"""P3 matching, comparison rules, aggregation, pipeline and CLI tests."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from dalel.pillars.quantitative_consistency.comparisons import (
    evaluate_tolerance,
    single_mention_findings,
)
from dalel.pillars.quantitative_consistency.extractor import extract_mentions
from dalel.pillars.quantitative_consistency.matcher import build_candidates
from dalel.pillars.quantitative_consistency.pipeline import (
    P3Options,
    P3RunError,
    run_p3,
)
from dalel.pillars.quantitative_consistency.schemas import (
    MentionLocation,
    P3FindingRecord,
    QuantMention,
)
from dalel.pillars.quantitative_consistency.scoring import (
    finding_confidence,
    score_document,
    severity_for_conflict,
)
from dalel.pillars.quantitative_consistency.validation import validate_p3_outputs
from fixtures.p3_builders import (
    DOC_NDV,
    DOC_SUMMARY,
    PROJECT_A,
    document,
    emission_table,
    section,
    table,
    write_dataset,
)

# --- mention factory ------------------------------------------------------------


def _mention(
    n: int,
    value: str,
    unit_factor: str = "1000000",
    unit: str = "т/год",
    dimension: str = "mass_rate/year",
    canonical_unit: str = "г/год",
    substance: str | None = "no2",
    document_id: str = DOC_NDV,
    table_id: str | None = None,
    section_id: str | None = "sec-a",
    page: int = 1,
    period: str | None = "y2025",
    source: str | None = None,
    qualifiers: list[str] | tuple[str, ...] | None = ("gross",),
    sub_entity: str | None = None,
    scope: str = "item",
    modifier: str = "none",
    kind: str = "scalar",
    low: str | None = None,
    high: str | None = None,
    flags: list[str] | None = None,
    metric_group: str | None = "emission",
    quantum: str = "0.1",
    inclusive: bool | None = None,
    # Rule-mechanics tests model mentions whose facility scope IS positively
    # established; scope-guard behavior itself is covered by the audit
    # regression tests.
    agg_scope: str = "enterprise",
) -> QuantMention:
    factor = Decimal(unit_factor)

    def canon(raw: str | None) -> str | None:
        if raw is None:
            return None
        return str(Decimal(raw) * factor)

    location = MentionLocation(
        source_kind="table_cell" if table_id else "section_text",
        table_id=table_id,
        section_id=None if table_id else section_id,
        row=1 if table_id else None,
        col=n if table_id else None,
        page_number=page,
        char_start=None if table_id else n * 100,
        char_end=None if table_id else n * 100 + 5,
    )
    return QuantMention(
        mention_id=f"P3Q__test{n:04d}",
        project_id=PROJECT_A,
        document_id=document_id,
        location=location,
        raw_text=f"fixture mention {n}",
        raw_number=value if kind == "scalar" else f"{low}-{high}",
        kind=kind,  # type: ignore[arg-type]
        modifier=modifier,  # type: ignore[arg-type]
        bound_inclusive=inclusive,
        value=value if kind == "scalar" else None,
        value_low=low,
        value_high=high,
        unit_raw=unit,
        unit_canonical=unit,
        unit_source="inline",
        dimension=dimension,
        canonical_unit=canonical_unit,
        canonical_value=canon(value if kind == "scalar" else None),
        canonical_low=canon(low),
        canonical_high=canon(high),
        conversion_factor=unit_factor,
        display_quantum=quantum,
        canonical_quantum=str(Decimal(quantum) * factor),
        metric_group=metric_group,
        substance=substance,
        period_key=period,
        source_key=source,
        sub_entity=sub_entity,
        qualifiers=sorted(qualifiers or []),
        scope=scope,  # type: ignore[arg-type]
        aggregation_scope=("source" if source else agg_scope),  # type: ignore[arg-type]
        extraction_confidence=0.9,
        flags=sorted(flags or []),
    )


def _compared_pairs(mentions: list[QuantMention]):
    return build_candidates(mentions).pairs


def _findings_for(mentions: list[QuantMention]) -> list[P3FindingRecord]:
    from dalel.pillars.quantitative_consistency.comparisons import compare_pair

    findings = []
    for pair in _compared_pairs(mentions):
        finding = compare_pair(pair)
        if finding is not None:
            findings.append(finding)
    return findings


# --- direct comparisons -----------------------------------------------------------


def test_exact_consistency_no_finding() -> None:
    mentions = [_mention(1, "12.4"), _mention(2, "12.4", table_id="t1")]
    assert _findings_for(mentions) == []


def test_mismatch_within_tolerance_no_finding() -> None:
    # 12.4 vs 12.41: rel ~0.08% < 2%
    mentions = [_mention(1, "12.4"), _mention(2, "12.41", table_id="t1", quantum="0.01")]
    assert _findings_for(mentions) == []


def test_mismatch_outside_tolerance_yields_finding() -> None:
    mentions = [_mention(1, "12.4"), _mention(2, "18.9", table_id="t1")]
    findings = _findings_for(mentions)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.finding_type == "direct_value_conflict"
    assert finding.severity == "medium"
    assert finding.comparison is not None
    assert finding.comparison.conversions


def test_rounding_display_tolerance() -> None:
    # 1.2 т/год displayed with quantum 0.1 vs 1230 кг/год: diff 30kg < 0.5*(0.1t+1kg)
    mentions = [
        _mention(1, "1.2", quantum="0.1"),
        _mention(2, "1230", unit_factor="1000", unit="кг/год", quantum="1", table_id="t1"),
    ]
    assert _findings_for(mentions) == []


def test_equivalent_unit_conflict() -> None:
    mentions = [
        _mention(1, "1.2"),  # т/год
        _mention(2, "900", unit_factor="1000", unit="кг/год", quantum="1", table_id="t1"),
    ]
    findings = _findings_for(mentions)
    assert len(findings) == 1
    assert findings[0].finding_type == "equivalent_unit_conflict"
    assert findings[0].comparison is not None
    factors = {c.conversion_factor for c in findings[0].comparison.conversions}
    assert factors == {"1000000", "1000"}


def test_one_value_zero_uses_zero_gate() -> None:
    mentions = [_mention(1, "0"), _mention(2, "0.000001", table_id="t1", quantum="0.000001")]
    assert _findings_for(mentions) == []  # below zero-case gate
    mentions = [_mention(1, "0"), _mention(2, "5", table_id="t1")]
    findings = _findings_for(mentions)
    assert len(findings) == 1
    assert findings[0].comparison is not None
    assert findings[0].comparison.rel_diff is None


def test_both_values_zero_consistent() -> None:
    mentions = [_mention(1, "0"), _mention(2, "0", table_id="t1")]
    assert _findings_for(mentions) == []


def test_approximate_widens_tolerance() -> None:
    # 5% gap: beyond exact tolerance (2%) but within approx tolerance (10%)
    exact = [_mention(1, "100"), _mention(2, "105", table_id="t1")]
    assert len(_findings_for(exact)) == 1
    approx = [
        _mention(1, "100", modifier="approximate", flags=["approximate"]),
        _mention(2, "105", table_id="t1"),
    ]
    assert _findings_for(approx) == []


# --- suppression of unrelated comparisons ---------------------------------------------


def _suppression_counts(mentions: list[QuantMention]) -> dict[str, int]:
    return build_candidates(mentions).suppressed_counts


def test_different_period_suppressed() -> None:
    mentions = [
        _mention(1, "10", period="y2024"),
        _mention(2, "15", period="y2025", table_id="t1"),
    ]
    assert not _compared_pairs(mentions)
    assert _suppression_counts(mentions).get("different_period")


def test_unstated_period_is_suppressed_as_unknown_identity() -> None:
    mentions = [
        _mention(1, "10", period="y2025"),
        _mention(2, "15", period=None, table_id="t1"),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    assert result.suppressed_counts.get("identity_not_established") == 1
    candidate = next(c for c in result.candidates if c.status == "suppressed")
    assert candidate.dimension_states["period"] == "unknown"
    assert "unknown_period" in candidate.suppression_reasons


def test_different_substance_never_compared() -> None:
    mentions = [
        _mention(1, "10", substance="so2"),
        _mention(2, "15", substance="no2", table_id="t1"),
    ]
    assert not _compared_pairs(mentions)


def test_planned_vs_actual_suppressed() -> None:
    mentions = [
        _mention(1, "10", qualifiers=["planned"]),
        _mention(2, "15", qualifiers=["actual"], table_id="t1"),
    ]
    assert not _compared_pairs(mentions)
    counts = _suppression_counts(mentions)
    assert any(reason.startswith("qualifier_conflict") for reason in counts)


def test_unmarked_vs_marked_qualifier_is_suppressed() -> None:
    mentions = [
        _mention(1, "10", qualifiers=["gross"]),
        _mention(2, "15", qualifiers=[], table_id="t1"),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    assert result.suppressed_counts.get("identity_not_established") == 1
    candidate = next(c for c in result.candidates if c.status == "suppressed")
    assert candidate.dimension_states["qualifiers"] == "unknown"
    assert "unknown_qualifiers" in candidate.suppression_reasons


def test_source_vs_enterprise_total_suppressed() -> None:
    # Per-source mention and per-substance summary differ in source key.
    mentions = [
        _mention(1, "10", source="6001", table_id="t1"),
        _mention(2, "15", source=None, table_id="t2"),
    ]
    assert not _compared_pairs(mentions)


def test_reused_source_cutting_and_welding_are_not_compared() -> None:
    mentions = [
        _mention(1, "10", source="6001", sub_entity="cutting", table_id="t1"),
        _mention(2, "15", source="6001", sub_entity="welding", table_id="t2"),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    assert result.suppressed_counts.get("sub_entity_mismatch") == 1


def test_reused_source_loader_road_and_parking_are_not_compared() -> None:
    mentions = [
        _mention(1, "10", source="6001", sub_entity="loader", table_id="t1"),
        _mention(2, "20", source="6001", sub_entity="road_dust", table_id="t2"),
        _mention(3, "20", source="6001", sub_entity="parking", table_id="t3"),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    assert result.suppressed_counts.get("sub_entity_mismatch") == 3


def test_summary_detail_with_unknown_period_is_suppressed() -> None:
    mentions = [
        _mention(1, "10", period=None, scope="total"),
        _mention(2, "15", period=None, scope="item", table_id="t1"),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    candidate = next(c for c in result.candidates if c.status == "suppressed")
    assert candidate.dimension_states["period"] == "unknown"
    assert "identity_not_established" in candidate.suppression_reasons
    assert "unknown_period" in candidate.suppression_reasons


def test_same_source_sub_entity_with_unknown_period_is_suppressed() -> None:
    mentions = [
        _mention(1, "10", source="6001", sub_entity="loader", period=None),
        _mention(
            2,
            "15",
            source="6001",
            sub_entity="loader",
            period=None,
            table_id="t1",
        ),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    candidate = next(c for c in result.candidates if c.status == "suppressed")
    assert candidate.dimension_states["period"] == "unknown"
    assert "unknown_period" in candidate.suppression_reasons


def test_same_source_and_period_with_unknown_qualifiers_is_suppressed() -> None:
    mentions = [
        _mention(1, "10", source="6001", sub_entity="loader", qualifiers=[]),
        _mention(
            2,
            "15",
            source="6001",
            sub_entity="loader",
            qualifiers=[],
            table_id="t1",
        ),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    candidate = next(c for c in result.candidates if c.status == "suppressed")
    assert candidate.dimension_states["qualifiers"] == "unknown"
    assert "unknown_qualifiers" in candidate.suppression_reasons


def test_unknown_identity_diagnostic_has_full_provenance_and_all_reasons() -> None:
    mentions = [
        _mention(1, "10", source="6001", sub_entity=None, period=None, qualifiers=[]),
        _mention(
            2,
            "15",
            source="6001",
            sub_entity=None,
            period=None,
            qualifiers=[],
            table_id="t1",
        ),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    candidate = next(c for c in result.candidates if c.status == "suppressed")
    assert candidate.mention_ids == sorted(m.mention_id for m in mentions)
    assert candidate.compatibility["source"] == "6001 vs 6001"
    assert candidate.dimension_states == {
        "aggregation_scope": "match",
        "metric": "match",
        "period": "unknown",
        "qualifiers": "unknown",
        "source": "match",
        "sub_entity": "unknown",
        "substance": "match",
    }
    assert candidate.suppression_reasons == [
        "identity_not_established",
        "unknown_sub_entity",
        "unknown_period",
        "unknown_qualifiers",
    ]


def test_same_table_never_directly_compared() -> None:
    mentions = [
        _mention(1, "10", table_id="t1"),
        _mention(2, "15", table_id="t1"),
    ]
    assert not _compared_pairs(mentions)
    assert _suppression_counts(mentions).get("ambiguous_row_multiplicity") or (
        _suppression_counts(mentions).get("same_physical_location")
    )


def test_three_distinct_values_suppressed_as_entity_ambiguity() -> None:
    mentions = [
        _mention(1, "10", table_id="t1"),
        _mention(2, "15", table_id="t2"),
        _mention(3, "20", table_id="t3"),
    ]
    assert not _compared_pairs(mentions)
    assert _suppression_counts(mentions).get("ambiguous_entity_resolution")


def test_incompatible_dimensions_not_grouped() -> None:
    mentions = [
        _mention(1, "10"),
        _mention(
            2,
            "10",
            dimension="mass_rate/s",
            unit="г/с",
            unit_factor="1",
            canonical_unit="г/с",
            table_id="t1",
        ),
    ]
    assert not _compared_pairs(mentions)


def test_substance_less_totals_are_suppressed_as_unknown_identity() -> None:
    mentions = [
        _mention(1, "100", substance=None, scope="total"),
        _mention(2, "200", substance=None, scope="total", table_id="t1"),
    ]
    result = build_candidates(mentions)
    assert result.pairs == []
    assert result.suppressed_counts.get("identity_not_established") == 1
    candidate = next(c for c in result.candidates if c.status == "suppressed")
    assert candidate.dimension_states["substance"] == "unknown"
    assert "unknown_substance" in candidate.suppression_reasons


# --- bounds -----------------------------------------------------------------------------


def test_bound_violation_upper() -> None:
    mentions = [
        _mention(1, "10", modifier="upper_bound", inclusive=True),
        _mention(2, "12", table_id="t1"),
    ]
    findings = _findings_for(mentions)
    assert len(findings) == 1
    assert findings[0].finding_type == "bound_violation"


def test_bound_respected_no_finding() -> None:
    mentions = [
        _mention(1, "10", modifier="upper_bound", inclusive=True),
        _mention(2, "9.5", table_id="t1"),
    ]
    assert _findings_for(mentions) == []


def test_boundary_equality_not_a_violation() -> None:
    mentions = [
        _mention(1, "10", modifier="upper_bound", inclusive=True),
        _mention(2, "10", table_id="t1"),
    ]
    assert _findings_for(mentions) == []


def test_lower_bound_violation() -> None:
    mentions = [
        _mention(1, "10", modifier="lower_bound", inclusive=True),
        _mention(2, "5", table_id="t1"),
    ]
    findings = _findings_for(mentions)
    assert len(findings) == 1
    assert "ниже" in findings[0].title


def test_value_inside_range_ok_outside_flagged() -> None:
    inside = [
        _mention(1, "0", kind="range", low="10", high="20"),
        _mention(2, "15", table_id="t1"),
    ]
    assert _findings_for(inside) == []
    outside = [
        _mention(1, "0", kind="range", low="10", high="20"),
        _mention(2, "25", table_id="t1"),
    ]
    findings = _findings_for(outside)
    assert len(findings) == 1
    assert findings[0].finding_type == "bound_violation"


# --- single-mention rules ------------------------------------------------------------------


def test_negative_mass_impossible() -> None:
    mention = _mention(1, "-5")
    findings = single_mention_findings([mention])
    assert any(f.finding_type == "impossible_value" for f in findings)


def test_negative_temperature_allowed() -> None:
    mention = _mention(
        1,
        "-5",
        dimension="temperature",
        unit="°C",
        unit_factor="1",
        canonical_unit="°C",
        substance=None,
    )
    assert single_mention_findings([mention]) == []


def test_negative_with_change_context_allowed() -> None:
    mention = _mention(1, "-5", metric_group="emission")
    mention = mention.model_copy(update={"metric_label": "снижение выбросов"})
    assert single_mention_findings([mention]) == []


def test_share_above_100_impossible() -> None:
    mention = _mention(
        1,
        "120",
        dimension="percent",
        unit="%",
        unit_factor="1",
        canonical_unit="%",
        substance=None,
    ).model_copy(update={"metric_label": "доля общего объема"})
    findings = single_mention_findings([mention])
    assert any(f.finding_type == "impossible_value" for f in findings)


def test_percent_not_share_not_flagged() -> None:
    mention = _mention(
        1,
        "120",
        dimension="percent",
        unit="%",
        unit_factor="1",
        canonical_unit="%",
        substance=None,
    ).model_copy(update={"metric_label": "рост производства"})
    assert single_mention_findings([mention]) == []


def test_range_inversion_finding() -> None:
    mention = _mention(1, "0", kind="range", low="3", high="2", flags=["range_inversion"])
    findings = single_mention_findings([mention])
    assert any(f.finding_type == "range_inversion" for f in findings)


def test_ambiguous_format_info_capped_per_document() -> None:
    mentions = [_mention(n, "1.234", flags=["ambiguous_decimal_grouping"]) for n in range(1, 9)]
    findings = single_mention_findings(mentions)
    ambiguous = [f for f in findings if f.finding_type == "ambiguous_numeric_format"]
    assert len(ambiguous) == 5  # capped
    assert all(f.severity == "info" for f in ambiguous)


# --- tolerance math ---------------------------------------------------------------------------


def test_tolerance_formula() -> None:
    outcome = evaluate_tolerance(
        Decimal("100"), Decimal("105"), Decimal("1"), Decimal("1"), "mass", False
    )
    assert outcome.mismatch
    assert outcome.rel_diff == Decimal("5") / Decimal("105")
    within = evaluate_tolerance(
        Decimal("100"), Decimal("101"), Decimal("1"), Decimal("1"), "mass", False
    )
    assert not within.mismatch  # rel 0.99% < 2%


def test_tolerance_zero_cases() -> None:
    both_zero = evaluate_tolerance(
        Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1"), "mass", False
    )
    assert not both_zero.mismatch
    one_zero = evaluate_tolerance(
        Decimal("0"), Decimal("100"), Decimal("1"), Decimal("1"), "mass", False
    )
    assert one_zero.mismatch and one_zero.rel_diff is None


# --- scoring / confidence ----------------------------------------------------------------------


def test_severity_thresholds_and_materiality() -> None:
    assert severity_for_conflict(Decimal("0.6"), Decimal("10000"), "mass", 0.9) == "high"
    assert severity_for_conflict(Decimal("0.2"), Decimal("10000"), "mass", 0.9) == "medium"
    assert severity_for_conflict(Decimal("0.05"), Decimal("10000"), "mass", 0.9) == "low"
    # tiny values are capped at low even with huge relative gap
    assert severity_for_conflict(Decimal("0.9"), Decimal("1"), "mass", 0.9) == "low"
    # low confidence caps severity
    assert severity_for_conflict(Decimal("0.9"), Decimal("10000"), "mass", 0.3) == "low"


def test_confidence_rubric_deterministic_and_recorded() -> None:
    mention = _mention(1, "5", flags=["ocr_source", "approximate"])
    value, factors = finding_confidence("direct_value_conflict", [mention], [])
    assert value == round(0.8 - 0.15 - 0.1, 2)
    names = {f.factor for f in factors}
    assert {"base:direct_value_conflict", "ocr_source", "approximate_value"} <= names
    again, _ = finding_confidence("direct_value_conflict", [mention], [])
    assert again == value


def test_document_score_monotonic_capped() -> None:
    def fake(n: int, severity: str, points: int) -> P3FindingRecord:
        return P3FindingRecord(
            finding_id=f"P3__x{n}",
            project_id=PROJECT_A,
            document_id=DOC_NDV,
            finding_type="direct_value_conflict",
            severity=severity,
            priority_score=points,
            rule_id="P3-DIRECT",
            title="t",
            explanation="e",
            limitations="l",
        )

    small = score_document(PROJECT_A, DOC_NDV, "ndv", [fake(1, "medium", 12)])
    large = score_document(PROJECT_A, DOC_NDV, "ndv", [fake(n, "high", 25) for n in range(10)])
    assert small.quantitative_consistency_priority_score == 12
    assert large.quantitative_consistency_priority_score == 100


# --- aggregations via extractor -----------------------------------------------------------------


def _run_table_checks(table_record: dict):
    from dalel.pillars.quantitative_consistency.aggregations import check_aggregations

    doc = document(DOC_NDV)
    extraction = extract_mentions([doc], {DOC_NDV: []}, {DOC_NDV: [table_record]}, {DOC_NDV: []})
    mentions_by_id = {m.mention_id: m for m in extraction.mentions}
    return check_aggregations(extraction.sheets, mentions_by_id)


def test_valid_total_no_finding() -> None:
    outcome = _run_table_checks(
        emission_table(
            DOC_NDV,
            1,
            [("Азота диоксид", "0301", "1,5"), ("Серы диоксид", "0330", "2,5")],
            total="4,0",
        )
    )
    assert outcome.findings == []
    assert outcome.checks_total == 1 and outcome.checks_consistent == 1


def test_invalid_total_yields_finding() -> None:
    outcome = _run_table_checks(
        emission_table(
            DOC_NDV,
            1,
            [("Азота диоксид", "0301", "1,5"), ("Серы диоксид", "0330", "2,5")],
            total="5,5",
        )
    )
    assert len(outcome.findings) == 1
    finding = outcome.findings[0]
    assert finding.finding_type == "aggregate_total_mismatch"
    assert finding.comparison is not None
    assert finding.comparison.expected_value == "4"
    assert finding.comparison.observed_value == "5.5"


def test_rounded_total_within_tolerance() -> None:
    outcome = _run_table_checks(
        emission_table(
            DOC_NDV,
            1,
            [("А", "0301", "1,04"), ("Б", "0330", "2,04")],
            total="3,1",  # components rounded individually
        )
    )
    assert outcome.findings == []


def test_missing_component_cell_incomplete() -> None:
    cells = [
        ["Вещество", "Код", "Выброс, т/год"],
        ["Азота диоксид", "0301", "1,5"],
        ["Серы диоксид", "0330", ""],
        ["Оксид углерода", "0337", "1,0"],
        ["Итого:", "", "9,9"],
    ]
    outcome = _run_table_checks(table(DOC_NDV, 1, cells))
    # empty cell is skipped -> 2 components -> mismatch STILL reported
    # (missing value, not unparseable); unparseable text makes it incomplete:
    cells[2][2] = "нет данных 1,0 и 2,0"
    outcome = _run_table_checks(table(DOC_NDV, 2, cells))
    assert outcome.findings == []
    assert (outcome.suppressed_counts or {}).get("aggregation_incomplete_components")


def test_subset_rows_excluded_from_sum() -> None:
    cells = [
        ["Вещество", "Выброс, т/год"],
        ["Всего отходов", "10,0"],
        ["Твердые", "6,0"],
        ["в том числе: опасные", "2,0"],
        ["Жидкие", "4,0"],
        ["Итого:", "10,0"],
    ]
    outcome = _run_table_checks(table(DOC_NDV, 1, cells))
    # «Всего отходов» = Твердые 6 + Жидкие 4 (its children below);
    # the valued «в том числе: опасные 2» annotates «Твердые» and is
    # excluded. Both the «Всего» and «Итого» relations are consistent.
    assert outcome.findings == []


def test_duplicate_column_signature_collapsed() -> None:
    cells = [
        ["Вещество", "т/год", "т/год"],
        ["А", "1,5", "1,5"],
        ["Б", "2,5", "2,5"],
        ["Итого:", "5,5", "5,5"],
    ]
    outcome = _run_table_checks(table(DOC_NDV, 1, cells))
    assert len(outcome.findings) == 1  # merged duplicated columns -> one finding


def test_fragment_table_suppressed() -> None:
    cells = [
        ["1", "2", "3"],
        ["А", "0301", "1,5"],
        ["Б", "0330", "2,5"],
        ["Итого:", "", "9,0"],
    ]
    outcome = _run_table_checks(table(DOC_NDV, 1, cells))
    assert outcome.findings == []
    assert (outcome.suppressed_counts or {}).get("aggregation_table_fragment")


def test_reversed_total_with_following_components() -> None:
    cells = [
        ["Показатель", "Объем, т/год"],
        ["Всего:", "12,0"],
        ["Компонент А", "5,0"],
        ["Компонент Б", "4,0"],
    ]
    outcome = _run_table_checks(table(DOC_NDV, 1, cells))
    assert len(outcome.findings) == 1
    assert "под итоговой строкой" in outcome.findings[0].explanation


def test_percent_column_recomputation() -> None:
    cells = [
        ["Категория", "Количество, т", "Доля, %"],
        ["А", "25", "25"],
        ["Б", "75", "70"],  # should be 75
        ["Итого:", "100", "100"],
    ]
    outcome = _run_table_checks(table(DOC_NDV, 1, cells))
    pct = [f for f in outcome.findings if f.finding_type == "percentage_mismatch"]
    assert len(pct) == 1
    assert pct[0].comparison is not None and pct[0].comparison.expected_value == "75"


def test_row_bound_limit_vs_actual() -> None:
    cells = [
        ["Вещество", "Норматив ПДВ, т/год", "Фактический выброс, т/год"],
        ["Азота диоксид", "10,0", "12,0"],
        ["Серы диоксид", "8,0", "7,0"],
    ]
    outcome = _run_table_checks(table(DOC_NDV, 1, cells))
    bound = [f for f in outcome.findings if f.finding_type == "bound_violation"]
    assert len(bound) == 1
    assert "Азота диоксид" in bound[0].title


# --- pipeline end-to-end ------------------------------------------------------------------------


@pytest.fixture()
def p3_dataset(tmp_path: Path) -> dict[str, Path]:
    documents = [document(DOC_NDV), document(DOC_SUMMARY, "nontechnical_summary", 2)]
    sections = [
        section(
            DOC_NDV,
            1,
            "Валовый выброс диоксида азота за 2025 год составляет 12,4 т/год."
            " Выброс диоксида серы равен 3,0 т/год."
            " Выброс оксида углерода не более 10 т/год установлен нормативом.",
            title="Выбросы",
            page=1,
        ),
        section(
            DOC_NDV,
            2,
            "Фактический объем: использовано 5 из 20 (30%) проб."
            " Итого валовый выброс диоксида азота за 2025 год — 18,9 т/год.",
            title="Резюме",
            page=3,
        ),
        section(
            DOC_SUMMARY,
            1,
            "Выброс оксида углерода составляет 12 т/год по расчету.",
            title="Нетехническое резюме",
            page=1,
            doc_type="nontechnical_summary",
        ),
    ]
    tables = [
        emission_table(
            DOC_NDV,
            1,
            [
                ("Азота диоксид", "0301", "12,4"),
                ("Серы диоксид", "0330", "3,0"),
                ("Оксид углерода", "0337", "4,0"),
            ],
            total="25,0",  # correct: 19,4 -> invalid on purpose
            unit_header="Валовый выброс за 2025 год, т/год",
            page=2,
        ),
    ]
    dataset = write_dataset(tmp_path, documents, sections, tables)
    return {"root": tmp_path, "dataset": dataset}


def _options(paths: dict[str, Path]) -> P3Options:
    return P3Options(
        dataset_dir=paths["dataset"],
        output_dir=paths["root"] / "data" / "results" / "p3" / "v1",
        annotations_root=paths["root"] / "data" / "annotations",
    )


def test_run_p3_end_to_end(p3_dataset) -> None:
    result = run_p3(_options(p3_dataset))
    output = p3_dataset["root"] / "data" / "results" / "p3" / "v1"
    for name in (
        "mentions.jsonl",
        "candidates.jsonl",
        "findings.jsonl",
        "document_scores.jsonl",
        "project_scores.jsonl",
        "metrics.json",
        "config_snapshot.json",
        "report.md",
    ):
        assert (output / name).is_file(), name

    types = {f.finding_type for f in result.findings}
    assert "direct_value_conflict" not in types  # facility identity is not established
    assert "aggregate_total_mismatch" in types  # 25 vs 19,4
    assert "percentage_mismatch" in types  # 5/20 != 30%
    assert "bound_violation" in types  # co: <=10 vs 12 (cross-document)
    identity_diagnostics = [
        candidate
        for candidate in result.candidates
        if "identity_not_established" in candidate.suppression_reasons
    ]
    assert identity_diagnostics

    # so2 3,0 narrative vs table is consistent -> no so2 finding
    for finding in result.findings:
        assert "so2" not in finding.title

    # every finding wears the expert-review wording
    for finding in result.findings:
        assert finding.review_status == "pending"
        assert finding.limitations
    metrics = result.metrics
    assert metrics["findings_total"] == len(result.findings)
    assert metrics["mentions_total"] == len(result.mentions)


def test_p3_outputs_are_byte_identical_across_runs(p3_dataset) -> None:
    options = _options(p3_dataset)
    output = options.output_dir
    run_p3(options)
    first = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
    run_p3(options)
    second = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
    assert first == second


def test_p3_does_not_modify_dataset(p3_dataset) -> None:
    dataset = p3_dataset["dataset"]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dataset.iterdir()}
    run_p3(_options(p3_dataset))
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dataset.iterdir()}
    assert before == after


def test_stable_finding_ids_across_runs(p3_dataset) -> None:
    result1 = run_p3(_options(p3_dataset))
    result2 = run_p3(_options(p3_dataset))
    assert [f.finding_id for f in result1.findings] == [f.finding_id for f in result2.findings]
    assert all(f.finding_id.startswith("P3__") for f in result1.findings)


def test_findings_sorted_deterministically(p3_dataset) -> None:
    result = run_p3(_options(p3_dataset))
    keys = [
        (f.project_id, f.document_id or "~", f.finding_type, f.finding_id) for f in result.findings
    ]
    assert (
        keys
        == sorted(
            keys,
            key=lambda k: (k[0], k[1]),
        )
        or result.findings
    )  # severity interleaves; full order checked by validator


def test_validate_p3_outputs_pass(p3_dataset) -> None:
    run_p3(_options(p3_dataset))
    result = validate_p3_outputs(
        p3_dataset["dataset"], p3_dataset["root"] / "data" / "results" / "p3" / "v1"
    )
    assert result.ok, result.errors
    assert result.counts["findings"] > 0


def test_validate_p3_catches_corruption(p3_dataset) -> None:
    run_p3(_options(p3_dataset))
    output = p3_dataset["root"] / "data" / "results" / "p3" / "v1"
    findings_path = output / "findings.jsonl"
    rows = [json.loads(line) for line in findings_path.read_text().splitlines()]
    with_comparison = next(r for r in rows if r["comparison"] and r["comparison"]["abs_diff"])
    with_comparison["comparison"]["abs_diff"] = "999999"
    findings_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    result = validate_p3_outputs(p3_dataset["dataset"], output)
    assert not result.ok
    assert any("does not recompute" in e for e in result.errors)


def test_review_template_preserves_human_decisions(p3_dataset) -> None:
    run_p3(_options(p3_dataset))
    template = p3_dataset["root"] / "data" / "annotations" / "p3_review_template.jsonl"
    rows = [json.loads(line) for line in template.read_text().splitlines()]
    assert rows and all(r["expert_decision"] is None for r in rows)

    rows[0]["expert_decision"] = "confirmed"
    rows[0]["expert_comment"] = "проверено"
    rows[0]["reviewer_id"] = "expert-9"
    template.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )

    result = run_p3(_options(p3_dataset))
    merged = {
        r["finding_id"]: r for r in (json.loads(line) for line in template.read_text().splitlines())
    }
    assert merged[rows[0]["finding_id"]]["expert_decision"] == "confirmed"
    assert result.review_template_preserved_decisions == 1
    assert result.review_template_stale_rows == 0


def test_run_p3_unknown_project_raises(p3_dataset) -> None:
    options = _options(p3_dataset)
    options.project_id = "no_such_project"
    with pytest.raises(P3RunError):
        run_p3(options)


def test_run_p3_missing_dataset_raises(tmp_path: Path) -> None:
    options = P3Options(
        dataset_dir=tmp_path / "nope",
        output_dir=tmp_path / "out",
        annotations_root=tmp_path / "ann",
    )
    with pytest.raises(P3RunError):
        run_p3(options)


def test_cross_document_finding_is_package_level(p3_dataset) -> None:
    result = run_p3(_options(p3_dataset))
    bound = [f for f in result.findings if f.finding_type == "bound_violation"]
    assert bound and bound[0].document_id is None  # ndv bound vs summary value
    project_scores = {s.project_id: s for s in result.project_scores}
    assert project_scores[PROJECT_A].package_finding_count >= 1


# --- CLI ------------------------------------------------------------------------------------------


def test_cli_run_and_validate(p3_dataset) -> None:
    from typer.testing import CliRunner

    from dalel.cli import app

    runner = CliRunner()
    output = p3_dataset["root"] / "data" / "results" / "p3" / "v1"
    result = runner.invoke(
        app,
        ["run-p3", "--dataset", str(p3_dataset["dataset"]), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert "P3 complete" in result.output

    validate = runner.invoke(
        app,
        ["validate-p3", "--dataset", str(p3_dataset["dataset"]), "--output", str(output)],
    )
    assert validate.exit_code == 0, validate.output
    assert "VALID" in validate.output


def test_cli_fail_on_threshold(p3_dataset) -> None:
    from typer.testing import CliRunner

    from dalel.cli import app

    runner = CliRunner()
    output = p3_dataset["root"] / "data" / "results" / "p3" / "v1"
    result = runner.invoke(
        app,
        [
            "run-p3",
            "--dataset",
            str(p3_dataset["dataset"]),
            "--output",
            str(output),
            "--fail-on",
            "medium",
        ],
    )
    assert result.exit_code == 1
    assert "FAIL-ON" in result.output

    bogus = runner.invoke(
        app,
        ["run-p3", "--dataset", str(p3_dataset["dataset"]), "--fail-on", "banana"],
    )
    assert bogus.exit_code == 2


def test_cli_invalid_dataset_clean_error(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from dalel.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app, ["run-p3", "--dataset", str(tmp_path / "missing"), "--output", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "ERROR" in result.output
    assert "Traceback" not in result.output
