"""P3 run orchestration over the curated dataset (read-only input).

Deterministic end to end: the same dataset and configuration produce
byte-identical artifacts — P3 output files contain NO timestamps (elapsed
time is reported only on stdout by the CLI). The review template merge
preserves human decisions exactly like P1's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dalel.pillars.quantitative_consistency.aggregations import check_aggregations
from dalel.pillars.quantitative_consistency.comparisons import (
    compare_pair,
    percent_triple_findings,
    single_mention_findings,
)
from dalel.pillars.quantitative_consistency.config import config_snapshot
from dalel.pillars.quantitative_consistency.extractor import extract_mentions
from dalel.pillars.quantitative_consistency.input_contract import validate_input_records
from dalel.pillars.quantitative_consistency.matcher import build_candidates
from dalel.pillars.quantitative_consistency.reports import render_p3_report
from dalel.pillars.quantitative_consistency.resolution import resolve_ambiguities
from dalel.pillars.quantitative_consistency.schemas import (
    ComparisonCandidate,
    P3AggregationCheck,
    P3DocumentScoreRecord,
    P3FindingRecord,
    P3ProjectScoreRecord,
    P3SuppressedSample,
    QuantMention,
)
from dalel.pillars.quantitative_consistency.scoring import score_document, score_project
from dalel.pillars.quantitative_consistency.semantic_context import lexicon_snapshot


class P3RunError(Exception):
    """Blocking P3 execution failure (missing/invalid curated input)."""


@dataclass
class P3Options:
    dataset_dir: Path
    output_dir: Path
    annotations_root: Path
    project_id: str | None = None
    document_id: str | None = None
    write_review_template: bool = True


@dataclass
class P3RunResult:
    mentions: list[QuantMention] = field(default_factory=list)
    suppressed_samples: list[P3SuppressedSample] = field(default_factory=list)
    candidates: list[ComparisonCandidate] = field(default_factory=list)
    aggregation_checks: list[P3AggregationCheck] = field(default_factory=list)
    findings: list[P3FindingRecord] = field(default_factory=list)
    document_scores: list[P3DocumentScoreRecord] = field(default_factory=list)
    project_scores: list[P3ProjectScoreRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    review_template_path: Path | None = None
    review_template_created: bool = False
    review_template_preserved_decisions: int = 0
    review_template_stale_rows: int = 0


_SEVERITY_SORT = {"high": 0, "medium": 1, "low": 2, "info": 3}


# Minimal record contracts per curated file: expected user-input problems
# (malformed JSON, missing keys) become a concise P3RunError with the file
# and line, never an uncontrolled traceback.
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "projects.jsonl": ("project_id",),
    "documents.jsonl": ("project_id", "document_id", "document_type"),
    "pages.jsonl": ("page_number", "provenance"),
    "sections.jsonl": ("section_id", "text", "provenance"),
    "tables.jsonl": ("table_id", "cells", "provenance"),
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise P3RunError(
            f"curated file is missing: {path};"
            " re-run `dalel curate` or point --dataset at a built dataset"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise P3RunError(
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
            raise P3RunError(
                f"{path.name}: line {line_number}: invalid JSON ({exc.msg});"
                " regenerate the curated dataset with `dalel curate --force`"
            ) from exc
        if not isinstance(record, dict):
            raise P3RunError(
                f"{path.name}: line {line_number}: record is not a JSON object;"
                " regenerate the curated dataset"
            )
        missing = [key for key in required if key not in record]
        if missing:
            raise P3RunError(
                f"{path.name}: line {line_number}: missing required"
                f" field(s) {', '.join(missing)}; the file does not match the"
                " Curated Dataset v1 contract — run `dalel validate-curated`"
            )
        if "provenance" in required and "document_id" not in (record.get("provenance") or {}):
            raise P3RunError(
                f"{path.name}: line {line_number}: provenance.document_id is"
                " missing; the file does not match the Curated Dataset v1"
                " contract — run `dalel validate-curated`"
            )
        records.append(record)
    # Full accepted-contract validation: nested types, forbidden extras,
    # value patterns and supported schema versions.
    validate_input_records(path.name, records, P3RunError)
    return records


def run_p3(options: P3Options) -> P3RunResult:
    projects = _read_jsonl(options.dataset_dir / "projects.jsonl")
    documents = _read_jsonl(options.dataset_dir / "documents.jsonl")
    pages = _read_jsonl(options.dataset_dir / "pages.jsonl")
    sections = _read_jsonl(options.dataset_dir / "sections.jsonl")
    tables = _read_jsonl(options.dataset_dir / "tables.jsonl")

    if options.project_id is not None:
        known = {str(p["project_id"]) for p in projects}
        if options.project_id not in known:
            raise P3RunError(f"--project-id {options.project_id!r} not in curated dataset")
    if options.document_id is not None:
        known_docs = {str(d["document_id"]) for d in documents}
        if options.document_id not in known_docs:
            raise P3RunError(f"--document-id {options.document_id!r} not in curated dataset")

    selected_documents = [
        d
        for d in documents
        if (options.project_id is None or str(d["project_id"]) == options.project_id)
        and (options.document_id is None or str(d["document_id"]) == options.document_id)
    ]
    selected_ids = {str(d["document_id"]) for d in selected_documents}

    def _by_document(records: list[dict[str, Any]], key: str = "provenance") -> dict[str, list]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            document_id = str(record[key]["document_id"])
            if document_id in selected_ids:
                grouped.setdefault(document_id, []).append(record)
        return grouped

    extraction = extract_mentions(
        selected_documents,
        _by_document(sections),
        _by_document(tables),
        _by_document(pages),
    )

    ambiguities_resolved = resolve_ambiguities(extraction)

    candidate_result = build_candidates(extraction.mentions)
    mentions_by_id = {m.mention_id: m for m in extraction.mentions}

    findings: list[P3FindingRecord] = []
    for pair in candidate_result.pairs:
        finding = compare_pair(pair)
        if finding is not None:
            findings.append(finding)
    aggregation = check_aggregations(extraction.sheets, mentions_by_id)
    findings.extend(aggregation.findings)
    findings.extend(percent_triple_findings(extraction.percent_triples))
    findings.extend(single_mention_findings(extraction.mentions))

    # Deduplicate by finding_id (content-derived), then collapse EQUIVALENT
    # value conflicts: the same contradiction (same subject, same value pair)
    # reported through different mention pairs is one finding for the expert.
    # The highest-confidence representative wins (ties: lowest finding_id).
    unique: dict[str, P3FindingRecord] = {}
    for finding in findings:
        unique.setdefault(finding.finding_id, finding)
    deduped_value_conflicts = 0
    by_value_pair: dict[tuple[str, ...], P3FindingRecord] = {}
    passthrough: list[P3FindingRecord] = []
    for finding in sorted(unique.values(), key=lambda f: (-(f.confidence or 0), f.finding_id)):
        if finding.finding_type not in ("direct_value_conflict", "equivalent_unit_conflict"):
            passthrough.append(finding)
            continue
        comparison = finding.comparison
        mention_subjects = {
            mentions_by_id[m].substance or mentions_by_id[m].metric_group or ""
            for m in finding.mention_ids
            if m in mentions_by_id
        }
        key = (
            finding.project_id,
            "|".join(sorted(mention_subjects)),
            (comparison.canonical_unit or "") if comparison else "",
            "|".join(sorted([comparison.expected_value or "", comparison.observed_value or ""]))
            if comparison
            else finding.finding_id,
        )
        if key in by_value_pair:
            deduped_value_conflicts += 1
            continue
        by_value_pair[key] = finding
    findings = sorted(
        [*passthrough, *by_value_pair.values()],
        key=lambda f: (
            f.project_id,
            f.document_id or "~",  # cross-document findings after documents
            _SEVERITY_SORT.get(f.severity, 9),
            f.finding_type,
            f.finding_id,
        ),
    )

    result = P3RunResult(
        mentions=extraction.mentions,
        suppressed_samples=sorted(
            extraction.suppressed_samples, key=lambda s: (s.reason, s.sample_id)
        ),
        candidates=candidate_result.candidates,
        aggregation_checks=aggregation.checks,
        findings=findings,
    )

    # --- scores -----------------------------------------------------------------
    findings_by_document: dict[str, list[P3FindingRecord]] = {}
    package_findings_by_project: dict[str, list[P3FindingRecord]] = {}
    for finding in findings:
        if finding.document_id is not None:
            findings_by_document.setdefault(finding.document_id, []).append(finding)
        else:
            package_findings_by_project.setdefault(finding.project_id, []).append(finding)

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
            score_project(
                project_id,
                document_scores,
                package_findings_by_project.get(project_id, []),
            )
        )

    result.metrics = _build_metrics(
        result, extraction, candidate_result, aggregation, projects, selected_documents
    )
    result.metrics["findings_deduplicated_equivalent"] = deduped_value_conflicts
    result.metrics["ambiguities_resolved_from_context"] = ambiguities_resolved
    _write_outputs(options, result)
    return result


def _build_metrics(
    result: P3RunResult,
    extraction: Any,
    candidate_result: Any,
    aggregation: Any,
    projects: list[dict[str, Any]],
    selected_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    from dalel.pillars.quantitative_consistency import P3_VERSION
    from dalel.pillars.quantitative_consistency.config import P3_SCORING_CONFIG_VERSION

    mentions = result.mentions
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_document: dict[str, int] = {}
    for finding in result.findings:
        by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        key = finding.document_id or f"__package__/{finding.project_id}"
        by_document[key] = by_document.get(key, 0) + 1

    by_canonical_unit: dict[str, int] = {}
    for mention in mentions:
        if mention.canonical_unit:
            by_canonical_unit[mention.canonical_unit] = (
                by_canonical_unit.get(mention.canonical_unit, 0) + 1
            )

    suppressed_candidates = dict(sorted(candidate_result.suppressed_counts.items()))
    for reason, count in (aggregation.suppressed_counts or {}).items():
        suppressed_candidates[reason] = suppressed_candidates.get(reason, 0) + count

    scores = [s.quantitative_consistency_priority_score for s in result.document_scores]
    project_ids = {str(d["project_id"]) for d in selected_documents}
    return {
        "p3_version": P3_VERSION,
        "scoring_config_version": P3_SCORING_CONFIG_VERSION,
        "documents_analyzed": len(selected_documents),
        "projects_analyzed": len([p for p in projects if str(p["project_id"]) in project_ids]),
        "mentions_total": len(mentions),
        "mentions_from_tables": sum(1 for m in mentions if m.location.source_kind == "table_cell"),
        "mentions_from_sections": sum(
            1 for m in mentions if m.location.source_kind == "section_text"
        ),
        "mentions_with_unit": sum(1 for m in mentions if m.unit_canonical),
        "unit_source_inline": sum(1 for m in mentions if m.unit_source == "inline"),
        "unit_source_column_header": sum(1 for m in mentions if m.unit_source == "column_header"),
        "mentions_ambiguous": sum(1 for m in mentions if "ambiguous_decimal_grouping" in m.flags),
        "mentions_ocr": sum(1 for m in mentions if "ocr_source" in m.flags),
        "mentions_by_canonical_unit": dict(sorted(by_canonical_unit.items())),
        "doc_decimal_styles": dict(sorted(extraction.doc_styles.items())),
        "suppressed_numbers_total": sum(extraction.suppressed_counts.values()),
        "suppressed_numbers_by_reason": dict(sorted(extraction.suppressed_counts.items())),
        "suppressed_examples": {
            reason: examples for reason, examples in sorted(extraction.suppressed_examples.items())
        },
        "candidates_compared": sum(1 for c in result.candidates if c.status == "compared"),
        "candidates_suppressed_serialized": sum(
            1 for c in result.candidates if c.status == "suppressed"
        ),
        "suppressed_candidates_total": sum(suppressed_candidates.values()),
        "suppressed_candidates_by_reason": suppressed_candidates,
        "aggregation_checks_total": aggregation.checks_total,
        "aggregation_checks_consistent": aggregation.checks_consistent,
        "percent_triples_found": len(extraction.percent_triples),
        "findings_total": len(result.findings),
        "findings_by_type": dict(sorted(by_type.items())),
        "findings_by_severity": dict(sorted(by_severity.items())),
        "findings_by_document": dict(sorted(by_document.items())),
        "score_distribution": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "mean": round(sum(scores) / len(scores), 1) if scores else None,
            "documents": {
                s.document_id: s.quantitative_consistency_priority_score
                for s in result.document_scores
            },
        },
        "evaluation_note": (
            "4 проекта: ML accuracy не заявляется; метрики описывают покрытие"
            " и распределения, а не качество классификации"
        ),
    }


_TEMPLATE_HUMAN_FIELDS = ("expert_decision", "corrected_severity", "expert_comment", "reviewer_id")


def _write_outputs(options: P3Options, result: P3RunResult) -> None:
    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    def _write_jsonl(name: str, records: list[dict[str, Any]]) -> None:
        with (output_dir / name).open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")

    _write_jsonl("mentions.jsonl", [m.model_dump(mode="json") for m in result.mentions])
    _write_jsonl(
        "suppressed_samples.jsonl",
        [s.model_dump(mode="json") for s in result.suppressed_samples],
    )
    _write_jsonl("candidates.jsonl", [c.model_dump(mode="json") for c in result.candidates])
    _write_jsonl(
        "aggregation_checks.jsonl",
        [c.model_dump(mode="json") for c in result.aggregation_checks],
    )
    _write_jsonl("findings.jsonl", [f.model_dump(mode="json") for f in result.findings])
    _write_jsonl(
        "document_scores.jsonl", [s.model_dump(mode="json") for s in result.document_scores]
    )
    _write_jsonl("project_scores.jsonl", [s.model_dump(mode="json") for s in result.project_scores])
    (output_dir / "metrics.json").write_text(
        json.dumps(result.metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    snapshot = config_snapshot()
    snapshot["lexicons"] = lexicon_snapshot()
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(render_p3_report(result), encoding="utf-8")

    if options.write_review_template:
        _merge_review_template(options, result, output_dir)


def _merge_review_template(options: P3Options, result: P3RunResult, output_dir: Path) -> None:
    """Create/update the expert review template WITHOUT losing human decisions
    (same contract as P1's template merge)."""
    options.annotations_root.mkdir(parents=True, exist_ok=True)
    template_path = options.annotations_root / "p3_review_template.jsonl"
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
