"""P5 run orchestration over a curated dataset (read-only input).

Stages: inventory → duplicate clustering → triage → model classification →
OCR/context → cross-modal checks → scoring → artifacts. Deterministic given
the serialized model outputs: artifacts contain no timestamps and no absolute
paths, IDs are content-derived, ordering is canonical, floats are rounded at
fixed precision. The review-template merge preserves human decisions exactly
like P1–P4.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dalel.pillars.multimodal_visual_evidence.assets import (
    DirectAssetSpec,
    InspectedAsset,
    cluster_duplicates,
    collect_curated_assets,
    collect_direct_assets,
    inspect_assets,
)
from dalel.pillars.multimodal_visual_evidence.checks import CheckOutcome, run_checks
from dalel.pillars.multimodal_visual_evidence.classification import (
    DecisionInputs,
    decide_classification,
)
from dalel.pillars.multimodal_visual_evidence.config import (
    ALL_CLASSES,
    CLASS_PROMPTS,
    CONFIDENCE_DECIMALS,
    OCR_MAX_ASSETS,
    REVIEW_TEMPLATE_FILENAME,
    REVIEW_TEMPLATE_LOW_INFORMATION_SEED,
    REVIEW_TEMPLATE_MAX_ROWS,
    SIMILARITY_DECIMALS,
    config_snapshot,
    prompts_fingerprint,
)
from dalel.pillars.multimodal_visual_evidence.context import (
    DocumentTextIndex,
    build_text_index,
    find_caption,
    find_figure_references,
    load_entity_terms,
    load_quant_page_counts,
    match_entity_terms,
    nearest_heading,
    page_snippet,
)
from dalel.pillars.multimodal_visual_evidence.embeddings import (
    VisualEmbeddingBackend,
    cosine_similarity,
    get_default_backend,
)
from dalel.pillars.multimodal_visual_evidence.input_contract import (
    check_document_membership,
    check_unique_asset_ids,
)
from dalel.pillars.multimodal_visual_evidence.ocr import (
    OcrEngine,
    OcrOutcome,
    eligible_for_ocr,
    get_default_engine,
)
from dalel.pillars.multimodal_visual_evidence.reports import render_p5_report
from dalel.pillars.multimodal_visual_evidence.schemas import (
    P5AssetContext,
    P5AssetRecord,
    P5Classification,
    P5DocumentScoreRecord,
    P5DuplicateCluster,
    P5FindingRecord,
    P5ProjectScoreRecord,
    P5Suppression,
    deterministic_id,
)
from dalel.pillars.multimodal_visual_evidence.scoring import score_document, score_project

ProgressCallback = Callable[[str], None]

_SEVERITY_SORT = {"high": 0, "medium": 1, "low": 2, "info": 3}

PHASES = (
    "inventory",
    "duplicate_clustering",
    "classification",
    "ocr_context",
    "cross_modal_checks",
    "findings",
    "completed",
)


class P5RunError(Exception):
    """Blocking P5 execution failure (missing/invalid input)."""


@dataclass
class P5Options:
    dataset_dir: Path
    output_dir: Path
    annotations_root: Path
    project_id: str | None = None
    p3_dir: Path | None = None
    p4_dir: Path | None = None
    direct_assets: list[DirectAssetSpec] = field(default_factory=list)
    backend: VisualEmbeddingBackend | None = None
    ocr_engine: OcrEngine | None = None
    job_id: str | None = None
    dossier_sections: dict[str, str] = field(default_factory=dict)
    document_hints: dict[str, str] = field(default_factory=dict)
    incoming_triage: dict[str, str] = field(default_factory=dict)
    write_review_template: bool = True
    progress: ProgressCallback | None = None
    # Live jobs may carry only directly uploaded images (no curated dataset).
    # With this flag and an explicit project_id, P5 analyzes the direct assets
    # alone instead of failing; text context is then honestly absent.
    allow_missing_dataset: bool = False


@dataclass
class P5RunResult:
    assets: list[P5AssetRecord] = field(default_factory=list)
    contexts: list[P5AssetContext] = field(default_factory=list)
    classifications: list[P5Classification] = field(default_factory=list)
    clusters: list[P5DuplicateCluster] = field(default_factory=list)
    findings: list[P5FindingRecord] = field(default_factory=list)
    suppressions: list[P5Suppression] = field(default_factory=list)
    document_scores: list[P5DocumentScoreRecord] = field(default_factory=list)
    project_scores: list[P5ProjectScoreRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    model_metadata: dict[str, Any] = field(default_factory=dict)
    review_template_path: Path | None = None
    review_template_created: bool = False
    review_template_preserved_decisions: int = 0
    review_template_stale_rows: int = 0


_PROCEDURAL_SECTIONS = {"procedural_publication_evidence"}


def _read_jsonl(path: Path, required: tuple[str, ...]) -> list[dict[str, Any]]:
    if not path.is_file():
        raise P5RunError(
            f"curated file is missing: {path};"
            " re-run `dalel curate` or point --dataset at a built dataset"
        )
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise P5RunError(f"{path.name}: line {line_number}: invalid JSON ({exc.msg})") from exc
        if not isinstance(record, dict):
            raise P5RunError(f"{path.name}: line {line_number}: record is not a JSON object")
        missing = [key for key in required if key not in record]
        if missing:
            raise P5RunError(
                f"{path.name}: line {line_number}: missing required field(s): {', '.join(missing)}"
            )
        records.append(record)
    return records


def _progress(options: P5Options, phase: str) -> None:
    if options.progress is not None:
        options.progress(phase)


def run_p5(options: P5Options) -> P5RunResult:
    dataset_present = (options.dataset_dir / "projects.jsonl").is_file()
    if dataset_present:
        projects = _read_jsonl(options.dataset_dir / "projects.jsonl", ("project_id",))
        documents = _read_jsonl(
            options.dataset_dir / "documents.jsonl", ("project_id", "document_id", "document_type")
        )
    elif options.allow_missing_dataset and options.direct_assets and options.project_id:
        projects = [{"project_id": options.project_id}]
        documents = []
    else:
        raise P5RunError(
            f"curated file is missing: {options.dataset_dir / 'projects.jsonl'};"
            " re-run `dalel curate` or point --dataset at a built dataset"
        )
    if options.project_id is not None:
        known = {str(p["project_id"]) for p in projects}
        if options.project_id not in known:
            raise P5RunError(f"--project-id {options.project_id!r} not in curated dataset")

    selected_projects = sorted(
        (
            str(p["project_id"])
            for p in projects
            if options.project_id is None or str(p["project_id"]) == options.project_id
        ),
    )
    selected_set = set(selected_projects)
    selected_documents = [d for d in documents if str(d["project_id"]) in selected_set]
    document_types = {str(d["document_id"]): str(d["document_type"]) for d in selected_documents}
    document_projects = {str(d["document_id"]): str(d["project_id"]) for d in selected_documents}

    # --- 1. inventory --------------------------------------------------------
    _progress(options, "inventory")
    inspected = collect_curated_assets(
        options.dataset_dir,
        job_id=options.job_id,
        document_types=document_types,
        dossier_sections=options.dossier_sections,
        incoming_triage=options.incoming_triage,
        project_filter=options.project_id,
    )
    inspected.extend(collect_direct_assets(options.direct_assets))
    inspected = [item for item in inspected if item.record.project_id in selected_set]
    check_unique_asset_ids([item.record.asset_id for item in inspected])
    direct_documents = {spec.document_id for spec in options.direct_assets}
    check_document_membership(
        {item.record.document_id for item in inspected},
        set(document_types),
        allow_extra=direct_documents,
    )
    inspect_assets(inspected)

    # --- 2. duplicate clustering --------------------------------------------
    _progress(options, "duplicate_clustering")
    clusters, membership = cluster_duplicates(inspected)
    cluster_by_id = {cluster.cluster_id: cluster for cluster in clusters}
    _assign_triage(inspected, clusters, membership)

    representatives = [
        item for item in inspected if item.record.triage_status == "analyzed_representative"
    ]
    representatives.sort(key=lambda item: item.record.asset_id)

    # --- 3. model classification --------------------------------------------
    _progress(options, "classification")
    backend = options.backend if options.backend is not None else get_default_backend()
    model_available = backend.available
    text_index = build_text_index(options.dataset_dir)
    contexts_draft = _draft_contexts(representatives, text_index, options)
    similarities = _encode_and_score(backend, representatives, contexts_draft)
    classifications = _classify(representatives, contexts_draft, similarities, model_available)

    # --- 4. OCR and context --------------------------------------------------
    _progress(options, "ocr_context")
    ocr_engine = options.ocr_engine if options.ocr_engine is not None else get_default_engine()
    _run_ocr(representatives, contexts_draft, clusters, inspected, ocr_engine)
    entity_terms = load_entity_terms(options.p4_dir)
    quant_counts = load_quant_page_counts(options.p3_dir)
    contexts = _finalize_contexts(
        representatives, contexts_draft, entity_terms, quant_counts, options
    )

    # --- 5. cross-modal checks ----------------------------------------------
    _progress(options, "cross_modal_checks")
    figure_refs = _figure_references_by_document(text_index, document_projects)
    asset_records = sorted(
        (item.record for item in inspected),
        key=lambda record: (
            record.project_id,
            record.document_id,
            record.image_id,
            record.asset_id,
        ),
    )
    outcome: CheckOutcome = run_checks(
        assets=asset_records,
        contexts={context.asset_id: context for context in contexts},
        classifications={c.asset_id: c for c in classifications},
        clusters=clusters,
        figure_refs_by_document=figure_refs,
        document_types=document_types,
        document_projects=document_projects,
        model_available=model_available,
    )

    # --- 6. findings / scoring ----------------------------------------------
    _progress(options, "findings")
    result = P5RunResult(
        assets=asset_records,
        contexts=sorted(contexts, key=lambda c: (c.project_id, c.asset_id)),
        classifications=sorted(classifications, key=lambda c: (c.project_id, c.asset_id)),
        clusters=clusters,
        findings=outcome.findings,
        suppressions=outcome.suppressions,
    )
    _score(result, selected_projects, selected_documents, direct_documents, model_available)
    result.model_metadata = _model_metadata(backend, ocr_engine, model_available)
    result.metrics = _build_metrics(result, options, selected_projects, model_available)
    _write_outputs(options, result, cluster_by_id)
    _progress(options, "completed")
    return result


# --- triage ------------------------------------------------------------------


def _assign_triage(
    inspected: list[InspectedAsset],
    clusters: list[P5DuplicateCluster],
    membership: dict[str, str],
) -> None:
    representative_ids = {cluster.representative_asset_id for cluster in clusters}
    cluster_kind = {cluster.cluster_id: cluster.kind for cluster in clusters}
    representative_of = {
        cluster.cluster_id: cluster.representative_asset_id for cluster in clusters
    }
    for item in inspected:
        record = item.record
        cluster_id = membership.get(record.asset_id)
        record.duplicate_cluster_id = cluster_id
        if record.dossier_section in _PROCEDURAL_SECTIONS:
            record.procedural_supporting_evidence = True

        if item.path is None or item.decode_failed:
            record.triage_status = "unsupported"
            record.triage_reason = (
                "Байты изображения отсутствуют или не декодируются; семантический"
                " анализ невозможен."
            )
            continue
        if cluster_id is not None and record.asset_id not in representative_ids:
            record.triage_status = "excluded_duplicate"
            record.duplicate_of_asset_id = representative_of[cluster_id]
            record.triage_reason = (
                "Дубликат другого визуального актива; анализируется один представитель кластера."
            )
            continue
        kind = cluster_kind.get(cluster_id) if cluster_id else None
        if kind == "repeated_text_header":
            record.triage_status = "excluded_repeated_header"
            record.triage_reason = (
                "Представитель кластера повторяемого текстового колонтитула;"
                " исключён из экологического визуального анализа."
            )
            continue
        if kind == "logo_or_branding":
            record.triage_status = "excluded_logo_or_branding"
            record.triage_reason = (
                "Представитель кластера логотипа/оформления; исключён из"
                " экологического визуального анализа."
            )
            continue
        if item.uniform:
            record.triage_status = "excluded_low_information"
            record.triage_reason = "Растр пустой или почти однотонный."
            continue
        if item.tiny:
            record.triage_status = "excluded_low_information"
            record.triage_reason = "Растр слишком мал для надёжного семантического анализа."
            continue
        record.triage_status = "analyzed_representative"
        record.eligible_for_analysis = True
        record.triage_reason = (
            "Представитель кластера, выбранный для анализа."
            if cluster_id is not None
            else "Уникальное изображение, пригодное для анализа."
        )


# --- context drafting ---------------------------------------------------------


@dataclass
class _ContextDraft:
    caption: str | None = None
    heading: str | None = None
    section_id: str | None = None
    snippet: str | None = None
    figure_refs: list[str] = field(default_factory=list)
    ocr: OcrOutcome | None = None
    caption_similarity: float | None = None
    context_similarity: float | None = None
    limitations: list[str] = field(default_factory=list)


def _draft_contexts(
    representatives: list[InspectedAsset],
    text_index: dict[str, DocumentTextIndex],
    options: P5Options,
) -> dict[str, _ContextDraft]:
    drafts: dict[str, _ContextDraft] = {}
    for item in representatives:
        record = item.record
        draft = _ContextDraft()
        index = text_index.get(record.document_id)
        if index is None:
            draft.limitations.append(
                "Текст документа недоступен; подпись и контекст страницы не определены."
            )
        else:
            page_text = (
                index.page_text.get(record.page_number) if record.page_number is not None else None
            )
            if page_text:
                draft.caption = find_caption(page_text)
                draft.snippet = page_snippet(page_text)
                draft.figure_refs = find_figure_references(page_text)
            else:
                draft.limitations.append("Текст страницы недоступен; подпись не определена.")
            heading, section_id = nearest_heading(index, record.page_number)
            draft.heading = heading
            draft.section_id = section_id
        drafts[record.asset_id] = draft
    return drafts


def _encode_and_score(
    backend: VisualEmbeddingBackend,
    representatives: list[InspectedAsset],
    drafts: dict[str, _ContextDraft],
) -> dict[str, dict[str, float]]:
    """Per-representative class similarities (mean over prompt ensembles)."""
    if not backend.available or not representatives:
        return {}
    prompt_texts: list[str] = []
    prompt_slices: dict[str, tuple[int, int]] = {}
    for visual_class in ALL_CLASSES:
        prompts = CLASS_PROMPTS.get(visual_class)
        if not prompts:
            continue
        start = len(prompt_texts)
        prompt_texts.extend(prompts)
        prompt_slices[visual_class] = (start, len(prompt_texts))
    prompt_embeddings = backend.encode_texts(prompt_texts)

    paths = [item.path for item in representatives if item.path is not None]
    image_embeddings = backend.encode_images(paths)
    embeddings_by_asset: dict[str, list[float] | None] = {}
    cursor = 0
    for item in representatives:
        if item.path is None:
            embeddings_by_asset[item.record.asset_id] = None
        else:
            embeddings_by_asset[item.record.asset_id] = image_embeddings[cursor]
            cursor += 1

    # Cross-modal caption/context similarities share the same encoder.
    unique_texts: dict[str, int] = {}
    for draft in drafts.values():
        for text in (draft.caption, draft.snippet):
            if text and text not in unique_texts:
                unique_texts[text] = len(unique_texts)
    context_embeddings = backend.encode_texts(list(unique_texts)) if unique_texts else []

    similarities: dict[str, dict[str, float]] = {}
    for item in representatives:
        asset_id = item.record.asset_id
        image_embedding = embeddings_by_asset.get(asset_id)
        if not image_embedding:
            continue
        per_class: dict[str, float] = {}
        for visual_class, (start, end) in prompt_slices.items():
            values = [
                cosine_similarity(image_embedding, prompt_embeddings[index])
                for index in range(start, end)
                if prompt_embeddings[index]
            ]
            if values:
                per_class[visual_class] = round(sum(values) / len(values), SIMILARITY_DECIMALS)
        similarities[asset_id] = per_class
        draft = drafts[asset_id]
        if draft.caption and context_embeddings:
            embedding = context_embeddings[unique_texts[draft.caption]]
            if embedding:
                draft.caption_similarity = round(
                    cosine_similarity(image_embedding, embedding), CONFIDENCE_DECIMALS
                )
        if draft.snippet and context_embeddings:
            embedding = context_embeddings[unique_texts[draft.snippet]]
            if embedding:
                draft.context_similarity = round(
                    cosine_similarity(image_embedding, embedding), CONFIDENCE_DECIMALS
                )
    return similarities


def _classify(
    representatives: list[InspectedAsset],
    drafts: dict[str, _ContextDraft],
    similarities: dict[str, dict[str, float]],
    model_available: bool,
) -> list[P5Classification]:
    classifications: list[P5Classification] = []
    for item in representatives:
        record = item.record
        draft = drafts[record.asset_id]
        decision = decide_classification(
            DecisionInputs(
                model_available=model_available,
                similarities=similarities.get(record.asset_id, {}),
                caption=draft.caption,
                display_hint=record.display_name_hint or "",
                procedural_section=record.dossier_section in _PROCEDURAL_SECTIONS,
                incoming_triage_state=record.incoming_triage_state,
            )
        )
        if decision.predicted_class == "procedural_notice":
            record.procedural_supporting_evidence = True
        classifications.append(
            P5Classification(
                classification_id=deterministic_id("P5L", record.asset_id),
                asset_id=record.asset_id,
                project_id=record.project_id,
                document_id=record.document_id,
                predicted_class=decision.predicted_class,
                classification_confidence=decision.classification_confidence,
                decision_path=decision.decision_path,  # type: ignore[arg-type]
                model_status="available" if model_available else "unavailable",
                competing_classes=decision.competing,
                deterministic_signals=sorted(decision.deterministic_signals),
                model_signals=similarities.get(record.asset_id, {}),
                context_signals=sorted(decision.context_signals),
                limitations=decision.limitations,
            )
        )
    return classifications


def _run_ocr(
    representatives: list[InspectedAsset],
    drafts: dict[str, _ContextDraft],
    clusters: list[P5DuplicateCluster],
    inspected: list[InspectedAsset],
    engine: OcrEngine,
) -> None:
    """OCR analyzed representatives plus excluded-cluster representatives."""
    by_id = {item.record.asset_id: item for item in inspected}
    targets: list[InspectedAsset] = list(representatives)
    excluded_reps = [
        by_id[cluster.representative_asset_id]
        for cluster in clusters
        if cluster.kind in {"repeated_text_header", "logo_or_branding"}
        and cluster.representative_asset_id in by_id
    ]
    targets.extend(excluded_reps)
    targets.sort(key=lambda item: item.record.asset_id)
    ran = 0
    outcomes: dict[str, OcrOutcome] = {}
    for item in targets:
        record = item.record
        if item.path is None or not eligible_for_ocr(record.width_px, record.height_px):
            outcomes[record.asset_id] = OcrOutcome(
                status="not_run", failure_reason="image too small or bytes unavailable"
            )
            continue
        if ran >= OCR_MAX_ASSETS:
            outcomes[record.asset_id] = OcrOutcome(
                status="not_run", failure_reason="ocr asset budget reached"
            )
            continue
        outcomes[record.asset_id] = engine.read(item.path)
        ran += 1
    for item in representatives:
        draft = drafts[item.record.asset_id]
        draft.ocr = outcomes.get(item.record.asset_id)
    for cluster in clusters:
        outcome = outcomes.get(cluster.representative_asset_id)
        if outcome is not None and outcome.status == "completed" and outcome.text:
            cluster.repeated_ocr_text = outcome.text[:200]


def _finalize_contexts(
    representatives: list[InspectedAsset],
    drafts: dict[str, _ContextDraft],
    entity_terms: dict[str, list[str]],
    quant_counts: dict[tuple[str, int], int],
    options: P5Options,
) -> list[P5AssetContext]:
    contexts: list[P5AssetContext] = []
    for item in representatives:
        record = item.record
        draft = drafts[record.asset_id]
        ocr = draft.ocr
        terms = entity_terms.get(record.project_id, [])
        matched = match_entity_terms(
            [draft.caption, draft.snippet, ocr.text if ocr else None], terms
        )
        limitations = list(draft.limitations)
        if not entity_terms and options.p4_dir is not None:
            limitations.append("Сущности P4 недоступны; пересечение с графом не проверялось.")
        if options.p4_dir is None:
            limitations.append("Каталог результатов P4 не задан; связь с сущностями не строилась.")
        if options.p3_dir is None:
            limitations.append(
                "Каталог результатов P3 не задан; количественный контекст не подключён."
            )
        quant = (
            quant_counts.get((record.document_id, record.page_number), 0)
            if record.page_number is not None
            else 0
        )
        contexts.append(
            P5AssetContext(
                context_id=deterministic_id("P5X", record.asset_id),
                asset_id=record.asset_id,
                project_id=record.project_id,
                document_id=record.document_id,
                page_number=record.page_number,
                caption=draft.caption,
                caption_source="page_caption_line" if draft.caption else "none",
                nearest_heading=draft.heading,
                section_id=draft.section_id,
                page_text_excerpt=draft.snippet,
                figure_references_on_page=draft.figure_refs,
                entity_terms_matched=matched,
                quantitative_mentions_on_page=quant,
                ocr_status=(ocr.status if ocr else "not_run"),  # type: ignore[arg-type]
                ocr_engine=ocr.engine if ocr else None,
                ocr_languages=list(ocr.languages) if ocr else [],
                ocr_text=ocr.text if ocr else None,
                ocr_mean_confidence=ocr.mean_confidence if ocr else None,
                ocr_failure_reason=ocr.failure_reason if ocr else None,
                image_caption_similarity=draft.caption_similarity,
                image_context_similarity=draft.context_similarity,
                limitations=limitations,
            )
        )
    return contexts


def _figure_references_by_document(
    text_index: dict[str, DocumentTextIndex],
    document_projects: dict[str, str],
) -> dict[str, list[tuple[int, str]]]:
    references: dict[str, list[tuple[int, str]]] = {}
    for document_id, index in sorted(text_index.items()):
        if document_id not in document_projects:
            continue
        rows: list[tuple[int, str]] = []
        for page_number in sorted(index.page_text):
            for reference in find_figure_references(index.page_text[page_number]):
                rows.append((page_number, reference))
        if rows:
            references[document_id] = rows
    return references


# --- scoring -----------------------------------------------------------------


def _score(
    result: P5RunResult,
    selected_projects: list[str],
    selected_documents: list[dict[str, Any]],
    direct_documents: set[str],
    model_available: bool,
) -> None:
    findings_by_document: dict[str, list[P5FindingRecord]] = {}
    package_by_project: dict[str, list[P5FindingRecord]] = {}
    for finding in result.findings:
        if finding.document_id is not None:
            findings_by_document.setdefault(finding.document_id, []).append(finding)
        else:
            package_by_project.setdefault(finding.project_id, []).append(finding)

    assets_by_document: dict[str, list[P5AssetRecord]] = {}
    for asset in result.assets:
        assets_by_document.setdefault(asset.document_id, []).append(asset)

    document_rows: list[tuple[str, str, str | None]] = [
        (str(d["project_id"]), str(d["document_id"]), str(d["document_type"]))
        for d in selected_documents
    ]
    for asset in result.assets:
        if asset.document_id in direct_documents:
            row = (asset.project_id, asset.document_id, asset.document_type)
            if row not in document_rows:
                document_rows.append(row)
    document_rows.sort(key=lambda row: (row[0], row[1]))

    for project_id in selected_projects:
        project_documents = [row for row in document_rows if row[0] == project_id]
        document_scores = []
        for _, document_id, document_type in project_documents:
            doc_assets = assets_by_document.get(document_id, [])
            document_scores.append(
                score_document(
                    project_id,
                    document_id,
                    document_type,
                    findings_by_document.get(document_id, []),
                    asset_count=len(doc_assets),
                    analyzed_count=sum(
                        1 for a in doc_assets if a.triage_status == "analyzed_representative"
                    ),
                    excluded_duplicate_count=sum(
                        1 for a in doc_assets if a.triage_status == "excluded_duplicate"
                    ),
                )
            )
        result.document_scores.extend(document_scores)
        project_assets = [a for a in result.assets if a.project_id == project_id]
        result.project_scores.append(
            score_project(
                project_id,
                document_scores,
                package_by_project.get(project_id, []),
                assets=project_assets,
                clusters=[c for c in result.clusters if c.project_id == project_id],
                classifications=[c for c in result.classifications if c.project_id == project_id],
                contexts=[c for c in result.contexts if c.project_id == project_id],
                model_available=model_available,
            )
        )


# --- metadata / metrics ------------------------------------------------------


def _model_metadata(
    backend: VisualEmbeddingBackend, ocr_engine: OcrEngine, model_available: bool
) -> dict[str, Any]:
    metadata = dict(backend.metadata)
    metadata["prompts_sha256"] = prompts_fingerprint()
    try:
        ocr_available = ocr_engine.available
    except Exception:
        ocr_available = False
    metadata["ocr"] = {
        "engine": ocr_engine.name,
        "status": "available" if ocr_available else "unavailable",
    }
    metadata["model_status"] = "available" if model_available else "unavailable"
    return metadata


def _input_fingerprint(dataset_dir: Path) -> str | None:
    report_path = dataset_dir / "build_report.json"
    if not report_path.is_file():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = report.get("input_fingerprint")
    return str(value) if isinstance(value, str) else None


def _build_metrics(
    result: P5RunResult,
    options: P5Options,
    selected_projects: list[str],
    model_available: bool,
) -> dict[str, Any]:
    from dalel.pillars.multimodal_visual_evidence import P5_VERSION
    from dalel.pillars.multimodal_visual_evidence.config import P5_SCORING_CONFIG_VERSION

    by_triage: dict[str, int] = {}
    for asset in result.assets:
        by_triage[asset.triage_status] = by_triage.get(asset.triage_status, 0) + 1
    by_class: dict[str, int] = {}
    for classification in result.classifications:
        by_class[classification.predicted_class] = (
            by_class.get(classification.predicted_class, 0) + 1
        )
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for finding in result.findings:
        by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
    by_cluster_kind: dict[str, int] = {}
    for cluster in result.clusters:
        by_cluster_kind[cluster.kind] = by_cluster_kind.get(cluster.kind, 0) + 1
    ocr_status: dict[str, int] = {}
    for context in result.contexts:
        ocr_status[context.ocr_status] = ocr_status.get(context.ocr_status, 0) + 1
    suppressed_by_reason: dict[str, int] = {}
    for suppression in result.suppressions:
        suppressed_by_reason[suppression.reason] = (
            suppressed_by_reason.get(suppression.reason, 0) + 1
        )

    per_project: dict[str, dict[str, Any]] = {}
    for score in result.project_scores:
        per_project[score.project_id] = {
            "review_priority": score.visual_evidence_review_priority_score,
            "total_assets": score.total_asset_count,
            "analyzed_representatives": score.analyzed_representative_count,
            "excluded_duplicates": score.excluded_duplicate_count,
            "visual_coverage": score.visual_coverage,
            "assessment_confidence": score.assessment_confidence,
        }

    return {
        "p5_version": P5_VERSION,
        "scoring_config_version": P5_SCORING_CONFIG_VERSION,
        "input_fingerprint": _input_fingerprint(options.dataset_dir),
        "projects_analyzed": len(selected_projects),
        "documents_analyzed": len(result.document_scores),
        "assets_total": len(result.assets),
        "assets_by_triage_status": dict(sorted(by_triage.items())),
        "analyzed_representatives": sum(
            1 for a in result.assets if a.triage_status == "analyzed_representative"
        ),
        "duplicate_clusters_total": len(result.clusters),
        "duplicate_clusters_by_kind": dict(sorted(by_cluster_kind.items())),
        "classifications_by_class": dict(sorted(by_class.items())),
        "contexts_total": len(result.contexts),
        "contexts_with_caption": sum(1 for c in result.contexts if c.caption),
        "contexts_with_entity_overlap": sum(1 for c in result.contexts if c.entity_terms_matched),
        "ocr_by_status": dict(sorted(ocr_status.items())),
        "findings_total": len(result.findings),
        "findings_by_type": dict(sorted(by_type.items())),
        "findings_by_severity": dict(sorted(by_severity.items())),
        "suppressions_total": len(result.suppressions),
        "suppressions_by_reason": dict(sorted(suppressed_by_reason.items())),
        "model_status": "available" if model_available else "unavailable",
        "per_project": dict(sorted(per_project.items())),
        "expert_evaluation": _expert_evaluation(options, result),
        "evaluation_note": (
            "Классификация — модельная аффинность, а не подтверждённая точность;"
            " покрытие и уверенность описывают полноту анализа, а не качество"
            " документации. Отсутствие находок не подтверждает корректность"
            " визуальных материалов."
        ),
    }


# --- expert labels ------------------------------------------------------------

_TEMPLATE_HUMAN_FIELDS = (
    "reviewed_class",
    "useful_for_p5",
    "duplicate_cluster_correct",
    "finding_correct",
    "reviewer_note",
)


def _expert_evaluation(options: P5Options, result: P5RunResult) -> dict[str, Any]:
    template_path = options.annotations_root / REVIEW_TEMPLATE_FILENAME
    if not template_path.is_file():
        return {"status": "no_completed_labels", "labeled_rows": 0}
    rows: list[dict[str, Any]] = []
    for line in template_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    labeled = [row for row in rows if row.get("reviewed_class")]
    if not labeled:
        return {"status": "no_completed_labels", "labeled_rows": 0}

    predictions = {c.asset_id: c.predicted_class for c in result.classifications}
    excluded_status = {a.asset_id: a.triage_status for a in result.assets}
    per_class: dict[str, dict[str, int]] = {}
    correct = 0
    for row in labeled:
        asset_id = str(row.get("asset_id") or "")
        reviewed = str(row.get("reviewed_class") or "")
        predicted = predictions.get(asset_id) or str(row.get("predicted_class") or "")
        stats = per_class.setdefault(reviewed, {"tp": 0, "fn": 0})
        if predicted == reviewed:
            stats["tp"] += 1
            correct += 1
        else:
            stats["fn"] += 1
            per_class.setdefault(predicted, {"tp": 0, "fn": 0})
    useful_rows = [row for row in labeled if row.get("useful_for_p5") is not None]
    useful_correct = sum(
        1
        for row in useful_rows
        if bool(row.get("useful_for_p5"))
        == (excluded_status.get(str(row.get("asset_id") or "")) == "analyzed_representative")
    )
    cluster_rows = [row for row in labeled if row.get("duplicate_cluster_correct") is not None]
    cluster_correct = sum(1 for row in cluster_rows if bool(row.get("duplicate_cluster_correct")))
    false_exclusions = sum(
        1
        for row in useful_rows
        if bool(row.get("useful_for_p5"))
        and excluded_status.get(str(row.get("asset_id") or ""), "").startswith("excluded")
    )
    return {
        "status": "labels_available",
        "labeled_rows": len(labeled),
        "class_accuracy": round(correct / len(labeled), 3),
        "per_class": {name: stats for name, stats in sorted(per_class.items())},
        "useful_agreement": (round(useful_correct / len(useful_rows), 3) if useful_rows else None),
        "duplicate_cluster_accuracy": (
            round(cluster_correct / len(cluster_rows), 3) if cluster_rows else None
        ),
        "false_exclusion_rate": (
            round(false_exclusions / len(useful_rows), 3) if useful_rows else None
        ),
    }


# --- outputs -----------------------------------------------------------------


def _write_outputs(
    options: P5Options,
    result: P5RunResult,
    cluster_by_id: dict[str, P5DuplicateCluster],
) -> None:
    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    def _write_jsonl(name: str, records: list[dict[str, Any]]) -> None:
        with (output_dir / name).open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")

    _write_jsonl("assets.jsonl", [a.model_dump(mode="json") for a in result.assets])
    _write_jsonl("asset_contexts.jsonl", [c.model_dump(mode="json") for c in result.contexts])
    _write_jsonl(
        "classifications.jsonl", [c.model_dump(mode="json") for c in result.classifications]
    )
    _write_jsonl("duplicate_clusters.jsonl", [c.model_dump(mode="json") for c in result.clusters])
    _write_jsonl("findings.jsonl", [f.model_dump(mode="json") for f in result.findings])
    _write_jsonl("suppressions.jsonl", [s.model_dump(mode="json") for s in result.suppressions])
    _write_jsonl(
        "document_scores.jsonl", [s.model_dump(mode="json") for s in result.document_scores]
    )
    _write_jsonl("project_scores.jsonl", [s.model_dump(mode="json") for s in result.project_scores])
    (output_dir / "metrics.json").write_text(
        json.dumps(result.metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(config_snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "model_metadata.json").write_text(
        json.dumps(result.model_metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(render_p5_report(result), encoding="utf-8")

    if options.write_review_template:
        _merge_review_template(options, result, output_dir)


def _review_template_rows(result: P5RunResult) -> list[dict[str, Any]]:
    """Representatives, excluded-cluster reps and a small excluded sample."""
    predictions = {c.asset_id: c.predicted_class for c in result.classifications}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(asset: P5AssetRecord, predicted: str) -> None:
        if asset.asset_id in seen or len(rows) >= REVIEW_TEMPLATE_MAX_ROWS:
            return
        seen.add(asset.asset_id)
        rows.append(
            {
                "asset_id": asset.asset_id,
                "predicted_class": predicted,
                "duplicate_cluster_id": asset.duplicate_cluster_id,
                "reviewed_class": None,
                "useful_for_p5": None,
                "duplicate_cluster_correct": None,
                "finding_correct": None,
                "reviewer_note": None,
            }
        )

    for asset in result.assets:
        if asset.triage_status == "analyzed_representative":
            _add(asset, predictions.get(asset.asset_id, "unknown"))
    for asset in result.assets:
        if asset.triage_status in {"excluded_repeated_header", "excluded_logo_or_branding"}:
            _add(
                asset,
                "text_fragment"
                if asset.triage_status == "excluded_repeated_header"
                else "logo_or_branding",
            )
    low_information = 0
    for asset in result.assets:
        if asset.triage_status == "excluded_low_information":
            _add(asset, "unknown")
            low_information += 1
            if low_information >= REVIEW_TEMPLATE_LOW_INFORMATION_SEED:
                break
    rows.sort(key=lambda row: str(row["asset_id"]))
    return rows


def _merge_review_template(options: P5Options, result: P5RunResult, output_dir: Path) -> None:
    """Create/update the expert review template WITHOUT losing human decisions."""
    options.annotations_root.mkdir(parents=True, exist_ok=True)
    template_path = options.annotations_root / REVIEW_TEMPLATE_FILENAME
    existing: dict[str, dict[str, Any]] = {}
    if template_path.exists():
        for line in template_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing[str(row.get("asset_id"))] = row

    def _has_human_data(row: dict[str, Any]) -> bool:
        return any(row.get(field_name) is not None for field_name in _TEMPLATE_HUMAN_FIELDS)

    rows = _review_template_rows(result)
    preserved = 0
    for row in rows:
        old = existing.get(str(row["asset_id"]))
        if old is None:
            continue
        for key in _TEMPLATE_HUMAN_FIELDS:
            if old.get(key) is not None:
                row[key] = old[key]
        if _has_human_data(old):
            preserved += 1

    current_ids = {str(row["asset_id"]) for row in rows}
    stale = [row for asset_id, row in existing.items() if asset_id not in current_ids]

    with template_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
    if stale:
        stale_path = output_dir / "review_template_stale.jsonl"
        with stale_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in stale:
                handle.write(json.dumps(row, ensure_ascii=False))
                handle.write("\n")

    result.review_template_path = template_path
    result.review_template_created = not existing
    result.review_template_preserved_decisions = preserved
    result.review_template_stale_rows = len(stale)
