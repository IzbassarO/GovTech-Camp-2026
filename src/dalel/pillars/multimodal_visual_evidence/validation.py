"""P5 output validation: identity, clusters, decisions, findings, scores.

Independent of the pipeline: re-reads the artifacts and the curated dataset
and re-derives every ID, cluster, representative, classification decision,
finding, suppression, score, coverage and confidence from first principles,
so tampering (a changed hash, a moved page, a flipped class, an inflated
score, a swapped representative, a rewritten finding) is detected. Model and
OCR outputs are replayed from their serialized signals — the validator never
loads the model.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dalel.pillars.multimodal_visual_evidence.assets import InspectedAsset, cluster_duplicates
from dalel.pillars.multimodal_visual_evidence.checks import run_checks
from dalel.pillars.multimodal_visual_evidence.classification import (
    DecisionInputs,
    decide_classification,
)
from dalel.pillars.multimodal_visual_evidence.config import (
    ALL_CLASSES,
    ASSESSMENT_CONFIDENCE_MAX,
    ASSESSMENT_CONFIDENCE_MIN,
    ASSESSMENT_CONFIDENCE_WEIGHTS,
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    FINDING_TYPES,
    META_INTEGRATION_STATUS,
    SCORE_CAP,
    SEVERITY_POINTS,
    prompts_fingerprint,
)
from dalel.pillars.multimodal_visual_evidence.context import (
    build_text_index,
    find_figure_references,
)
from dalel.pillars.multimodal_visual_evidence.schemas import (
    SEVERITIES,
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
from dalel.pillars.multimodal_visual_evidence.scoring import compute_assessment_confidence

_OUTPUT_FILES = (
    "assets.jsonl",
    "asset_contexts.jsonl",
    "classifications.jsonl",
    "duplicate_clusters.jsonl",
    "findings.jsonl",
    "suppressions.jsonl",
    "document_scores.jsonl",
    "project_scores.jsonl",
    "metrics.json",
    "config_snapshot.json",
    "model_metadata.json",
    "report.md",
)

_INPUT_FILES = ("projects.jsonl", "documents.jsonl", "images.jsonl", "pages.jsonl")

_PROCEDURAL_SECTIONS = {"procedural_publication_evidence"}


@dataclass
class P5ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"{path.name}:{line_number}: blank line")
        records.append(json.loads(line))
    return records


def _load(path: Path, model: Any, result: P5ValidationResult, name: str) -> list[Any]:
    records: list[Any] = []
    for index, raw in enumerate(_read_jsonl(path), start=1):
        try:
            records.append(model.model_validate(raw))
        except ValidationError as exc:
            result.error(f"{name}:{index}: schema violation: {exc.errors()[:2]}")
    return records


def validate_p5_outputs(
    dataset_dir: Path,
    output_dir: Path,
    annotations_root: Path | None = None,
) -> P5ValidationResult:
    result = P5ValidationResult()

    for name in _OUTPUT_FILES:
        if not (output_dir / name).is_file():
            result.error(f"missing output file: {name}")
    if not result.ok:
        return result

    try:
        assets = _load(output_dir / "assets.jsonl", P5AssetRecord, result, "assets")
        contexts = _load(
            output_dir / "asset_contexts.jsonl", P5AssetContext, result, "asset_contexts"
        )
        classifications = _load(
            output_dir / "classifications.jsonl", P5Classification, result, "classifications"
        )
        clusters = _load(
            output_dir / "duplicate_clusters.jsonl", P5DuplicateCluster, result, "clusters"
        )
        findings = _load(output_dir / "findings.jsonl", P5FindingRecord, result, "findings")
        suppressions = _load(
            output_dir / "suppressions.jsonl", P5Suppression, result, "suppressions"
        )
        document_scores = _load(
            output_dir / "document_scores.jsonl", P5DocumentScoreRecord, result, "document_scores"
        )
        project_scores = _load(
            output_dir / "project_scores.jsonl", P5ProjectScoreRecord, result, "project_scores"
        )
    except (ValueError, json.JSONDecodeError) as exc:
        result.error(f"output parse failure: {exc}")
        return result
    if not result.ok:
        return result

    result.counts = {
        "assets": len(assets),
        "asset_contexts": len(contexts),
        "classifications": len(classifications),
        "duplicate_clusters": len(clusters),
        "findings": len(findings),
        "suppressions": len(suppressions),
        "document_scores": len(document_scores),
        "project_scores": len(project_scores),
    }

    _check_unique_ids(result, assets, contexts, classifications, clusters, findings, suppressions)
    _check_asset_identity(result, dataset_dir, assets)
    _check_cluster_replay(result, assets, clusters)
    _check_triage_consistency(result, assets, clusters)
    _check_context_grounding(result, dataset_dir, assets, contexts)
    _check_classification_replay(result, assets, contexts, classifications)
    _check_findings_replay(
        result,
        dataset_dir,
        assets,
        contexts,
        classifications,
        clusters,
        findings,
        suppressions,
        project_scores,
    )
    _check_finding_rules(result, findings, assets, clusters)
    _check_scores(
        result,
        assets,
        clusters,
        classifications,
        contexts,
        findings,
        document_scores,
        project_scores,
    )
    _check_ordering(result, assets, contexts, classifications, clusters, findings)
    _check_metrics_and_report(
        result, output_dir, dataset_dir, assets, clusters, findings, classifications, project_scores
    )
    _check_model_metadata(result, output_dir, classifications)
    _check_review_template(result, output_dir, assets, annotations_root, dataset_dir)
    _check_no_absolute_paths(result, output_dir)
    _check_dataset_untouched(result, dataset_dir)
    _check_output_location(result, dataset_dir, output_dir)
    return result


# --- ids ----------------------------------------------------------------------


def _check_unique_ids(
    result: P5ValidationResult,
    assets: list[P5AssetRecord],
    contexts: list[P5AssetContext],
    classifications: list[P5Classification],
    clusters: list[P5DuplicateCluster],
    findings: list[P5FindingRecord],
    suppressions: list[P5Suppression],
) -> None:
    for label, ids, prefix in (
        ("asset", [a.asset_id for a in assets], "P5A__"),
        ("context", [c.context_id for c in contexts], "P5X__"),
        ("classification", [c.classification_id for c in classifications], "P5L__"),
        ("cluster", [c.cluster_id for c in clusters], "P5D__"),
        ("finding", [f.finding_id for f in findings], "P5__"),
        ("suppression", [s.suppression_id for s in suppressions], "P5S__"),
    ):
        if len(set(ids)) != len(ids):
            result.error(f"duplicate {label} id values")
        for identifier in ids:
            if not identifier.startswith(prefix):
                result.error(f"{label} id without {prefix} prefix: {identifier}")


def _check_asset_identity(
    result: P5ValidationResult, dataset_dir: Path, assets: list[P5AssetRecord]
) -> None:
    for asset in assets:
        recomputed = deterministic_id(
            "P5A",
            asset.project_id,
            asset.document_id,
            asset.image_id,
            asset.file_sha256 or "metadata-only",
        )
        if asset.asset_id != recomputed:
            result.error(
                f"{asset.asset_id}: asset id does not recompute from provenance"
                " (possible identity tampering)"
            )
        if asset.image_source is not None:
            relative = asset.image_source.relative_path
            if relative.startswith("/") or ".." in relative.split("/"):
                result.error(f"{asset.asset_id}: unsafe image_source path")
            elif asset.image_source.root == "curated" and asset.file_sha256:
                target = dataset_dir / relative
                if target.is_file():
                    actual = hashlib.sha256(target.read_bytes()).hexdigest()
                    if actual != asset.file_sha256:
                        result.error(
                            f"{asset.asset_id}: image bytes on disk do not match the"
                            " recorded SHA-256 (source tampering)"
                        )


# --- clusters -----------------------------------------------------------------


def _check_cluster_replay(
    result: P5ValidationResult,
    assets: list[P5AssetRecord],
    clusters: list[P5DuplicateCluster],
) -> None:
    reconstructed = [
        InspectedAsset(
            record=asset.model_copy(deep=True),
            path=None,
            uniform=asset.near_uniform,
            tiny=asset.tiny,
        )
        for asset in assets
    ]
    replayed, _membership = cluster_duplicates(reconstructed)
    replayed_dump = [c.model_dump(mode="json", exclude={"repeated_ocr_text"}) for c in replayed]
    actual_dump = [c.model_dump(mode="json", exclude={"repeated_ocr_text"}) for c in clusters]
    if replayed_dump != actual_dump:
        result.error(
            "duplicate_clusters.jsonl does not reproduce from asset hashes and"
            " geometry (cluster or representative tampering)"
        )


def _check_triage_consistency(
    result: P5ValidationResult,
    assets: list[P5AssetRecord],
    clusters: list[P5DuplicateCluster],
) -> None:
    cluster_by_id = {c.cluster_id: c for c in clusters}
    for asset in assets:
        if asset.triage_status == "excluded_duplicate":
            cluster = cluster_by_id.get(asset.duplicate_cluster_id or "")
            if cluster is None:
                result.error(f"{asset.asset_id}: duplicate without a resolvable cluster")
                continue
            if asset.asset_id == cluster.representative_asset_id:
                result.error(
                    f"{asset.asset_id}: cluster representative marked as excluded duplicate"
                )
            if asset.duplicate_of_asset_id != cluster.representative_asset_id:
                result.error(
                    f"{asset.asset_id}: duplicate_of does not point at the cluster representative"
                )
        if asset.triage_status == "analyzed_representative" and not asset.eligible_for_analysis:
            result.error(f"{asset.asset_id}: analyzed representative not marked eligible")
        if asset.eligible_for_analysis and asset.triage_status != "analyzed_representative":
            result.error(f"{asset.asset_id}: eligible asset with non-analyzed status")
    for cluster in clusters:
        if cluster.member_count != len(cluster.member_asset_ids):
            result.error(f"{cluster.cluster_id}: member_count does not match members")
        if cluster.representative_asset_id not in cluster.member_asset_ids:
            result.error(f"{cluster.cluster_id}: representative outside the cluster")


# --- context grounding --------------------------------------------------------


def _check_context_grounding(
    result: P5ValidationResult,
    dataset_dir: Path,
    assets: list[P5AssetRecord],
    contexts: list[P5AssetContext],
) -> None:
    assets_by_id = {a.asset_id: a for a in assets}
    analyzed_ids = {a.asset_id for a in assets if a.triage_status == "analyzed_representative"}
    context_ids = {c.asset_id for c in contexts}
    for missing in sorted(analyzed_ids - context_ids):
        result.error(f"{missing}: analyzed representative without a context record")
    for extra in sorted(context_ids - analyzed_ids):
        result.error(f"{extra}: context recorded for a non-analyzed asset")

    text_index = build_text_index(dataset_dir)
    for context in contexts:
        if context.context_id != deterministic_id("P5X", context.asset_id):
            result.error(f"{context.context_id}: context id does not recompute")
        asset = assets_by_id.get(context.asset_id)
        if asset is None:
            result.error(f"{context.context_id}: unresolved asset {context.asset_id}")
            continue
        if (asset.document_id, asset.project_id) != (context.document_id, context.project_id):
            result.error(f"{context.context_id}: document/project mismatch with asset")
        index = text_index.get(context.document_id)
        page_text = None
        if index is not None and context.page_number is not None:
            page_text = index.page_text.get(context.page_number)
        if context.caption:
            joined = " ".join((page_text or "").split()).casefold()
            if not page_text or " ".join(context.caption.split()).casefold() not in joined:
                result.error(
                    f"{context.context_id}: caption is not present in the source page"
                    " text (possible caption fabrication)"
                )
        if context.ocr_status == "completed" and not context.ocr_text:
            result.error(f"{context.context_id}: OCR marked completed without text")
        if context.ocr_status in {"not_run", "unavailable"} and context.ocr_text:
            result.error(f"{context.context_id}: OCR text present but engine did not run")
        for value in (context.image_caption_similarity, context.image_context_similarity):
            if value is not None and not -1.0 <= value <= 1.0:
                result.error(f"{context.context_id}: similarity out of range")


# --- classification replay ----------------------------------------------------


def _check_classification_replay(
    result: P5ValidationResult,
    assets: list[P5AssetRecord],
    contexts: list[P5AssetContext],
    classifications: list[P5Classification],
) -> None:
    assets_by_id = {a.asset_id: a for a in assets}
    contexts_by_id = {c.asset_id: c for c in contexts}
    analyzed_ids = {a.asset_id for a in assets if a.triage_status == "analyzed_representative"}
    classified_ids = {c.asset_id for c in classifications}
    for missing in sorted(analyzed_ids - classified_ids):
        result.error(f"{missing}: analyzed representative without a classification")
    for extra in sorted(classified_ids - analyzed_ids):
        result.error(f"{extra}: classification recorded for a non-analyzed asset")

    for classification in classifications:
        if classification.classification_id != deterministic_id("P5L", classification.asset_id):
            result.error(
                f"{classification.classification_id}: classification id does not recompute"
            )
        if classification.predicted_class not in ALL_CLASSES:
            result.error(
                f"{classification.classification_id}: unknown class"
                f" {classification.predicted_class}"
            )
        asset = assets_by_id.get(classification.asset_id)
        context = contexts_by_id.get(classification.asset_id)
        if asset is None:
            result.error(f"{classification.classification_id}: unresolved asset")
            continue
        decision = decide_classification(
            DecisionInputs(
                model_available=classification.model_status == "available",
                similarities=dict(classification.model_signals),
                caption=context.caption if context else None,
                display_hint=asset.display_name_hint or "",
                procedural_section=asset.dossier_section in _PROCEDURAL_SECTIONS,
                incoming_triage_state=asset.incoming_triage_state,
            )
        )
        if decision.predicted_class != classification.predicted_class:
            result.error(
                f"{classification.classification_id}: predicted class does not replay"
                f" from serialized signals (stored {classification.predicted_class},"
                f" replayed {decision.predicted_class})"
            )
        stored = classification.classification_confidence
        replayed = decision.classification_confidence
        if (stored is None) != (replayed is None):
            result.error(f"{classification.classification_id}: confidence presence does not replay")
        elif stored is not None and replayed is not None and abs(stored - replayed) > 0.001:
            result.error(
                f"{classification.classification_id}: confidence {stored} does not"
                f" replay from signals ({replayed})"
            )
        if decision.decision_path != classification.decision_path:
            result.error(f"{classification.classification_id}: decision path does not replay")


# --- findings replay ----------------------------------------------------------


def _dump(objects: list[Any]) -> list[dict[str, Any]]:
    return [obj.model_dump(mode="json") for obj in objects]


def _check_findings_replay(
    result: P5ValidationResult,
    dataset_dir: Path,
    assets: list[P5AssetRecord],
    contexts: list[P5AssetContext],
    classifications: list[P5Classification],
    clusters: list[P5DuplicateCluster],
    findings: list[P5FindingRecord],
    suppressions: list[P5Suppression],
    project_scores: list[P5ProjectScoreRecord],
) -> None:
    # The run may have been project-filtered; the analyzed project set is
    # exactly the set of project score records the run produced. Findings are
    # replayed against that same scope.
    selected_projects = {score.project_id for score in project_scores}
    documents_path = dataset_dir / "documents.jsonl"
    document_types: dict[str, str] = {}
    document_projects: dict[str, str] = {}
    if documents_path.is_file():
        for line in documents_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if selected_projects and str(row.get("project_id")) not in selected_projects:
                continue
            document_types[str(row.get("document_id"))] = str(row.get("document_type"))
            document_projects[str(row.get("document_id"))] = str(row.get("project_id"))
    for asset in assets:
        document_types.setdefault(asset.document_id, asset.document_type or "")
        document_projects.setdefault(asset.document_id, asset.project_id)

    text_index = build_text_index(dataset_dir)
    figure_refs: dict[str, list[tuple[int, str]]] = {}
    for document_id, index in sorted(text_index.items()):
        if document_id not in document_projects:
            continue
        rows: list[tuple[int, str]] = []
        for page_number in sorted(index.page_text):
            for reference in find_figure_references(index.page_text[page_number]):
                rows.append((page_number, reference))
        if rows:
            figure_refs[document_id] = rows

    model_available = any(c.model_status == "available" for c in classifications)
    try:
        outcome = run_checks(
            assets=assets,
            contexts={c.asset_id: c for c in contexts},
            classifications={c.asset_id: c for c in classifications},
            clusters=clusters,
            figure_refs_by_document=figure_refs,
            document_types=document_types,
            document_projects=document_projects,
            model_available=model_available,
        )
    except Exception as exc:  # replay must never crash the validator
        result.error(f"finding replay failed: {exc}")
        return
    if _dump(outcome.findings) != _dump(findings):
        result.error(
            "findings.jsonl does not reproduce from assets/contexts/classifications"
            " (finding tampering: fabricated evidence, altered severity or"
            " rewritten explanation)"
        )
    if _dump(outcome.suppressions) != _dump(suppressions):
        result.error(
            "suppressions.jsonl does not reproduce from the artifacts (suppression tampering)"
        )


def _check_finding_rules(
    result: P5ValidationResult,
    findings: list[P5FindingRecord],
    assets: list[P5AssetRecord],
    clusters: list[P5DuplicateCluster],
) -> None:
    asset_ids = {a.asset_id for a in assets}
    cluster_ids = {c.cluster_id for c in clusters}
    for finding in findings:
        if finding.finding_type not in FINDING_TYPES:
            result.error(f"{finding.finding_id}: unknown finding_type {finding.finding_type}")
        if finding.severity not in SEVERITIES:
            result.error(f"{finding.finding_id}: invalid severity {finding.severity}")
        if finding.severity == "high":
            result.error(f"{finding.finding_id}: high severity is not permitted in P5")
        if finding.priority_score != SEVERITY_POINTS.get(finding.severity):
            result.error(f"{finding.finding_id}: priority_score does not match severity")
        if finding.legal_conclusion is not False:
            result.error(f"{finding.finding_id}: legal_conclusion must be false")
        if not finding.limitations.strip():
            result.error(f"{finding.finding_id}: limitations must be stated")
        if finding.asset_id is not None and finding.asset_id not in asset_ids:
            result.error(f"{finding.finding_id}: unresolved asset {finding.asset_id}")
        for related in finding.related_asset_ids:
            if related not in asset_ids:
                result.error(f"{finding.finding_id}: unresolved related asset {related}")
        if (
            finding.duplicate_cluster_id is not None
            and finding.duplicate_cluster_id not in cluster_ids
        ):
            result.error(f"{finding.finding_id}: unresolved cluster")
        if finding.confidence is not None:
            if not 0.0 <= finding.confidence <= 1.0:
                result.error(f"{finding.finding_id}: confidence out of range")
            if finding.confidence_factors:
                recomputed = round(
                    min(
                        CONFIDENCE_MAX,
                        max(
                            CONFIDENCE_MIN,
                            sum(f.delta for f in finding.confidence_factors),
                        ),
                    ),
                    2,
                )
                if abs(recomputed - finding.confidence) > 0.001:
                    result.error(
                        f"{finding.finding_id}: confidence does not recompute from factors"
                    )
        if not finding.evidence:
            result.error(f"{finding.finding_id}: finding without evidence references")


# --- scores -------------------------------------------------------------------


def _check_scores(
    result: P5ValidationResult,
    assets: list[P5AssetRecord],
    clusters: list[P5DuplicateCluster],
    classifications: list[P5Classification],
    contexts: list[P5AssetContext],
    findings: list[P5FindingRecord],
    document_scores: list[P5DocumentScoreRecord],
    project_scores: list[P5ProjectScoreRecord],
) -> None:
    findings_by_document: dict[str, list[P5FindingRecord]] = {}
    package_by_project: dict[str, list[P5FindingRecord]] = {}
    for finding in findings:
        if finding.document_id is not None:
            findings_by_document.setdefault(finding.document_id, []).append(finding)
        else:
            package_by_project.setdefault(finding.project_id, []).append(finding)
    assets_by_document: dict[str, list[P5AssetRecord]] = {}
    for asset in assets:
        assets_by_document.setdefault(asset.document_id, []).append(asset)

    doc_scores_by_project: dict[str, list[int]] = {}
    for record in document_scores:
        expected = min(
            SCORE_CAP,
            sum(f.priority_score for f in findings_by_document.get(record.document_id, [])),
        )
        if record.visual_evidence_review_priority_score != expected:
            result.error(
                f"document score {record.document_id} does not recompute (expected {expected})"
            )
        doc_assets = assets_by_document.get(record.document_id, [])
        expected_counts = {
            "asset_count": len(doc_assets),
            "analyzed_representative_count": sum(
                1 for a in doc_assets if a.triage_status == "analyzed_representative"
            ),
            "excluded_duplicate_count": sum(
                1 for a in doc_assets if a.triage_status == "excluded_duplicate"
            ),
        }
        for name, value in expected_counts.items():
            if getattr(record, name) != value:
                result.error(f"document score {record.document_id}: {name} does not match assets")
        doc_scores_by_project.setdefault(record.project_id, []).append(expected)

    for project_record in project_scores:
        project_id = project_record.project_id
        doc_points = doc_scores_by_project.get(project_id, [])
        package_points = sum(f.priority_score for f in package_by_project.get(project_id, []))
        mean_documents = sum(doc_points) / len(doc_points) if doc_points else 0.0
        expected_total = min(SCORE_CAP, round(mean_documents) + package_points)
        if project_record.visual_evidence_review_priority_score != expected_total:
            result.error(
                f"project score {project_id} does not recompute (expected {expected_total})"
            )
        project_assets = [a for a in assets if a.project_id == project_id]
        analyzed = [a for a in project_assets if a.triage_status == "analyzed_representative"]
        eligible = [a for a in project_assets if a.eligible_for_analysis]
        expected_stats = {
            "total_asset_count": len(project_assets),
            "assets_with_bytes_count": sum(1 for a in project_assets if a.file_sha256 is not None),
            "eligible_asset_count": len(eligible),
            "analyzed_representative_count": len(analyzed),
            "excluded_duplicate_count": sum(
                1 for a in project_assets if a.triage_status == "excluded_duplicate"
            ),
            "excluded_low_information_count": sum(
                1 for a in project_assets if a.triage_status == "excluded_low_information"
            ),
            "excluded_header_or_logo_count": sum(
                1
                for a in project_assets
                if a.triage_status in {"excluded_repeated_header", "excluded_logo_or_branding"}
            ),
            "unsupported_asset_count": sum(
                1 for a in project_assets if a.triage_status == "unsupported"
            ),
            "procedural_asset_count": sum(
                1 for a in project_assets if a.procedural_supporting_evidence
            ),
            "duplicate_cluster_count": sum(1 for c in clusters if c.project_id == project_id),
        }
        for name, value in expected_stats.items():
            if getattr(project_record, name) != value:
                result.error(
                    f"project score {project_id}: {name}"
                    f" {getattr(project_record, name)} does not match artifacts ({value})"
                )
        model_available = project_record.model_status == "available"
        if not eligible:
            expected_coverage = None
        elif not model_available:
            expected_coverage = 0.0
        else:
            expected_coverage = round(len(analyzed) / len(eligible), 3)
        if project_record.visual_coverage != expected_coverage:
            result.error(f"project score {project_id}: coverage does not recompute")
        expected_confidence, expected_components = compute_assessment_confidence(
            model_available=model_available,
            classifications=[c for c in classifications if c.project_id == project_id],
            contexts=[c for c in contexts if c.project_id == project_id],
        )
        if abs(project_record.assessment_confidence - expected_confidence) > 0.001:
            result.error(
                f"project score {project_id}: assessment confidence does not"
                f" recompute (expected {expected_confidence})"
            )
        if project_record.confidence_components != expected_components:
            result.error(
                f"project score {project_id}: confidence components do not match artifacts"
            )
        blended = sum(
            ASSESSMENT_CONFIDENCE_WEIGHTS[name] * value
            for name, value in project_record.confidence_components.items()
            if name in ASSESSMENT_CONFIDENCE_WEIGHTS
        )
        bounded = min(ASSESSMENT_CONFIDENCE_MAX, max(ASSESSMENT_CONFIDENCE_MIN, blended))
        if abs(round(bounded, 2) - project_record.assessment_confidence) > 0.001:
            result.error(
                f"project score {project_id}: confidence does not recompute from its own components"
            )
        if project_record.meta_integration_status != META_INTEGRATION_STATUS:
            result.error(
                f"project score {project_id}: meta_integration_status must be"
                f" {META_INTEGRATION_STATUS}"
            )


# --- ordering -----------------------------------------------------------------


def _check_ordering(
    result: P5ValidationResult,
    assets: list[P5AssetRecord],
    contexts: list[P5AssetContext],
    classifications: list[P5Classification],
    clusters: list[P5DuplicateCluster],
    findings: list[P5FindingRecord],
) -> None:
    severity_sort = {"high": 0, "medium": 1, "low": 2, "info": 3}
    if [a.asset_id for a in assets] != [
        a.asset_id
        for a in sorted(assets, key=lambda a: (a.project_id, a.document_id, a.image_id, a.asset_id))
    ]:
        result.error("assets.jsonl is not deterministically ordered")
    if [c.context_id for c in contexts] != [
        c.context_id for c in sorted(contexts, key=lambda c: (c.project_id, c.asset_id))
    ]:
        result.error("asset_contexts.jsonl is not deterministically ordered")
    if [c.classification_id for c in classifications] != [
        c.classification_id
        for c in sorted(classifications, key=lambda c: (c.project_id, c.asset_id))
    ]:
        result.error("classifications.jsonl is not deterministically ordered")
    if [c.cluster_id for c in clusters] != sorted(c.cluster_id for c in clusters):
        result.error("duplicate_clusters.jsonl is not deterministically ordered")
    expected = [
        f.finding_id
        for f in sorted(
            findings,
            key=lambda f: (
                f.project_id,
                f.document_id or "~",
                severity_sort.get(f.severity, 9),
                f.finding_type,
                f.finding_id,
            ),
        )
    ]
    if [f.finding_id for f in findings] != expected:
        result.error("findings.jsonl is not deterministically ordered")


# --- metrics / report ---------------------------------------------------------


def _check_metrics_and_report(
    result: P5ValidationResult,
    output_dir: Path,
    dataset_dir: Path,
    assets: list[P5AssetRecord],
    clusters: list[P5DuplicateCluster],
    findings: list[P5FindingRecord],
    classifications: list[P5Classification],
    project_scores: list[P5ProjectScoreRecord],
) -> None:
    try:
        metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.error(f"metrics.json unreadable: {exc}")
        return
    checks = {
        "assets_total": len(assets),
        "duplicate_clusters_total": len(clusters),
        "findings_total": len(findings),
        "analyzed_representatives": sum(
            1 for a in assets if a.triage_status == "analyzed_representative"
        ),
    }
    for key, value in checks.items():
        if metrics.get(key) != value:
            result.error(f"metrics.{key} does not match artifacts (expected {value})")
    by_class: dict[str, int] = {}
    for classification in classifications:
        by_class[classification.predicted_class] = (
            by_class.get(classification.predicted_class, 0) + 1
        )
    if metrics.get("classifications_by_class") != dict(sorted(by_class.items())):
        result.error("metrics.classifications_by_class does not match classifications.jsonl")
    for score in project_scores:
        recorded = (metrics.get("per_project") or {}).get(score.project_id) or {}
        if recorded.get("review_priority") != score.visual_evidence_review_priority_score:
            result.error(f"metrics.per_project[{score.project_id}] does not match scores")

    build_report = dataset_dir / "build_report.json"
    if build_report.is_file():
        try:
            expected_fingerprint = json.loads(build_report.read_text(encoding="utf-8")).get(
                "input_fingerprint"
            )
        except (OSError, json.JSONDecodeError):
            expected_fingerprint = None
        if expected_fingerprint and metrics.get("input_fingerprint") != expected_fingerprint:
            result.error(
                "metrics.input_fingerprint does not match the dataset build report"
                " (input identity tampering)"
            )

    report = (output_dir / "report.md").read_text(encoding="utf-8")
    if f"- Всего: {len(findings)}" not in report:
        result.error("report.md findings count does not match findings.jsonl")
    if f"- Визуальных активов: {len(assets)}" not in report:
        result.error("report.md asset count does not match assets.jsonl")


def _check_model_metadata(
    result: P5ValidationResult,
    output_dir: Path,
    classifications: list[P5Classification],
) -> None:
    try:
        metadata = json.loads((output_dir / "model_metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.error(f"model_metadata.json unreadable: {exc}")
        return
    if metadata.get("prompts_sha256") != prompts_fingerprint():
        result.error("model_metadata.prompts_sha256 does not match the configured prompt set")
    status = metadata.get("model_status")
    if status not in {"available", "unavailable"}:
        result.error("model_metadata.model_status must be available|unavailable")
    if not metadata.get("model_name"):
        result.error("model_metadata.model_name is missing")
    classification_status = {c.model_status for c in classifications}
    if status == "unavailable" and "available" in classification_status:
        result.error("classifications claim model availability but model_metadata says unavailable")


# --- review template ----------------------------------------------------------


def _check_review_template(
    result: P5ValidationResult,
    output_dir: Path,
    assets: list[P5AssetRecord],
    annotations_root: Path | None,
    dataset_dir: Path,
) -> None:
    template_root = annotations_root or dataset_dir.parent.parent / "annotations"
    template_path = template_root / "p5_review_template.jsonl"
    if not template_path.exists():
        return
    asset_ids = {a.asset_id for a in assets}
    for line_number, line in enumerate(
        template_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("asset_id")) not in asset_ids:
            result.error(
                f"review template row {line_number} references unknown asset {row.get('asset_id')}"
            )


# --- safety -------------------------------------------------------------------

_ABSOLUTE_PATH_RE = re.compile(r"(/Users/|\\Users\\|/home/)")


def _check_no_absolute_paths(result: P5ValidationResult, output_dir: Path) -> None:
    for name in _OUTPUT_FILES:
        text = (output_dir / name).read_text(encoding="utf-8")
        if _ABSOLUTE_PATH_RE.search(text):
            result.error(f"{name}: contains an absolute local path")


def _check_dataset_untouched(result: P5ValidationResult, dataset_dir: Path) -> None:
    checksums_path = dataset_dir / "checksums.jsonl"
    if not checksums_path.is_file():
        result.warnings.append("checksums.jsonl missing: dataset integrity not verified")
        return
    recorded: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            recorded[str(entry["file"])] = str(entry["sha256"])
    for name in _INPUT_FILES:
        path = dataset_dir / name
        if name not in recorded:
            result.warnings.append(f"checksums.jsonl has no entry for {name}")
            continue
        if not path.is_file():
            result.error(f"dataset file {name} is missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != recorded[name]:
            result.error(f"dataset file {name} changed after the P5 run (checksum mismatch)")


def _check_output_location(result: P5ValidationResult, dataset_dir: Path, output_dir: Path) -> None:
    try:
        if output_dir.resolve().is_relative_to(dataset_dir.resolve()):
            result.error("P5 output directory must not live inside the curated dataset")
    except (OSError, ValueError):
        pass
