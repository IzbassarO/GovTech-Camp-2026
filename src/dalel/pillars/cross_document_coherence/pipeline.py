"""P4 run orchestration over the curated dataset (read-only input).

Deterministic end to end: the same dataset and configuration produce
byte-identical artifacts — P4 output files contain NO timestamps and NO
absolute paths. The review-template merge preserves human decisions exactly
like P1/P3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dalel.pillars.cross_document_coherence.checks import run_checks
from dalel.pillars.cross_document_coherence.config import config_snapshot
from dalel.pillars.cross_document_coherence.entity_resolution import resolve_entities
from dalel.pillars.cross_document_coherence.extractor import extract_claims
from dalel.pillars.cross_document_coherence.graph import build_graph
from dalel.pillars.cross_document_coherence.input_contract import validate_input_records
from dalel.pillars.cross_document_coherence.reports import render_p4_report
from dalel.pillars.cross_document_coherence.schemas import (
    CONFLICT_FINDING_TYPES,
    Edge,
    Entity,
    EntityClaim,
    P4DocumentScoreRecord,
    P4FindingRecord,
    P4ProjectScoreRecord,
    ResolutionDecision,
    SuppressedComparison,
)
from dalel.pillars.cross_document_coherence.scoring import score_document, score_project


class P4RunError(Exception):
    """Blocking P4 execution failure (missing/invalid curated input)."""


@dataclass
class P4Options:
    dataset_dir: Path
    output_dir: Path
    annotations_root: Path
    project_id: str | None = None
    document_id: str | None = None
    write_review_template: bool = True


@dataclass
class P4RunResult:
    claims: list[EntityClaim] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    resolution_decisions: list[ResolutionDecision] = field(default_factory=list)
    suppressed: list[SuppressedComparison] = field(default_factory=list)
    findings: list[P4FindingRecord] = field(default_factory=list)
    document_scores: list[P4DocumentScoreRecord] = field(default_factory=list)
    project_scores: list[P4ProjectScoreRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    review_template_path: Path | None = None
    review_template_created: bool = False
    review_template_preserved_decisions: int = 0
    review_template_stale_rows: int = 0


_SEVERITY_SORT = {"high": 0, "medium": 1, "low": 2, "info": 3}

_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "projects.jsonl": ("project_id",),
    "documents.jsonl": ("project_id", "document_id", "document_type"),
    "sections.jsonl": ("section_id", "text", "provenance"),
    "tables.jsonl": ("table_id", "cells", "provenance"),
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise P4RunError(
            f"curated file is missing: {path};"
            " re-run `dalel curate` or point --dataset at a built dataset"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise P4RunError(
            f"{path.name}: cannot read file ({exc});"
            " check dataset integrity with `dalel validate-curated`"
        ) from exc
    required = _REQUIRED_KEYS.get(path.name, ())
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise P4RunError(
                f"{path.name}: line {line_number}: invalid JSON ({exc.msg});"
                " regenerate the curated dataset with `dalel curate --force`"
            ) from exc
        if not isinstance(record, dict):
            raise P4RunError(
                f"{path.name}: line {line_number}: record is not a JSON object;"
                " regenerate the curated dataset"
            )
        missing = [key for key in required if key not in record]
        if missing:
            raise P4RunError(
                f"{path.name}: line {line_number}: missing required"
                f" field(s) {', '.join(missing)}; the file does not match the"
                " Curated Dataset v1 contract — run `dalel validate-curated`"
            )
        if "provenance" in required and "document_id" not in (record.get("provenance") or {}):
            raise P4RunError(
                f"{path.name}: line {line_number}: provenance.document_id is"
                " missing; the file does not match the Curated Dataset v1"
                " contract — run `dalel validate-curated`"
            )
        records.append(record)
    validate_input_records(path.name, records, P4RunError)
    return records


def run_p4(options: P4Options) -> P4RunResult:
    projects = _read_jsonl(options.dataset_dir / "projects.jsonl")
    documents = _read_jsonl(options.dataset_dir / "documents.jsonl")
    sections = _read_jsonl(options.dataset_dir / "sections.jsonl")
    tables = _read_jsonl(options.dataset_dir / "tables.jsonl")

    if options.project_id is not None:
        known = {str(p["project_id"]) for p in projects}
        if options.project_id not in known:
            raise P4RunError(f"--project-id {options.project_id!r} not in curated dataset")
    if options.document_id is not None:
        known_docs = {str(d["document_id"]) for d in documents}
        if options.document_id not in known_docs:
            raise P4RunError(f"--document-id {options.document_id!r} not in curated dataset")

    selected_projects = [
        p
        for p in projects
        if options.project_id is None or str(p["project_id"]) == options.project_id
    ]
    selected_project_ids = {str(p["project_id"]) for p in selected_projects}
    selected_documents = [
        d
        for d in documents
        if str(d["project_id"]) in selected_project_ids
        and (options.document_id is None or str(d["document_id"]) == options.document_id)
    ]
    selected_doc_ids = {str(d["document_id"]) for d in selected_documents}
    projects_by_id = {str(p["project_id"]): p for p in selected_projects}

    def _by_document(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            document_id = str(record["provenance"]["document_id"])
            if document_id in selected_doc_ids:
                grouped.setdefault(document_id, []).append(record)
        return grouped

    extraction = extract_claims(
        selected_documents,
        _by_document(sections),
        _by_document(tables),
        projects_by_id,
    )
    resolution = resolve_entities(extraction.claims, projects_by_id, selected_documents)
    graph = build_graph(resolution.entities)
    checks = run_checks(
        extraction.claims, resolution.operator_by_project, projects_by_id, selected_documents
    )

    findings = sorted(
        checks.findings,
        key=lambda f: (
            f.project_id,
            f.document_id or "~",
            _SEVERITY_SORT.get(f.severity, 9),
            f.finding_type,
            f.finding_id,
        ),
    )

    result = P4RunResult(
        claims=extraction.claims,
        entities=resolution.entities,
        edges=graph.edges,
        resolution_decisions=resolution.decisions,
        suppressed=checks.suppressed,
        findings=findings,
    )

    _score(result, selected_projects, selected_documents)
    result.metrics = _build_metrics(result, extraction, selected_projects, selected_documents)
    _write_outputs(options, result)
    return result


# --- scoring -----------------------------------------------------------------


def _project_graph_stats(
    project_id: str,
    entities: list[Entity],
    edges: list[Edge],
    decisions: list[ResolutionDecision],
    suppressed: list[SuppressedComparison],
) -> dict[str, int]:
    project_entities = [e for e in entities if e.project_id == project_id]
    project_edges = [e for e in edges if e.project_id == project_id]
    linked_docs: set[str] = set()
    for entity in project_entities:
        if (
            entity.entity_type not in ("project", "document")
            and len(entity.source_document_ids) >= 2
        ):
            linked_docs.update(entity.source_document_ids)
    unresolved_ids: set[str] = set()
    for decision in decisions:
        if decision.project_id == project_id and decision.decision == "unresolved":
            unresolved_ids.update(decision.entity_ids)
    return {
        "entity_count": len(project_entities),
        "edge_count": len(project_edges),
        "linked_document_count": len(linked_docs),
        "unresolved_entity_count": len(unresolved_ids),
        "suppressed_comparison_count": sum(1 for s in suppressed if s.project_id == project_id),
    }


def _score(
    result: P4RunResult,
    projects: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> None:
    findings_by_document: dict[str, list[P4FindingRecord]] = {}
    package_by_project: dict[str, list[P4FindingRecord]] = {}
    for finding in result.findings:
        if finding.document_id is not None:
            findings_by_document.setdefault(finding.document_id, []).append(finding)
        else:
            package_by_project.setdefault(finding.project_id, []).append(finding)

    for project in sorted(projects, key=lambda p: str(p["project_id"])):
        project_id = str(project["project_id"])
        project_documents = sorted(
            (d for d in documents if str(d["project_id"]) == project_id),
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
        stats = _project_graph_stats(
            project_id,
            result.entities,
            result.edges,
            result.resolution_decisions,
            result.suppressed,
        )
        result.project_scores.append(
            score_project(
                project_id,
                document_scores,
                package_by_project.get(project_id, []),
                **stats,
            )
        )


# --- metrics -----------------------------------------------------------------


def _build_metrics(
    result: P4RunResult,
    extraction: Any,
    projects: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    from dalel.pillars.cross_document_coherence import P4_VERSION
    from dalel.pillars.cross_document_coherence.config import P4_SCORING_CONFIG_VERSION

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_document: dict[str, int] = {}
    for finding in result.findings:
        by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        key = finding.document_id or f"__package__/{finding.project_id}"
        by_document[key] = by_document.get(key, 0) + 1

    entities_by_type: dict[str, int] = {}
    for entity in result.entities:
        entities_by_type[entity.entity_type] = entities_by_type.get(entity.entity_type, 0) + 1
    edges_by_relation: dict[str, int] = {}
    for edge in result.edges:
        edges_by_relation[edge.relation] = edges_by_relation.get(edge.relation, 0) + 1
    claims_by_attribute: dict[str, int] = {}
    for claim in result.claims:
        claims_by_attribute[claim.attribute] = claims_by_attribute.get(claim.attribute, 0) + 1
    resolution_by_decision: dict[str, int] = {}
    for decision in result.resolution_decisions:
        resolution_by_decision[decision.decision] = (
            resolution_by_decision.get(decision.decision, 0) + 1
        )
    suppressed_by_reason: dict[str, int] = {}
    for suppression in result.suppressed:
        suppressed_by_reason[suppression.reason] = (
            suppressed_by_reason.get(suppression.reason, 0) + 1
        )

    proven_conflicts = sum(1 for f in result.findings if f.finding_type in CONFLICT_FINDING_TYPES)
    scores = [s.cross_document_coherence_priority_score for s in result.document_scores]
    return {
        "p4_version": P4_VERSION,
        "scoring_config_version": P4_SCORING_CONFIG_VERSION,
        "documents_analyzed": len(documents),
        "projects_analyzed": len(projects),
        "sections_scanned": extraction.sections_scanned,
        "claims_total": len(result.claims),
        "claims_by_attribute": dict(sorted(claims_by_attribute.items())),
        "organization_mentions": extraction.org_mentions,
        "entities_total": len(result.entities),
        "entities_by_type": dict(sorted(entities_by_type.items())),
        "edges_total": len(result.edges),
        "edges_by_relation": dict(sorted(edges_by_relation.items())),
        "resolution_decisions_total": len(result.resolution_decisions),
        "resolution_by_decision": dict(sorted(resolution_by_decision.items())),
        "suppressed_comparisons_total": len(result.suppressed),
        "suppressed_comparisons_by_reason": dict(sorted(suppressed_by_reason.items())),
        "findings_total": len(result.findings),
        "findings_by_type": dict(sorted(by_type.items())),
        "findings_by_severity": dict(sorted(by_severity.items())),
        "findings_by_document": dict(sorted(by_document.items())),
        "proven_cross_document_conflicts": proven_conflicts,
        "linked_documents_total": sum(s.linked_document_count for s in result.project_scores),
        "unresolved_entities_total": sum(s.unresolved_entity_count for s in result.project_scores),
        "score_distribution": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "mean": round(sum(scores) / len(scores), 1) if scores else None,
            "documents": {
                s.document_id: s.cross_document_coherence_priority_score
                for s in result.document_scores
            },
        },
        "evaluation_note": (
            "4 проекта: ML accuracy не заявляется; метрики описывают покрытие"
            " графа и распределения, а не качество классификации. Отсутствие"
            " доказанных противоречий не подтверждает корректность документов."
        ),
    }


# --- outputs -----------------------------------------------------------------

_TEMPLATE_HUMAN_FIELDS = ("expert_decision", "corrected_severity", "expert_comment", "reviewer_id")


def _write_outputs(options: P4Options, result: P4RunResult) -> None:
    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    def _write_jsonl(name: str, records: list[dict[str, Any]]) -> None:
        with (output_dir / name).open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")

    _write_jsonl("claims.jsonl", [c.model_dump(mode="json") for c in result.claims])
    _write_jsonl("entities.jsonl", [e.model_dump(mode="json") for e in result.entities])
    _write_jsonl("edges.jsonl", [e.model_dump(mode="json") for e in result.edges])
    _write_jsonl(
        "resolution_decisions.jsonl",
        [d.model_dump(mode="json") for d in result.resolution_decisions],
    )
    _write_jsonl(
        "suppressed_comparisons.jsonl", [s.model_dump(mode="json") for s in result.suppressed]
    )
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
    (output_dir / "report.md").write_text(render_p4_report(result), encoding="utf-8")

    if options.write_review_template:
        _merge_review_template(options, result, output_dir)


def _merge_review_template(options: P4Options, result: P4RunResult, output_dir: Path) -> None:
    """Create/update the expert review template WITHOUT losing human decisions
    (same contract as P1/P3)."""
    options.annotations_root.mkdir(parents=True, exist_ok=True)
    template_path = options.annotations_root / "p4_review_template.jsonl"
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

    def _has_human_data(row: dict[str, Any]) -> bool:
        return any(row.get(field_name) is not None for field_name in _TEMPLATE_HUMAN_FIELDS)

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
            if _has_human_data(old):
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
