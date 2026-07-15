"""P3 output validation: schemas, IDs, ordering, evidence, recomputation.

Also verifies that the curated dataset files P3 reads still match their
recorded checksums — running P3 must never modify Dataset v1 (its accepted
fingerprint contract stays intact by construction: P3 writes only under its
own output directory and the annotations review template).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dalel.pillars.quantitative_consistency.comparisons import evaluate_tolerance
from dalel.pillars.quantitative_consistency.config import (
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    SEVERITY_POINTS,
)
from dalel.pillars.quantitative_consistency.normalization import normalize_for_scan
from dalel.pillars.quantitative_consistency.number_parser import decimal_str, scan_text
from dalel.pillars.quantitative_consistency.schemas import (
    P3_FINDING_TYPES,
    SEVERITIES,
    ComparisonCandidate,
    P3AggregationCheck,
    P3DocumentScoreRecord,
    P3FindingRecord,
    P3ProjectScoreRecord,
    P3SuppressedSample,
    QuantMention,
    deterministic_id,
)
from dalel.pillars.quantitative_consistency.scoring import (
    high_severity_eligible,
    severity_for_conflict,
)
from dalel.pillars.quantitative_consistency.units import (
    canonical_unit_for,
    dimension_key,
    lookup_unit,
)


def _cap(severity: str, cap: str) -> str:
    order = ["info", "low", "medium", "high"]
    return order[min(order.index(severity), order.index(cap))]


_OUTPUT_FILES = (
    "mentions.jsonl",
    "suppressed_samples.jsonl",
    "candidates.jsonl",
    "aggregation_checks.jsonl",
    "findings.jsonl",
    "document_scores.jsonl",
    "project_scores.jsonl",
    "metrics.json",
    "config_snapshot.json",
    "report.md",
)

# Dataset files P3 reads; their checksums must be unchanged after a run.
_INPUT_FILES = (
    "projects.jsonl",
    "documents.jsonl",
    "pages.jsonl",
    "sections.jsonl",
    "tables.jsonl",
)


@dataclass
class P3ValidationResult:
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


def validate_p3_outputs(
    dataset_dir: Path,
    output_dir: Path,
    annotations_root: Path | None = None,
) -> P3ValidationResult:
    result = P3ValidationResult()

    for name in _OUTPUT_FILES:
        if not (output_dir / name).is_file():
            result.error(f"missing output file: {name}")
    if not result.ok:
        return result

    try:
        mentions_raw = _read_jsonl(output_dir / "mentions.jsonl")
        candidates_raw = _read_jsonl(output_dir / "candidates.jsonl")
        findings_raw = _read_jsonl(output_dir / "findings.jsonl")
        document_scores_raw = _read_jsonl(output_dir / "document_scores.jsonl")
        project_scores_raw = _read_jsonl(output_dir / "project_scores.jsonl")
    except (ValueError, json.JSONDecodeError) as exc:
        result.error(f"output parse failure: {exc}")
        return result

    mentions: list[QuantMention] = []
    candidates: list[ComparisonCandidate] = []
    findings: list[P3FindingRecord] = []
    for raw, model, bucket, name in (
        (mentions_raw, QuantMention, mentions, "mentions"),
        (candidates_raw, ComparisonCandidate, candidates, "candidates"),
        (findings_raw, P3FindingRecord, findings, "findings"),
    ):
        for index, record in enumerate(raw, start=1):
            try:
                bucket.append(model.model_validate(record))  # type: ignore[attr-defined,arg-type]
            except ValidationError as exc:
                result.error(f"{name}.jsonl:{index}: schema violation: {exc.errors()[:2]}")
    for index, record in enumerate(document_scores_raw, start=1):
        try:
            P3DocumentScoreRecord.model_validate(record)
        except ValidationError as exc:
            result.error(f"document_scores.jsonl:{index}: {exc.errors()[:2]}")
    for index, record in enumerate(project_scores_raw, start=1):
        try:
            P3ProjectScoreRecord.model_validate(record)
        except ValidationError as exc:
            result.error(f"project_scores.jsonl:{index}: {exc.errors()[:2]}")
    if not result.ok:
        return result

    result.counts = {
        "mentions": len(mentions),
        "candidates": len(candidates),
        "findings": len(findings),
        "document_scores": len(document_scores_raw),
        "project_scores": len(project_scores_raw),
    }

    # --- unique, well-formed IDs ---------------------------------------------------
    mention_ids = [m.mention_id for m in mentions]
    if len(set(mention_ids)) != len(mention_ids):
        result.error("duplicate mention_id values")
    finding_ids = [f.finding_id for f in findings]
    if len(set(finding_ids)) != len(finding_ids):
        result.error("duplicate finding_id values")
    candidate_ids = [c.candidate_id for c in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        result.error("duplicate candidate_id values")
    for finding in findings:
        if not finding.finding_id.startswith("P3__"):
            result.error(f"finding id without P3 prefix: {finding.finding_id}")
        if finding.finding_type not in P3_FINDING_TYPES:
            result.error(f"{finding.finding_id}: unknown finding_type {finding.finding_type}")
        if finding.severity not in SEVERITIES:
            result.error(f"{finding.finding_id}: invalid severity {finding.severity}")
        if finding.confidence is not None and not 0.0 <= finding.confidence <= 1.0:
            result.error(f"{finding.finding_id}: confidence out of range")

    # --- evidence resolution ----------------------------------------------------------
    known_mentions = set(mention_ids)
    for finding in findings:
        for mention_id in finding.mention_ids:
            if mention_id not in known_mentions:
                result.error(f"{finding.finding_id}: unresolved mention {mention_id}")
    known_candidates = set(candidate_ids)
    for finding in findings:
        if finding.candidate_id is not None and finding.candidate_id not in known_candidates:
            result.error(f"{finding.finding_id}: unresolved candidate {finding.candidate_id}")
    for candidate in candidates:
        for mention_id in candidate.mention_ids:
            if mention_id not in known_mentions:
                result.error(f"{candidate.candidate_id}: unresolved mention {mention_id}")

    # --- mention containers exist and spans/cells resolve to raw content ---------------
    try:
        section_texts = {
            str(record["section_id"]): str(record.get("text") or "")
            for record in (
                json.loads(line)
                for line in (dataset_dir / "sections.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            )
        }
        table_cells = {
            str(record["table_id"]): record.get("cells") or []
            for record in (
                json.loads(line)
                for line in (dataset_dir / "tables.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        result.error(f"cannot read dataset containers: {exc}")
        return result
    section_norm_cache: dict[str, str] = {}
    for mention in mentions:
        loc = mention.location
        if loc.source_kind == "table_cell":
            if loc.table_id not in table_cells:
                result.error(f"{mention.mention_id}: unknown table {loc.table_id}")
                continue
            grid = table_cells[loc.table_id]
            if loc.row is None or loc.col is None or loc.row >= len(grid):
                result.error(f"{mention.mention_id}: table cell out of range")
                continue
            row = grid[loc.row]
            raw_cell = row[loc.col] if loc.col < len(row) else ""
            normalized_cell = normalize_for_scan(raw_cell)
            raw_number = mention.raw_number
            if raw_number not in normalized_cell and raw_number.lstrip("-") not in normalized_cell:
                result.error(
                    f"{mention.mention_id}: raw number {mention.raw_number!r} not"
                    f" found in table cell {loc.table_id}[{loc.row}][{loc.col}]"
                )
        else:
            if loc.section_id not in section_texts:
                result.error(f"{mention.mention_id}: unknown section {loc.section_id}")
                continue
            if loc.section_id not in section_norm_cache:
                section_norm_cache[loc.section_id] = normalize_for_scan(
                    section_texts[loc.section_id]
                )
            normalized = section_norm_cache[loc.section_id]
            if loc.char_start is not None and loc.char_end is not None:
                span_text = normalized[loc.char_start : loc.char_end]
                if mention.raw_number not in span_text and span_text not in (mention.raw_number):
                    result.error(
                        f"{mention.mention_id}: char span does not contain"
                        f" {mention.raw_number!r} (found {span_text!r})"
                    )

    # --- mentions: conversions, unit registry consistency, IDs -------------------------
    for mention in mentions:
        if mention.canonical_value and mention.value and mention.conversion_factor:
            expected = Decimal(mention.value) * Decimal(mention.conversion_factor)
            if Decimal(mention.canonical_value) != expected:
                result.error(
                    f"{mention.mention_id}: canonical_value {mention.canonical_value}"
                    f" != value*factor {expected}"
                )
        if mention.unit_canonical is not None:
            registry_unit = lookup_unit(mention.unit_canonical)
            if registry_unit is None:
                result.error(
                    f"{mention.mention_id}: unit {mention.unit_canonical!r} is not"
                    " in the declared registry"
                )
            else:
                if mention.dimension != dimension_key(registry_unit):
                    result.error(
                        f"{mention.mention_id}: dimension {mention.dimension}"
                        f" does not match unit {mention.unit_canonical}"
                    )
                if mention.canonical_unit != canonical_unit_for(registry_unit):
                    result.error(
                        f"{mention.mention_id}: canonical_unit"
                        f" {mention.canonical_unit!r} is not the canonical unit"
                        f" for {mention.dimension}"
                    )
                if (
                    mention.conversion_factor is not None
                    and Decimal(mention.conversion_factor) != registry_unit.factor
                ):
                    result.error(
                        f"{mention.mention_id}: conversion factor does not match"
                        f" the declared registry factor for {mention.unit_canonical}"
                    )
        # Content-derived id replays from the mention's own basis fields.
        loc = mention.location
        recomputed_id = deterministic_id(
            "P3Q",
            mention.document_id,
            loc.source_kind,
            loc.table_id or loc.section_id or "",
            str(loc.row if loc.row is not None else ""),
            str(loc.col if loc.col is not None else ""),
            str(loc.char_start if loc.char_start is not None else ""),
            mention.raw_number,
        )
        if mention.mention_id != recomputed_id:
            result.error(f"{mention.mention_id}: mention id does not recompute")

    # --- comparison arithmetic recomputes (values, differences, decisions) ---------------
    mentions_index = {m.mention_id: m for m in mentions}
    candidates_index = {c.candidate_id: c for c in candidates}
    for finding in findings:
        comparison = finding.comparison
        if comparison is None or comparison.abs_diff is None:
            continue
        if comparison.expected_value is None or comparison.observed_value is None:
            continue
        expected = Decimal(comparison.expected_value)
        observed = Decimal(comparison.observed_value)
        stated_diff = Decimal(comparison.abs_diff)
        recomputed = abs(expected - observed)
        # abs_diff may be serialized rounded; allow one quantum of its display.
        quantum = Decimal(1).scaleb(-_decimals(comparison.abs_diff))
        if abs(recomputed - stated_diff) > quantum:
            result.error(
                f"{finding.finding_id}: abs_diff {stated_diff} does not recompute"
                f" (|{expected} - {observed}| = {recomputed})"
            )
        # rel_diff = abs/max(|a|,|b|)
        if comparison.rel_diff is not None:
            denominator = max(abs(expected), abs(observed))
            if denominator != 0:
                rel_expected = recomputed / denominator
                rel_quantum = Decimal(1).scaleb(-_decimals(comparison.rel_diff))
                if abs(rel_expected - Decimal(comparison.rel_diff)) > rel_quantum * 2:
                    result.error(
                        f"{finding.finding_id}: rel_diff {comparison.rel_diff}"
                        f" does not recompute (expected ~{rel_expected})"
                    )
        # conversion evidence recomputes exactly
        for conversion in comparison.conversions:
            if (
                conversion.parsed_value
                and conversion.conversion_factor
                and conversion.canonical_value
            ):
                product = Decimal(conversion.parsed_value) * Decimal(conversion.conversion_factor)
                if Decimal(conversion.canonical_value) != product:
                    result.error(
                        f"{finding.finding_id}: conversion for"
                        f" {conversion.mention_id} does not recompute"
                    )
        # direct/equivalent conflicts: decision, tolerances, formula, unit,
        # observed values, severity and evidence ALL replay from the mention
        # data plus the configuration — never from other output fields.
        if finding.finding_type in ("direct_value_conflict", "equivalent_unit_conflict"):
            pair = [mentions_index[m] for m in finding.mention_ids if m in mentions_index]
            if len(pair) == 2 and all(m.canonical_value for m in pair):
                approximate = any(m.modifier == "approximate" for m in pair)
                kind = (pair[0].dimension or "").split("/")[0]
                evaluation = evaluate_tolerance(
                    Decimal(pair[0].canonical_value or "0"),
                    Decimal(pair[1].canonical_value or "0"),
                    Decimal(pair[0].canonical_quantum or pair[0].display_quantum),
                    Decimal(pair[1].canonical_quantum or pair[1].display_quantum),
                    kind,
                    approximate,
                )
                if not evaluation.mismatch:
                    result.error(
                        f"{finding.finding_id}: mismatch decision does not replay"
                        " (values are within tolerance)"
                    )
                serialized_pair = sorted(
                    [comparison.expected_value or "", comparison.observed_value or ""]
                )
                canonical_pair = sorted(
                    [
                        decimal_str(Decimal(pair[0].canonical_value or "0")),
                        decimal_str(Decimal(pair[1].canonical_value or "0")),
                    ]
                )
                if serialized_pair != canonical_pair:
                    result.error(
                        f"{finding.finding_id}: expected/observed values do not"
                        " replay from the referenced mentions"
                    )
                if comparison.tolerance_abs != decimal_str(evaluation.abs_tolerance):
                    result.error(
                        f"{finding.finding_id}: tolerance_abs does not replay from configuration"
                    )
                if comparison.tolerance_rel != decimal_str(evaluation.rel_tolerance):
                    result.error(
                        f"{finding.finding_id}: tolerance_rel does not replay from configuration"
                    )
                if comparison.rounding_tolerance != decimal_str(evaluation.rounding_tolerance):
                    result.error(f"{finding.finding_id}: rounding_tolerance does not replay")
                if comparison.canonical_unit != pair[0].canonical_unit:
                    result.error(
                        f"{finding.finding_id}: comparison canonical_unit does not"
                        " match the referenced mentions"
                    )
                expected_formula = (
                    "mismatch <=> |a-b| > max(abs_tol, rounding_tol)"
                    " AND |a-b|/max(|a|,|b|) > rel_tol"
                )
                if comparison.formula != expected_formula:
                    result.error(f"{finding.finding_id}: formula does not match the rule")
                expected_rule = (
                    "P3-DIRECT"
                    if pair[0].unit_canonical == pair[1].unit_canonical
                    else "P3-EQUIV-UNIT"
                )
                if finding.rule_id != expected_rule:
                    result.error(f"{finding.finding_id}: rule_id does not match the pair")
                if finding.confidence is not None:
                    replayed = severity_for_conflict(
                        evaluation.rel_diff,
                        max(
                            abs(Decimal(pair[0].canonical_value or "0")),
                            abs(Decimal(pair[1].canonical_value or "0")),
                        ),
                        kind,
                        finding.confidence,
                    )
                    pair_candidate = candidates_index.get(finding.candidate_id or "")
                    if pair_candidate is not None:
                        if any(
                            state == "unknown" for state in pair_candidate.dimension_states.values()
                        ):
                            replayed = _cap(replayed, "low")
                        if replayed == "high" and not high_severity_eligible(
                            pair_candidate.dimension_states, pair
                        ):
                            replayed = "medium"
                    if finding.severity != replayed:
                        result.error(
                            f"{finding.finding_id}: severity {finding.severity}"
                            f" does not replay (expected {replayed})"
                        )
            # evidence pages/quotes must come from the referenced mentions
            for evidence in finding.evidence:
                allowed_pages = {m.location.page_number for m in pair}
                if evidence.page_number not in allowed_pages:
                    result.error(
                        f"{finding.finding_id}: evidence page {evidence.page_number}"
                        " does not belong to any referenced mention"
                    )
                allowed_quotes = {m.raw_text[:200] for m in pair}
                if evidence.quote not in allowed_quotes:
                    result.error(
                        f"{finding.finding_id}: evidence quote does not match any"
                        " referenced mention"
                    )
        # aggregation findings: component sums replay and evidence is complete
        aggregation = comparison.aggregation
        if aggregation is not None:
            included = [c for c in aggregation.components if c.included]
            if not included:
                result.error(f"{finding.finding_id}: aggregation without components")
            elif any(c.value is None for c in included):
                result.error(f"{finding.finding_id}: aggregation component missing value")
            else:
                total = sum((Decimal(c.value) for c in included if c.value), Decimal(0))
                if decimal_str(total) != comparison.expected_value:
                    result.error(
                        f"{finding.finding_id}: aggregation sum {decimal_str(total)}"
                        f" != expected_value {comparison.expected_value}"
                    )
            for conversion in comparison.conversions:
                if conversion.conversion_factor is None or conversion.canonical_value is None:
                    result.error(
                        f"{finding.finding_id}: aggregation conversion evidence"
                        f" incomplete for {conversion.mention_id}"
                    )
            grid = table_cells.get(aggregation.table_id)
            if grid is None:
                result.error(
                    f"{finding.finding_id}: aggregation table {aggregation.table_id} not in dataset"
                )
            else:
                for component in included:
                    if component.row >= len(grid):
                        result.error(
                            f"{finding.finding_id}: component row {component.row} out of range"
                        )
                        continue
                    row = grid[component.row]
                    cell_text = row[aggregation.column] if aggregation.column < len(row) else ""
                    if component.value and not _value_in_cell(component.value, cell_text):
                        result.error(
                            f"{finding.finding_id}: component value {component.value}"
                            f" not found in raw cell"
                            f" {aggregation.table_id}[{component.row}]"
                            f"[{aggregation.column}]"
                        )

    # --- severity/confidence/scoring consistency -------------------------------------------
    for finding in findings:
        if finding.priority_score != SEVERITY_POINTS.get(finding.severity):
            result.error(
                f"{finding.finding_id}: priority_score {finding.priority_score}"
                f" != severity points for {finding.severity}"
            )
        if finding.confidence is not None and finding.confidence_factors:
            base_and_deltas = sum(f.delta for f in finding.confidence_factors)
            recomputed_confidence = round(
                min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, base_and_deltas)), 2
            )
            if abs(recomputed_confidence - finding.confidence) > 0.001:
                result.error(
                    f"{finding.finding_id}: confidence {finding.confidence} does not"
                    f" recompute from its factors ({recomputed_confidence})"
                )

    findings_by_doc: dict[str, list[P3FindingRecord]] = {}
    package_findings: dict[str, list[P3FindingRecord]] = {}
    for finding in findings:
        if finding.document_id is not None:
            findings_by_doc.setdefault(finding.document_id, []).append(finding)
        else:
            package_findings.setdefault(finding.project_id, []).append(finding)
    doc_scores_by_project: dict[str, list[int]] = {}
    for record in document_scores_raw:
        document_id = str(record["document_id"])
        expected_points = min(
            100, sum(f.priority_score for f in findings_by_doc.get(document_id, []))
        )
        if int(record["quantitative_consistency_priority_score"]) != expected_points:
            result.error(
                f"document score for {document_id} does not recompute (expected {expected_points})"
            )
        doc_scores_by_project.setdefault(str(record["project_id"]), []).append(expected_points)
    for record in project_scores_raw:
        project_id = str(record["project_id"])
        doc_points = doc_scores_by_project.get(project_id, [])
        package_points = sum(f.priority_score for f in package_findings.get(project_id, []))
        mean_documents = sum(doc_points) / len(doc_points) if doc_points else 0.0
        expected_total = min(100, round(mean_documents) + package_points)
        if int(record["quantitative_consistency_priority_score"]) != expected_total:
            result.error(
                f"project score for {project_id} does not recompute (expected {expected_total})"
            )

    # --- findings and mentions ordering replays the pipeline sort --------------------------------
    severity_sort = {"high": 0, "medium": 1, "low": 2, "info": 3}
    expected_order = [
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
    if finding_ids != expected_order:
        result.error("findings.jsonl is not deterministically ordered")

    # --- aggregation checks replay from raw table cells ------------------------------------------
    try:
        checks_raw = _read_jsonl(output_dir / "aggregation_checks.jsonl")
    except (ValueError, json.JSONDecodeError) as exc:
        result.error(f"aggregation_checks.jsonl parse failure: {exc}")
        checks_raw = []
    for index, record in enumerate(checks_raw, start=1):
        try:
            check = P3AggregationCheck.model_validate(record)
        except ValidationError as exc:
            result.error(f"aggregation_checks.jsonl:{index}: {exc.errors()[:2]}")
            continue
        grid = table_cells.get(check.table_id)
        if grid is None:
            result.error(f"{check.check_id}: unknown table {check.table_id}")
            continue
        included = [c for c in check.components if c.included]
        if len(included) < 2:
            result.error(f"{check.check_id}: fewer than two included components")
            continue
        total = sum((Decimal(c.value) for c in included if c.value), Decimal(0))
        if decimal_str(total) != check.expected_total:
            result.error(
                f"{check.check_id}: expected_total {check.expected_total} does"
                f" not recompute from components ({decimal_str(total)})"
            )
        for component in included:
            if component.row >= len(grid):
                result.error(f"{check.check_id}: component row out of range")
                continue
            row_cells = grid[component.row]
            cell_text = row_cells[check.column] if check.column < len(row_cells) else ""
            if component.value and not _value_in_cell(component.value, cell_text):
                result.error(
                    f"{check.check_id}: component value {component.value} not found"
                    f" in raw cell {check.table_id}[{component.row}][{check.column}]"
                )
            if component.conversion_factor is None:
                result.error(f"{check.check_id}: component conversion factor missing")
        # observed total must live in the raw total cell
        total_cells = grid[check.total_row] if check.total_row < len(grid) else []
        total_text = total_cells[check.column] if check.column < len(total_cells) else ""
        if not _value_in_cell(check.observed_total, total_text):
            result.error(
                f"{check.check_id}: observed_total {check.observed_total} not found"
                f" in raw total cell"
            )
        abs_diff = abs(total - Decimal(check.observed_total))
        if decimal_str(abs_diff) != check.abs_diff:
            result.error(f"{check.check_id}: abs_diff does not recompute")
        rel_denominator = max(abs(total), abs(Decimal(check.observed_total)))
        check_rel = abs_diff / rel_denominator if rel_denominator != 0 else None
        mismatch = abs_diff > Decimal(check.rounding_tolerance) and (
            check_rel is None or check_rel > Decimal(check.rel_tolerance)
        )
        expected_decision = "mismatch" if mismatch else "consistent"
        if check.decision != expected_decision:
            result.error(
                f"{check.check_id}: decision {check.decision} does not replay"
                f" (expected {expected_decision})"
            )
        if check.decision == "mismatch" and check.finding_id not in set(finding_ids):
            result.error(f"{check.check_id}: mismatch check references unknown finding")

    # --- metrics agree with the artifacts ------------------------------------------------------
    try:
        metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.error(f"metrics.json unreadable: {exc}")
        metrics = {}
    if metrics:
        by_severity: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for finding in findings:
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
            by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1
        if metrics.get("findings_total") != len(findings):
            result.error("metrics.findings_total does not match findings.jsonl")
        if metrics.get("findings_by_severity") != dict(sorted(by_severity.items())):
            result.error("metrics.findings_by_severity does not match findings.jsonl")
        if metrics.get("findings_by_type") != dict(sorted(by_type.items())):
            result.error("metrics.findings_by_type does not match findings.jsonl")
        if metrics.get("mentions_total") != len(mentions):
            result.error("metrics.mentions_total does not match mentions.jsonl")
        compared = sum(1 for c in candidates if c.status == "compared")
        if metrics.get("candidates_compared") != compared:
            result.error("metrics.candidates_compared does not match candidates.jsonl")
        report_text = (output_dir / "report.md").read_text(encoding="utf-8")
        if f"Всего: {len(findings)}" not in report_text:
            result.error("report.md findings count does not match findings.jsonl")

    # --- suppressed samples resolve --------------------------------------------------------------
    samples_path = output_dir / "suppressed_samples.jsonl"
    if samples_path.is_file():
        sample_ids: set[str] = set()
        for index, line in enumerate(
            samples_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                sample = P3SuppressedSample.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as exc:
                result.error(f"suppressed_samples.jsonl:{index}: {exc}")
                continue
            if sample.sample_id in sample_ids:
                result.error(f"duplicate suppressed sample id {sample.sample_id}")
            sample_ids.add(sample.sample_id)
            if sample.table_id is not None and sample.table_id not in table_cells:
                result.error(f"{sample.sample_id}: unknown table {sample.table_id}")
            if sample.section_id is not None and sample.section_id not in section_texts:
                result.error(f"{sample.sample_id}: unknown section {sample.section_id}")
    else:
        result.error("suppressed_samples.jsonl is missing")

    # --- no incompatible dimensions were compared ------------------------------------------
    mentions_by_id = {m.mention_id: m for m in mentions}
    for candidate in candidates:
        if candidate.status != "compared":
            continue
        dimensions = {
            mentions_by_id[m].dimension for m in candidate.mention_ids if m in mentions_by_id
        }
        if len(dimensions) > 1:
            mixed = sorted(map(str, dimensions))
            result.error(f"{candidate.candidate_id}: mixed dimensions compared: {mixed}")

    # --- deterministic ordering --------------------------------------------------------------
    if [c.candidate_id for c in candidates] != [
        c.candidate_id
        for c in sorted(candidates, key=lambda c: (c.project_id, c.rule, c.candidate_id))
    ]:
        result.error("candidates.jsonl is not deterministically ordered")

    # --- review template corresponds to findings ----------------------------------------------
    template_root = annotations_root or dataset_dir.parent.parent / "annotations"
    template_path = template_root / "p3_review_template.jsonl"
    if template_path.exists():
        template_ids = [
            str(json.loads(line)["finding_id"])
            for line in template_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        unknown_ids = [t for t in template_ids if t not in set(finding_ids)]
        missing_ids = [f for f in finding_ids if f not in set(template_ids)]
        for template_id in unknown_ids:
            result.error(f"review template references unknown finding {template_id}")
        for finding_id in missing_ids:
            result.error(f"review template is missing finding {finding_id}")
        if not unknown_ids and not missing_ids and template_ids != finding_ids:
            result.error("review template order is not deterministic")

    # --- input dataset untouched -------------------------------------------------------------
    checksums_path = dataset_dir / "checksums.jsonl"
    if checksums_path.is_file():
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
                result.error(f"dataset file {name} changed after P3 run (checksum mismatch)")
    else:
        result.warnings.append("checksums.jsonl missing: dataset integrity not verified")

    try:
        if output_dir.resolve().is_relative_to(dataset_dir.resolve()):
            result.error("P3 output directory must not live inside the curated dataset")
    except (OSError, ValueError):
        pass

    return result


def _decimals(text: str) -> int:
    if "." in text:
        return len(text.split(".", 1)[1])
    return 0


def _value_in_cell(value: str, cell_text: str) -> bool:
    """The recorded component value must be recoverable from the raw cell:
    verbatim (comma→dot, spaces stripped) or by re-scanning the cell under
    either document decimal style."""

    normalized = normalize_for_scan(cell_text).replace(",", ".").replace(" ", "")
    if value in normalized:
        return True
    target = Decimal(value)
    for style in ("comma", "dot", None):
        for span in scan_text(cell_text, style).spans:
            if span.value is not None and span.value == target:
                return True
    return False
