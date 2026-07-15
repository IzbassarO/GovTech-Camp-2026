"""P2 run orchestration over the curated dataset (read-only input).

Deterministic end to end in offline mode: the same dataset, corpus and
configuration produce byte-identical artifacts (no timestamps). With an
external LLM provider the content-addressed cache makes repeated runs
deterministic once responses are cached. The review-template merge
preserves human decisions exactly like P1/P3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dalel.curation.schemas import (
    CuratedDocument,
    CuratedProject,
    CuratedSectionRecord,
)
from dalel.pillars.regulatory_compliance.assessment import assess_pair
from dalel.pillars.regulatory_compliance.config import (
    DEFAULT_TOP_K,
    DEMO_CORPUS_WARNING,
    config_snapshot,
)
from dalel.pillars.regulatory_compliance.corpus import (
    DEMO_CORPUS_RESOURCE,
    CorpusError,
    corpus_is_demo_only,
    corpus_summary,
    load_corpus,
)
from dalel.pillars.regulatory_compliance.evidence import build_evidence_stores
from dalel.pillars.regulatory_compliance.providers import (
    LLMProvider,
    ProviderError,
    ResponseCache,
    provider_from_config,
)
from dalel.pillars.regulatory_compliance.reports import render_p2_report
from dalel.pillars.regulatory_compliance.retrieval import (
    build_index,
    build_queries,
    retrieve_for_project,
)
from dalel.pillars.regulatory_compliance.schemas import (
    P2Assessment,
    P2DocumentScoreRecord,
    P2FindingRecord,
    P2ProjectScoreRecord,
    ProjectEvidence,
    RegulatoryRequirement,
    RetrievalRecord,
)
from dalel.pillars.regulatory_compliance.scoring import (
    build_findings,
    score_document,
    score_project,
)


class P2RunError(Exception):
    """Blocking P2 execution failure (invalid dataset, corpus or config)."""


@dataclass
class P2Options:
    dataset_dir: Path
    output_dir: Path
    annotations_root: Path
    regulations: Path | None = None  # None => packaged demo corpus
    top_k: int = DEFAULT_TOP_K
    provider_name: str | None = None  # None/"none" => deterministic mode
    use_cache: bool = True
    project_id: str | None = None
    write_review_template: bool = True


@dataclass
class P2RunResult:
    requirements: list[RegulatoryRequirement] = field(default_factory=list)
    evidence: list[ProjectEvidence] = field(default_factory=list)
    retrievals: list[RetrievalRecord] = field(default_factory=list)
    assessments: list[P2Assessment] = field(default_factory=list)
    findings: list[P2FindingRecord] = field(default_factory=list)
    document_scores: list[P2DocumentScoreRecord] = field(default_factory=list)
    project_scores: list[P2ProjectScoreRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    corpus_demo_only: bool = True
    review_template_path: Path | None = None
    review_template_created: bool = False
    review_template_preserved_decisions: int = 0
    review_template_stale_rows: int = 0


# Expected user-input problems become a concise P2RunError (never a
# traceback); every record is validated against the accepted curated
# models before use.
_RECORD_MODELS: dict[str, type[BaseModel]] = {
    "projects.jsonl": CuratedProject,
    "documents.jsonl": CuratedDocument,
    "sections.jsonl": CuratedSectionRecord,
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise P2RunError(
            f"curated file is missing: {path};"
            " re-run `dalel curate` or point --dataset at a built dataset"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise P2RunError(f"{path.name}: cannot read file ({exc})") from exc
    model = _RECORD_MODELS.get(path.name)
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise P2RunError(
                f"{path.name}: line {line_number}: invalid JSON ({exc.msg});"
                " regenerate the curated dataset with `dalel curate --force`"
            ) from exc
        if not isinstance(record, dict):
            raise P2RunError(f"{path.name}: line {line_number}: record is not a JSON object")
        if model is not None:
            try:
                model.model_validate(record)
            except ValidationError as exc:
                first = exc.errors()[0]
                location = ".".join(str(p) for p in first.get("loc", ())) or "(record)"
                raise P2RunError(
                    f"{path.name}: line {line_number}: field '{location}':"
                    f" {first.get('msg', 'invalid value')} — run"
                    " `dalel validate-curated`"
                ) from exc
        records.append(record)
    return records


def run_p2(options: P2Options) -> P2RunResult:
    regulations_path = options.regulations or DEMO_CORPUS_RESOURCE
    try:
        requirements = load_corpus(regulations_path)
    except CorpusError as exc:
        raise P2RunError(str(exc)) from exc

    try:
        provider: LLMProvider | None = provider_from_config(options.provider_name)
    except ProviderError as exc:
        raise P2RunError(str(exc)) from exc

    projects = _read_jsonl(options.dataset_dir / "projects.jsonl")
    documents = _read_jsonl(options.dataset_dir / "documents.jsonl")
    sections = _read_jsonl(options.dataset_dir / "sections.jsonl")

    if options.project_id is not None:
        known = {str(p["project_id"]) for p in projects}
        if options.project_id not in known:
            raise P2RunError(f"--project-id {options.project_id!r} not in curated dataset")
        projects = [p for p in projects if str(p["project_id"]) == options.project_id]

    selected_project_ids = {str(p["project_id"]) for p in projects}
    selected_documents = [d for d in documents if str(d["project_id"]) in selected_project_ids]
    selected_document_ids = {str(d["document_id"]) for d in selected_documents}
    sections_by_document: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        document_id = str(section["provenance"]["document_id"])
        if document_id in selected_document_ids:
            sections_by_document.setdefault(document_id, []).append(section)

    stores = build_evidence_stores(projects, selected_documents, sections_by_document)
    index = build_index(requirements)
    requirements_by_id = {r.requirement_id: r for r in requirements}

    cache_path = (options.output_dir / "llm_cache.jsonl") if options.use_cache else None
    cache = ResponseCache.load(cache_path if provider is not None else None)

    result = P2RunResult(requirements=list(requirements))
    result.corpus_demo_only = corpus_is_demo_only(requirements)

    queries_total = 0
    for project_id in sorted(stores):
        store = stores[project_id]
        all_retrievals, best_per_requirement = retrieve_for_project(index, store, options.top_k)
        queries_total += len(build_queries(store))
        result.retrievals.extend(
            sorted(all_retrievals, key=lambda r: (r.query_id, r.rank, r.requirement_id))
        )
        for requirement_id in sorted(best_per_requirement):
            retrieval = best_per_requirement[requirement_id]
            requirement = requirements_by_id[requirement_id]
            result.assessments.append(assess_pair(requirement, store, retrieval, provider, cache))
        # Snippets created during assessment become part of the store.
        result.evidence.extend(store.ordered())

    if provider is not None:
        cache.save()

    result.assessments.sort(key=lambda a: (a.project_id, a.requirement_id))
    result.findings = build_findings(
        result.assessments,
        requirements_by_id,
        result.corpus_demo_only,
        sorted(stores),
    )

    findings_by_document: dict[str, list[P2FindingRecord]] = {}
    package_by_project: dict[str, list[P2FindingRecord]] = {}
    for finding in result.findings:
        if finding.document_id is not None:
            findings_by_document.setdefault(finding.document_id, []).append(finding)
        else:
            package_by_project.setdefault(finding.project_id, []).append(finding)

    for project in sorted(projects, key=lambda p: str(p["project_id"])):
        project_id = str(project["project_id"])
        project_documents = sorted(
            (d for d in selected_documents if str(d["project_id"]) == project_id),
            key=lambda d: str(d["document_id"]),
        )
        if not project_documents:
            continue
        document_scores = [
            score_document(
                project_id,
                str(document["document_id"]),
                str(document["document_type"]),
                findings_by_document.get(str(document["document_id"]), []),
            )
            for document in project_documents
        ]
        result.document_scores.extend(document_scores)
        result.project_scores.append(
            score_project(project_id, document_scores, package_by_project.get(project_id, []))
        )

    result.metrics = _build_metrics(
        result, projects, selected_documents, queries_total, provider, options.top_k
    )
    _write_outputs(options, result)
    return result


def _build_metrics(
    result: P2RunResult,
    projects: list[dict[str, Any]],
    selected_documents: list[dict[str, Any]],
    queries_total: int,
    provider: LLMProvider | None,
    top_k: int,
) -> dict[str, Any]:
    from dalel.pillars.regulatory_compliance import P2_VERSION
    from dalel.pillars.regulatory_compliance.config import P2_SCORING_CONFIG_VERSION

    by_label: dict[str, int] = {}
    by_engine: dict[str, int] = {}
    by_applicability: dict[str, int] = {}
    for assessment in result.assessments:
        by_label[assessment.label] = by_label.get(assessment.label, 0) + 1
        by_engine[assessment.inference_engine] = by_engine.get(assessment.inference_engine, 0) + 1
        by_applicability[assessment.applicability] = (
            by_applicability.get(assessment.applicability, 0) + 1
        )
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for finding in result.findings:
        by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1

    summary = corpus_summary(result.requirements)
    scores = [s.regulatory_compliance_priority_score for s in result.document_scores]
    return {
        "p2_version": P2_VERSION,
        "scoring_config_version": P2_SCORING_CONFIG_VERSION,
        "top_k": top_k,
        "projects_analyzed": len(projects),
        "documents_analyzed": len(selected_documents),
        "requirements_total": summary["requirements_total"],
        "requirements_authoritative": summary["authoritative"],
        "requirements_demo_only": summary["demo_only"],
        "requirements_by_obligation_type": summary["by_obligation_type"],
        "corpus_demo_only": result.corpus_demo_only,
        "corpus_warning": DEMO_CORPUS_WARNING if result.corpus_demo_only else None,
        "queries_total": queries_total,
        "retrievals_total": len(result.retrievals),
        "evidence_total": len(result.evidence),
        "assessments_total": len(result.assessments),
        "assessments_by_label": dict(sorted(by_label.items())),
        "assessments_by_engine": dict(sorted(by_engine.items())),
        "assessments_by_applicability": dict(sorted(by_applicability.items())),
        "llm_provider": provider.name if provider is not None else None,
        "findings_total": len(result.findings),
        "findings_by_type": dict(sorted(by_type.items())),
        "findings_by_severity": dict(sorted(by_severity.items())),
        "score_distribution": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "documents": {
                s.document_id: s.regulatory_compliance_priority_score
                for s in result.document_scores
            },
        },
        "evaluation_note": (
            "Экспертная поддержка: метрики описывают покрытие и распределения,"
            " не качество юридической классификации."
        ),
    }


_TEMPLATE_HUMAN_FIELDS = ("expert_decision", "corrected_severity", "expert_comment", "reviewer_id")


def _write_outputs(options: P2Options, result: P2RunResult) -> None:
    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    def _write_jsonl(name: str, records: list[dict[str, Any]]) -> None:
        with (output_dir / name).open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")

    _write_jsonl(
        "requirements_snapshot.jsonl",
        [r.model_dump(mode="json") for r in result.requirements],
    )
    _write_jsonl("project_evidence.jsonl", [e.model_dump(mode="json") for e in result.evidence])
    _write_jsonl("retrievals.jsonl", [r.model_dump(mode="json") for r in result.retrievals])
    _write_jsonl("assessments.jsonl", [a.model_dump(mode="json") for a in result.assessments])
    _write_jsonl("findings.jsonl", [f.model_dump(mode="json") for f in result.findings])
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
    (output_dir / "report.md").write_text(render_p2_report(result), encoding="utf-8")

    if options.write_review_template:
        _merge_review_template(options, result, output_dir)


def _merge_review_template(options: P2Options, result: P2RunResult, output_dir: Path) -> None:
    """Create/update the expert review template WITHOUT losing human
    decisions (same contract as P1/P3)."""
    options.annotations_root.mkdir(parents=True, exist_ok=True)
    template_path = options.annotations_root / "p2_review_template.jsonl"
    existing: dict[str, dict[str, Any]] = {}
    if template_path.exists():
        for line in template_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing[str(row.get("finding_id"))] = row

    def _empty_row(finding_id: str) -> dict[str, Any]:
        return {
            "finding_id": finding_id,
            "expert_decision": None,
            "corrected_severity": None,
            "expert_comment": None,
            "reviewed_at": None,
            "reviewer_id": None,
        }

    current_ids = [finding.finding_id for finding in result.findings]
    current_set = set(current_ids)
    rows: list[dict[str, Any]] = []
    preserved = 0
    for finding_id in current_ids:
        old = existing.get(finding_id)
        if old is not None:
            merged = _empty_row(finding_id)
            for key in (*_TEMPLATE_HUMAN_FIELDS, "reviewed_at"):
                if old.get(key) is not None:
                    merged[key] = old[key]
            if any(old.get(f) is not None for f in _TEMPLATE_HUMAN_FIELDS):
                preserved += 1
            rows.append(merged)
        else:
            rows.append(_empty_row(finding_id))

    stale = [row for finding_id, row in existing.items() if finding_id not in current_set]

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
