"""P4 output validation: schemas, IDs, references, grounding, recomputation.

Independent of the pipeline: it re-reads the artifacts and the curated
containers and re-derives every ID, reference, score, count and grounding from
first principles, so any tampering (a changed ID, a rewritten evidence quote, a
moved edge endpoint, an inflated score, an unsupported high severity) is
detected. It also verifies that running P4 never modified Dataset v1.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dalel.pillars.cross_document_coherence.checks import run_checks
from dalel.pillars.cross_document_coherence.config import CONFIDENCE_MAX, CONFIDENCE_MIN
from dalel.pillars.cross_document_coherence.entity_resolution import resolve_entities
from dalel.pillars.cross_document_coherence.extractor import section_evidence_text
from dalel.pillars.cross_document_coherence.graph import build_graph
from dalel.pillars.cross_document_coherence.normalization import normalize_text
from dalel.pillars.cross_document_coherence.schemas import (
    CONFLICT_FINDING_TYPES,
    DIAGNOSTIC_FINDING_TYPES,
    P4_FINDING_TYPES,
    SEVERITIES,
    Edge,
    Entity,
    EntityClaim,
    P4DocumentScoreRecord,
    P4FindingRecord,
    P4ProjectScoreRecord,
    ResolutionDecision,
    SuppressedComparison,
    deterministic_id,
)
from dalel.pillars.cross_document_coherence.scoring import points_for

_OUTPUT_FILES = (
    "claims.jsonl",
    "entities.jsonl",
    "edges.jsonl",
    "resolution_decisions.jsonl",
    "suppressed_comparisons.jsonl",
    "findings.jsonl",
    "document_scores.jsonl",
    "project_scores.jsonl",
    "metrics.json",
    "config_snapshot.json",
    "report.md",
)

_INPUT_FILES = ("projects.jsonl", "documents.jsonl", "sections.jsonl", "tables.jsonl")


@dataclass
class P4ValidationResult:
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


def validate_p4_outputs(
    dataset_dir: Path,
    output_dir: Path,
    annotations_root: Path | None = None,
) -> P4ValidationResult:
    result = P4ValidationResult()

    for name in _OUTPUT_FILES:
        if not (output_dir / name).is_file():
            result.error(f"missing output file: {name}")
    if not result.ok:
        return result

    try:
        claims = _load(output_dir / "claims.jsonl", EntityClaim, result, "claims")
        entities = _load(output_dir / "entities.jsonl", Entity, result, "entities")
        edges = _load(output_dir / "edges.jsonl", Edge, result, "edges")
        decisions = _load(
            output_dir / "resolution_decisions.jsonl", ResolutionDecision, result, "resolution"
        )
        suppressed = _load(
            output_dir / "suppressed_comparisons.jsonl", SuppressedComparison, result, "suppressed"
        )
        findings = _load(output_dir / "findings.jsonl", P4FindingRecord, result, "findings")
        document_scores = _load(
            output_dir / "document_scores.jsonl", P4DocumentScoreRecord, result, "document_scores"
        )
        project_scores = _load(
            output_dir / "project_scores.jsonl", P4ProjectScoreRecord, result, "project_scores"
        )
    except (ValueError, json.JSONDecodeError) as exc:
        result.error(f"output parse failure: {exc}")
        return result
    if not result.ok:
        return result

    result.counts = {
        "claims": len(claims),
        "entities": len(entities),
        "edges": len(edges),
        "resolution_decisions": len(decisions),
        "suppressed_comparisons": len(suppressed),
        "findings": len(findings),
        "document_scores": len(document_scores),
        "project_scores": len(project_scores),
    }

    _check_unique_ids(result, claims, entities, edges, decisions, suppressed, findings)
    _check_id_recomputation(result, claims, edges, decisions, suppressed, findings)
    _check_references(result, claims, entities, edges, decisions, findings)
    _check_grounding(result, dataset_dir, claims)
    _check_replay(result, dataset_dir, claims, entities, edges, decisions, findings, suppressed)
    _check_finding_rules(result, findings)
    _check_scores(result, findings, document_scores, project_scores)
    _check_project_stats(result, entities, edges, decisions, suppressed, project_scores)
    _check_ordering(result, findings, entities, edges)
    _check_metrics_and_report(result, output_dir, claims, entities, edges, suppressed, findings)
    _check_review_template(result, dataset_dir, findings, annotations_root)
    _check_no_absolute_paths(result, output_dir)
    _check_dataset_untouched(result, dataset_dir)
    _check_output_location(result, dataset_dir, output_dir)

    return result


def _load(path: Path, model: Any, result: P4ValidationResult, name: str) -> list[Any]:
    records: list[Any] = []
    for index, raw in enumerate(_read_jsonl(path), start=1):
        try:
            records.append(model.model_validate(raw))
        except ValidationError as exc:
            result.error(f"{name}.jsonl:{index}: schema violation: {exc.errors()[:2]}")
    return records


# --- ids ---------------------------------------------------------------------


def _check_unique_ids(
    result: P4ValidationResult,
    claims: list[EntityClaim],
    entities: list[Entity],
    edges: list[Edge],
    decisions: list[ResolutionDecision],
    suppressed: list[SuppressedComparison],
    findings: list[P4FindingRecord],
) -> None:
    for label, ids, prefix in (
        ("claim", [c.claim_id for c in claims], "P4C__"),
        ("entity", [e.entity_id for e in entities], "P4E__"),
        ("edge", [e.edge_id for e in edges], "P4G__"),
        ("decision", [d.decision_id for d in decisions], "P4R__"),
        ("suppression", [s.suppression_id for s in suppressed], "P4S__"),
        ("finding", [f.finding_id for f in findings], "P4__"),
    ):
        if len(set(ids)) != len(ids):
            result.error(f"duplicate {label} id values")
        for identifier in ids:
            if not identifier.startswith(prefix):
                result.error(f"{label} id without {prefix} prefix: {identifier}")


def _check_id_recomputation(
    result: P4ValidationResult,
    claims: list[EntityClaim],
    edges: list[Edge],
    decisions: list[ResolutionDecision],
    suppressed: list[SuppressedComparison],
    findings: list[P4FindingRecord],
) -> None:
    for claim in claims:
        prov = claim.provenance
        recomputed = deterministic_id(
            "P4C",
            claim.project_id,
            prov.document_id or "",
            claim.candidate_entity_type,
            claim.attribute,
            claim.normalized_value,
            prov.section_id or prov.table_id or "meta",
            str(prov.char_start if prov.char_start is not None else ""),
        )
        if claim.claim_id != recomputed:
            result.error(f"{claim.claim_id}: claim id does not recompute")
    for edge in edges:
        recomputed = deterministic_id(
            "P4G", edge.project_id, edge.relation, edge.source_entity_id, edge.target_entity_id
        )
        if edge.edge_id != recomputed:
            result.error(f"{edge.edge_id}: edge id does not recompute")
    for decision in decisions:
        recomputed = deterministic_id(
            "P4R",
            decision.project_id,
            decision.entity_type,
            decision.decision,
            decision.signal,
            "|".join(sorted(decision.entity_ids)),
        )
        if decision.decision_id != recomputed:
            result.error(f"{decision.decision_id}: decision id does not recompute")
    for suppression in suppressed:
        recomputed = deterministic_id(
            "P4S",
            suppression.project_id,
            suppression.check,
            suppression.attribute,
            suppression.reason,
            "|".join(sorted(suppression.claim_ids)),
        )
        if suppression.suppression_id != recomputed:
            result.error(f"{suppression.suppression_id}: suppression id does not recompute")
    for finding in findings:
        if finding.claim_ids:
            key = "|".join(finding.claim_ids)
        elif finding.entity_ids:
            key = "|".join(finding.entity_ids)
        elif finding.package_check is not None:
            key = f"{finding.package_check.check}@" + "|".join(
                finding.package_check.inspected_document_ids
            )
        else:
            key = ""
        recomputed = deterministic_id(
            "P4", finding.project_id, finding.finding_type, finding.document_id or "", key
        )
        if finding.finding_id != recomputed:
            result.error(
                f"{finding.finding_id}: finding id does not recompute from its"
                " referenced claims/entities/package check (possible evidence tampering)"
            )


# --- references --------------------------------------------------------------


def _check_references(
    result: P4ValidationResult,
    claims: list[EntityClaim],
    entities: list[Entity],
    edges: list[Edge],
    decisions: list[ResolutionDecision],
    findings: list[P4FindingRecord],
) -> None:
    claim_ids = {c.claim_id for c in claims}
    entity_ids = {e.entity_id for e in entities}
    for edge in edges:
        if edge.source_entity_id not in entity_ids:
            result.error(f"{edge.edge_id}: source entity {edge.source_entity_id} does not resolve")
        if edge.target_entity_id not in entity_ids:
            result.error(f"{edge.edge_id}: target entity {edge.target_entity_id} does not resolve")
        for claim_id in edge.claim_ids:
            if claim_id not in claim_ids:
                result.error(f"{edge.edge_id}: unresolved claim {claim_id}")
    for entity in entities:
        for claim_id in entity.claim_ids:
            if claim_id not in claim_ids:
                result.error(f"{entity.entity_id}: unresolved claim {claim_id}")
    for decision in decisions:
        for entity_id in decision.entity_ids:
            if entity_id not in entity_ids:
                result.error(f"{decision.decision_id}: unresolved entity {entity_id}")
        for claim_id in decision.claim_ids:
            if claim_id not in claim_ids:
                result.error(f"{decision.decision_id}: unresolved claim {claim_id}")
    for finding in findings:
        for claim_id in finding.claim_ids:
            if claim_id not in claim_ids:
                result.error(f"{finding.finding_id}: unresolved claim {claim_id}")
        for entity_id in finding.entity_ids:
            if entity_id not in entity_ids:
                result.error(f"{finding.finding_id}: unresolved entity {entity_id}")
        for conflicting in finding.conflicting_claims:
            if conflicting.claim_id not in claim_ids:
                result.error(
                    f"{finding.finding_id}: conflicting claim {conflicting.claim_id}"
                    " does not resolve"
                )


# --- grounding ---------------------------------------------------------------


def _check_grounding(
    result: P4ValidationResult, dataset_dir: Path, claims: list[EntityClaim]
) -> None:
    try:
        section_records = {
            str(r["section_id"]): r for r in _iter_jsonl(dataset_dir / "sections.jsonl")
        }
        section_text = {
            sid: section_evidence_text(record) for sid, record in section_records.items()
        }
        table_cells = {
            str(r["table_id"]): r.get("cells") or []
            for r in _iter_jsonl(dataset_dir / "tables.jsonl")
        }
        project_meta = {
            str(r["project_id"]): r for r in _iter_jsonl(dataset_dir / "projects.jsonl")
        }
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        result.error(f"cannot read dataset containers: {exc}")
        return
    for claim in claims:
        prov = claim.provenance
        needle = normalize_text(claim.raw_value)
        if prov.source_kind == "section_text":
            if prov.section_id not in section_text:
                result.error(f"{claim.claim_id}: unknown section {prov.section_id}")
                continue
            source = section_text[prov.section_id]
            # Blocker B: the character span must resolve EXACTLY to the raw value
            # against the ORIGINAL source string — not a normalized/collapsed one.
            if prov.char_start is not None and prov.char_end is not None:
                span = source[prov.char_start : prov.char_end]
                if span != claim.raw_value:
                    result.error(
                        f"{claim.claim_id}: character span"
                        f" [{prov.char_start}:{prov.char_end}] resolves to {span!r},"
                        f" not raw value {claim.raw_value!r} (invalid span)"
                    )
                    continue
            elif needle and needle not in normalize_text(source):
                result.error(
                    f"{claim.claim_id}: raw value {claim.raw_value!r} not found in"
                    f" section {prov.section_id} (possible claim tampering)"
                )
        elif prov.source_kind == "table_cell":
            grid = table_cells.get(prov.table_id or "")
            if grid is None:
                result.error(f"{claim.claim_id}: unknown table {prov.table_id}")
                continue
            joined = normalize_text(" ".join(cell for row in grid for cell in row))
            if needle and needle not in joined:
                result.error(f"{claim.claim_id}: raw value not found in table {prov.table_id}")
        elif prov.source_kind == "project_metadata":
            project = project_meta.get(claim.project_id)
            if project is None:
                result.error(f"{claim.claim_id}: unknown project {claim.project_id}")
                continue
            values = {str(project.get("region") or ""), str(project.get("industry") or "")}
            if claim.raw_value not in values:
                result.error(
                    f"{claim.claim_id}: metadata value {claim.raw_value!r} does not"
                    " match projects.jsonl (possible claim tampering)"
                )


# --- deterministic replay (resolution + checks) ------------------------------


def _dump(objects: list[Any]) -> list[dict[str, Any]]:
    return [obj.model_dump(mode="json") for obj in objects]


def _check_replay(
    result: P4ValidationResult,
    dataset_dir: Path,
    claims: list[EntityClaim],
    entities: list[Entity],
    edges: list[Edge],
    decisions: list[ResolutionDecision],
    findings: list[P4FindingRecord],
    suppressed: list[SuppressedComparison],
) -> None:
    """Blocker C: independently RE-DERIVE the entities, graph edges, resolution
    decisions, findings and suppressions from the serialized claims + accepted
    dataset, then compare to the serialized output. This goes beyond referential
    existence: a resolution decision whose claim reference was swapped for an
    unrelated existing claim, or a finding whose evidence note was rewritten,
    does not reproduce and is rejected — even when all IDs still resolve.
    """
    project_ids = {e.project_id for e in entities}
    document_ids = {
        e.source_document_ids[0]
        for e in entities
        if e.entity_type == "document" and e.source_document_ids
    }
    try:
        all_projects = {
            str(r["project_id"]): r for r in _iter_jsonl(dataset_dir / "projects.jsonl")
        }
        all_documents = _iter_jsonl(dataset_dir / "documents.jsonl")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        result.error(f"cannot read dataset for replay: {exc}")
        return

    projects_by_id = {pid: all_projects[pid] for pid in project_ids if pid in all_projects}
    documents = [d for d in all_documents if str(d["document_id"]) in document_ids]

    try:
        resolution = resolve_entities(claims, projects_by_id, documents)
        graph = build_graph(resolution.entities)
        checks = run_checks(claims, resolution.operator_by_project, projects_by_id, documents)
    except Exception as exc:  # replay must never crash the validator
        result.error(f"replay from claims failed: {exc}")
        return

    if _dump(resolution.entities) != _dump(entities):
        result.error(
            "entities.jsonl does not reproduce from claims — resolution tampering"
            " (e.g. an unsafe merge or altered entity)"
        )
    if _dump(resolution.decisions) != _dump(decisions):
        result.error(
            "resolution_decisions.jsonl does not reproduce from claims — decision"
            " tampering (unrelated claim reference, altered reason/signal/result)"
        )
    if _dump(graph.edges) != _dump(edges):
        result.error("edges.jsonl does not reproduce from resolved entities (graph tampering)")
    # Findings get the pipeline's final severity-aware ordering before writing.
    severity_sort = {"high": 0, "medium": 1, "low": 2, "info": 3}
    replayed_findings = sorted(
        checks.findings,
        key=lambda f: (
            f.project_id,
            f.document_id or "~",
            severity_sort.get(f.severity, 9),
            f.finding_type,
            f.finding_id,
        ),
    )
    if _dump(replayed_findings) != _dump(findings):
        result.error(
            "findings.jsonl does not reproduce from claims + resolution — finding"
            " tampering (fabricated evidence, altered inspected documents, checked"
            " attribute, zero-match count or explanation)"
        )
    if _dump(checks.suppressed) != _dump(suppressed):
        result.error("suppressed_comparisons.jsonl does not reproduce from claims (tampering)")


# --- finding rules -----------------------------------------------------------


def _check_finding_rules(result: P4ValidationResult, findings: list[P4FindingRecord]) -> None:
    for finding in findings:
        if finding.finding_type not in P4_FINDING_TYPES:
            result.error(f"{finding.finding_id}: unknown finding_type {finding.finding_type}")
        if finding.severity not in SEVERITIES:
            result.error(f"{finding.finding_id}: invalid severity {finding.severity}")
        if finding.severity == "high":
            result.error(f"{finding.finding_id}: high severity is not permitted in the P4 MVP")
        if finding.finding_type in DIAGNOSTIC_FINDING_TYPES and finding.severity != "info":
            result.error(
                f"{finding.finding_id}: diagnostic finding must be severity info,"
                f" got {finding.severity}"
            )
        if finding.finding_type in CONFLICT_FINDING_TYPES and finding.severity not in (
            "low",
            "medium",
        ):
            result.error(
                f"{finding.finding_id}: conflict finding must be low or medium,"
                f" got {finding.severity}"
            )
        if finding.priority_score != points_for(finding.severity):
            result.error(
                f"{finding.finding_id}: priority_score {finding.priority_score}"
                f" != severity points for {finding.severity}"
            )
        if finding.confidence is not None and not 0.0 <= finding.confidence <= 1.0:
            result.error(f"{finding.finding_id}: confidence out of range")
        if finding.confidence is not None and finding.confidence_factors:
            recomputed = round(
                min(
                    CONFIDENCE_MAX,
                    max(CONFIDENCE_MIN, sum(f.delta for f in finding.confidence_factors)),
                ),
                2,
            )
            if abs(recomputed - finding.confidence) > 0.001:
                result.error(
                    f"{finding.finding_id}: confidence {finding.confidence} does not"
                    f" recompute from its factors ({recomputed})"
                )
        # conflict findings must carry conflicting-claim evidence
        if finding.finding_type in CONFLICT_FINDING_TYPES and not finding.conflicting_claims:
            result.error(
                f"{finding.finding_id}: conflict finding without conflicting_claims evidence"
            )


# --- scores ------------------------------------------------------------------


def _check_scores(
    result: P4ValidationResult,
    findings: list[P4FindingRecord],
    document_scores: list[P4DocumentScoreRecord],
    project_scores: list[P4ProjectScoreRecord],
) -> None:
    findings_by_doc: dict[str, list[P4FindingRecord]] = {}
    package_by_project: dict[str, list[P4FindingRecord]] = {}
    for finding in findings:
        if finding.document_id is not None:
            findings_by_doc.setdefault(finding.document_id, []).append(finding)
        else:
            package_by_project.setdefault(finding.project_id, []).append(finding)

    doc_scores_by_project: dict[str, list[int]] = {}
    for record in document_scores:
        expected = min(
            100, sum(f.priority_score for f in findings_by_doc.get(record.document_id, []))
        )
        if record.cross_document_coherence_priority_score != expected:
            result.error(
                f"document score for {record.document_id} does not recompute (expected {expected})"
            )
        doc_scores_by_project.setdefault(record.project_id, []).append(expected)
    for project_record in project_scores:
        doc_points = doc_scores_by_project.get(project_record.project_id, [])
        package_points = sum(
            f.priority_score for f in package_by_project.get(project_record.project_id, [])
        )
        mean_documents = sum(doc_points) / len(doc_points) if doc_points else 0.0
        expected_total = min(100, round(mean_documents) + package_points)
        if project_record.cross_document_coherence_priority_score != expected_total:
            result.error(
                f"project score for {project_record.project_id} does not recompute"
                f" (expected {expected_total})"
            )


def _check_project_stats(
    result: P4ValidationResult,
    entities: list[Entity],
    edges: list[Edge],
    decisions: list[ResolutionDecision],
    suppressed: list[SuppressedComparison],
    project_scores: list[P4ProjectScoreRecord],
) -> None:
    for record in project_scores:
        project_id = record.project_id
        project_entities = [e for e in entities if e.project_id == project_id]
        linked: set[str] = set()
        for entity in project_entities:
            if (
                entity.entity_type not in ("project", "document")
                and len(entity.source_document_ids) >= 2
            ):
                linked.update(entity.source_document_ids)
        unresolved: set[str] = set()
        for decision in decisions:
            if decision.project_id == project_id and decision.decision == "unresolved":
                unresolved.update(decision.entity_ids)
        expected = {
            "entity_count": len(project_entities),
            "edge_count": sum(1 for e in edges if e.project_id == project_id),
            "linked_document_count": len(linked),
            "unresolved_entity_count": len(unresolved),
            "suppressed_comparison_count": sum(1 for s in suppressed if s.project_id == project_id),
        }
        for field_name, value in expected.items():
            if getattr(record, field_name) != value:
                result.error(
                    f"project score {project_id}: {field_name} {getattr(record, field_name)}"
                    f" does not match artifacts ({value})"
                )


# --- ordering ----------------------------------------------------------------


def _check_ordering(
    result: P4ValidationResult,
    findings: list[P4FindingRecord],
    entities: list[Entity],
    edges: list[Edge],
) -> None:
    severity_sort = {"high": 0, "medium": 1, "low": 2, "info": 3}
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
    if [e.entity_id for e in entities] != [
        e.entity_id
        for e in sorted(entities, key=lambda e: (e.project_id, e.entity_type, e.entity_id))
    ]:
        result.error("entities.jsonl is not deterministically ordered")
    if [e.edge_id for e in edges] != [
        e.edge_id for e in sorted(edges, key=lambda e: (e.project_id, e.relation, e.edge_id))
    ]:
        result.error("edges.jsonl is not deterministically ordered")


# --- metrics / report --------------------------------------------------------


def _check_metrics_and_report(
    result: P4ValidationResult,
    output_dir: Path,
    claims: list[EntityClaim],
    entities: list[Entity],
    edges: list[Edge],
    suppressed: list[SuppressedComparison],
    findings: list[P4FindingRecord],
) -> None:
    try:
        metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.error(f"metrics.json unreadable: {exc}")
        return
    checks = {
        "claims_total": len(claims),
        "entities_total": len(entities),
        "edges_total": len(edges),
        "suppressed_comparisons_total": len(suppressed),
        "findings_total": len(findings),
        "proven_cross_document_conflicts": sum(
            1 for f in findings if f.finding_type in CONFLICT_FINDING_TYPES
        ),
    }
    for key, value in checks.items():
        if metrics.get(key) != value:
            result.error(f"metrics.{key} does not match artifacts (expected {value})")
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1
    if metrics.get("findings_by_severity") != dict(sorted(by_severity.items())):
        result.error("metrics.findings_by_severity does not match findings.jsonl")
    if metrics.get("findings_by_type") != dict(sorted(by_type.items())):
        result.error("metrics.findings_by_type does not match findings.jsonl")
    report = (output_dir / "report.md").read_text(encoding="utf-8")
    if f"Всего: {len(findings)}" not in report:
        result.error("report.md findings count does not match findings.jsonl")


# --- review template ---------------------------------------------------------


def _check_review_template(
    result: P4ValidationResult,
    dataset_dir: Path,
    findings: list[P4FindingRecord],
    annotations_root: Path | None,
) -> None:
    template_root = annotations_root or dataset_dir.parent.parent / "annotations"
    template_path = template_root / "p4_review_template.jsonl"
    if not template_path.exists():
        return
    finding_ids = [f.finding_id for f in findings]
    template_ids = [
        str(json.loads(line)["finding_id"])
        for line in template_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    unknown = [t for t in template_ids if t not in set(finding_ids)]
    missing = [f for f in finding_ids if f not in set(template_ids)]
    for template_id in unknown:
        result.error(f"review template references unknown finding {template_id}")
    for finding_id in missing:
        result.error(f"review template is missing finding {finding_id}")
    if not unknown and not missing and template_ids != finding_ids:
        result.error("review template order is not deterministic")


# --- safety ------------------------------------------------------------------


def _check_no_absolute_paths(result: P4ValidationResult, output_dir: Path) -> None:
    for name in _OUTPUT_FILES:
        text = (output_dir / name).read_text(encoding="utf-8")
        if "/Users/" in text or "\\Users\\" in text or "/home/" in text:
            result.error(f"{name}: contains an absolute local path")


def _check_dataset_untouched(result: P4ValidationResult, dataset_dir: Path) -> None:
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
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != recorded[name]:
            result.error(f"dataset file {name} changed after P4 run (checksum mismatch)")


def _check_output_location(result: P4ValidationResult, dataset_dir: Path, output_dir: Path) -> None:
    try:
        if output_dir.resolve().is_relative_to(dataset_dir.resolve()):
            result.error("P4 output directory must not live inside the curated dataset")
    except (OSError, ValueError):
        pass


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
