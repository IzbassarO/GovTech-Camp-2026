"""Regression tests for every defect from the independent Phase 1B audit.

Each test replicates the STRUCTURE of an audited production false positive
with small synthetic fixtures (no large production records are copied).
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from dalel.pillars.quantitative_consistency.extractor import extract_mentions
from dalel.pillars.quantitative_consistency.matcher import build_candidates
from dalel.pillars.quantitative_consistency.number_parser import scan_text
from dalel.pillars.quantitative_consistency.pipeline import (
    P3Options,
    P3RunError,
    run_p3,
)
from dalel.pillars.quantitative_consistency.units import (
    convert_to_canonical,
    lookup_unit,
    match_unit_after,
)
from fixtures.p3_builders import (
    DOC_NDV,
    DOC_SUMMARY,
    document,
    section,
    table,
    write_dataset,
)


def _extract(documents, sections_by_doc, tables_by_doc):
    pages_by_doc = {d["document_id"]: [] for d in documents}
    return extract_mentions(documents, sections_by_doc, tables_by_doc, pages_by_doc)


def _direct_pairs(extraction):
    result = build_candidates(extraction.mentions)
    return [p for p in result.pairs if p.rule == "direct"], result.suppressed_counts


_EMISSION_HEADER = ["Код", "Наименование ЗВ", "Выброс г/с", "Выброс т/год"]


def _mini_emission_table(doc_id, index, page, code, name, gs, ty):
    return table(
        doc_id,
        index,
        [_EMISSION_HEADER, [code, name, gs, ty]],
        page=page,
    )


# --- audit: bereke P3__791cbaad03cd — same-page source boundary ---------------------


def test_bereke_same_page_source_boundary_not_compared() -> None:
    """Two tables on p117: one closes source 6023's block, the next belongs
    to source 6024 whose heading starts ON p117. Attribution is ambiguous —
    the tables must not be compared."""
    doc = document(DOC_NDV, page_count=5)
    sections_by_doc = {
        DOC_NDV: [
            section(DOC_NDV, 1, "расчет", title="Склад зерна пшеницы - источник №6023", page=2),
            section(DOC_NDV, 2, "расчет", title="Размольное отделение - источник №6024", page=3),
        ]
    }
    tables_by_doc = {
        DOC_NDV: [
            _mini_emission_table(DOC_NDV, 1, 3, "2937", "Пыль зерновая", "0.0004", "0.0105"),
            _mini_emission_table(DOC_NDV, 2, 3, "2937", "Пыль зерновая", "0.66", "4.752"),
        ]
    }
    extraction = _extract([doc], sections_by_doc, tables_by_doc)
    table_mentions = [m for m in extraction.mentions if m.location.source_kind == "table_cell"]
    assert all(m.source_key is None for m in table_mentions), (
        "a source heading starting on the same page must not be assigned"
    )
    assert all(m.aggregation_scope == "unknown" for m in table_mentions)
    pairs, suppressed = _direct_pairs(extraction)
    assert pairs == []
    assert suppressed.get("scope_unresolved")


def test_interior_block_pages_still_attributed() -> None:
    """Pages strictly inside a source block keep positive attribution."""
    doc = document(DOC_NDV, page_count=6)
    sections_by_doc = {
        DOC_NDV: [
            section(DOC_NDV, 1, "расчет", title="Маслопресс - источник №0003", page=2),
            section(DOC_NDV, 2, "расчет", title="Склад №1 - источник №6004", page=5),
        ]
    }
    tables_by_doc = {
        DOC_NDV: [
            _mini_emission_table(DOC_NDV, 1, 3, "1301", "Акролеин", "0.01", "0.105"),
            _mini_emission_table(DOC_NDV, 2, 5, "1301", "Акролеин", "0.06", "0.630"),
        ]
    }
    extraction = _extract([doc], sections_by_doc, tables_by_doc)
    by_table = {
        m.location.table_id: m
        for m in extraction.mentions
        if m.location.source_kind == "table_cell" and m.unit_canonical == "г/с"
    }
    interior = by_table[f"{DOC_NDV}__tab_0001"]
    boundary = by_table[f"{DOC_NDV}__tab_0002"]
    assert interior.source_key == "0003"  # page 3 is strictly inside the block
    assert interior.aggregation_scope == "source"
    assert boundary.source_key is None  # heading page 5 is a boundary page
    pairs, _ = _direct_pairs(extraction)
    assert pairs == []  # source vs unknown must not compare


# --- audit: azm P3__3961862cf52d — unknown-vs-unknown table pairs --------------------


def test_unknown_scope_tables_never_compared() -> None:
    doc = document(DOC_NDV, page_count=5)
    tables_by_doc = {
        DOC_NDV: [
            _mini_emission_table(DOC_NDV, 1, 2, "2902", "Взвешенные частицы", "0.0275", "0.2475"),
            _mini_emission_table(DOC_NDV, 2, 4, "2902", "Взвешенные частицы", "0.0014", "0.001008"),
        ]
    }
    extraction = _extract([doc], {DOC_NDV: []}, tables_by_doc)
    pairs, suppressed = _direct_pairs(extraction)
    assert pairs == []
    assert suppressed.get("scope_unresolved")


# --- audit: sintez P3__741d…/P3__21a4… — scope mismatch --------------------------------


def _inventory_table(doc_id, index, page, gs_value):
    return table(
        doc_id,
        index,
        [
            ["Код ЗВ", "Наименование", "Выброс вещества с учетом очистки, г/с"],
            ["0337", "Углерод оксид", gs_value],
        ],
        page=page,
    )


def test_enterprise_inventory_vs_unknown_table_suppressed() -> None:
    doc = document(DOC_NDV, page_count=6)
    sections_by_doc = {
        DOC_NDV: [
            section(
                DOC_NDV,
                1,
                "перечень",
                title="Перечень загрязняющих веществ, выбрасываемых в атмосферу",
                page=5,
            ),
        ]
    }
    tables_by_doc = {
        DOC_NDV: [
            _mini_emission_table(DOC_NDV, 1, 2, "0337", "Углерод оксид", "0.0512", "1.6"),
            _inventory_table(DOC_NDV, 2, 5, "1.0462"),
        ]
    }
    extraction = _extract([doc], sections_by_doc, tables_by_doc)
    scopes = {
        m.location.table_id: m.aggregation_scope
        for m in extraction.mentions
        if m.location.source_kind == "table_cell" and m.substance == "co"
    }
    assert scopes[f"{DOC_NDV}__tab_0002"] == "enterprise"
    assert scopes[f"{DOC_NDV}__tab_0001"] == "unknown"
    pairs, suppressed = _direct_pairs(extraction)
    assert pairs == []
    assert suppressed.get("scope_unresolved") or suppressed.get("scope_mismatch")


def test_cross_document_scope_mismatch_suppressed() -> None:
    doc_a = document(DOC_NDV, page_count=3)
    doc_b = document(DOC_SUMMARY, "nontechnical_summary", page_count=3)
    sections = {
        DOC_NDV: [
            section(DOC_NDV, 1, "перечень", title="Перечень загрязняющих веществ", page=1),
        ],
        DOC_SUMMARY: [],
    }
    tables = {
        DOC_NDV: [_inventory_table(DOC_NDV, 1, 1, "1.0462")],
        DOC_SUMMARY: [
            _mini_emission_table(DOC_SUMMARY, 1, 2, "0337", "Углерод оксид", "0.0512", "1.6"),
        ],
    }
    extraction = _extract([doc_a, doc_b], sections, tables)
    pairs, _ = _direct_pairs(extraction)
    assert pairs == []


# --- audit: P3__0e480bc2eaa7 / P3__131ae2284c80 — subtotal double counting --------------


_WASTE_GRID = [
    ["Наименование отходов", "Объем", "Лимит накопления, тонн/год"],
    ["Всего:", "-", "69,625"],
    ["в том числе отходов производства", "-", "67"],
    ["отходов потребления", "-", "2,625"],
    ["Опасные отходы", "", ""],
    ["Бумажная тара (150)", "-", "0,9"],
    ["Металлическая упаковка (150)", "-", "5"],
    ["Водные жидкие отходы (161001*)", "-", "60"],
    ["Абсорбенты, фильтры (150202*)", "-", "1"],
    ["Неопасные отходы", "", ""],
    ["Твердо-бытовые отходы (200399)", "-", "2,625"],
    ["Отходы СИЗ (200110)", "-", "0,1"],
]


def _run_aggregation(table_records, doc_ids=None):
    from dalel.pillars.quantitative_consistency.aggregations import check_aggregations

    doc_ids = doc_ids or [DOC_NDV]
    docs = [document(d, page_count=3) for d in doc_ids]
    tables_by_doc = {}
    for record in table_records:
        tables_by_doc.setdefault(record["provenance"]["document_id"], []).append(record)
    extraction = _extract(docs, {d: [] for d in doc_ids}, tables_by_doc)
    mentions_by_id = {m.mention_id: m for m in extraction.mentions}
    return check_aggregations(extraction.sheets, mentions_by_id)


def test_waste_table_subtotal_enumeration_not_double_counted() -> None:
    """0.9+5+60+1+2.625+0.1 = 69.625: the «в том числе»-enumeration rows
    (67 and 2.625) must not be added on top of the detail rows."""
    outcome = _run_aggregation([table(DOC_NDV, 1, _WASTE_GRID, page=2)])
    assert outcome.findings == []
    assert outcome.checks_consistent >= 1


def test_waste_table_real_mismatch_still_detected() -> None:
    grid = [row[:] for row in _WASTE_GRID]
    grid[1] = ["Всего:", "-", "80,0"]  # stated total genuinely wrong
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert len(outcome.findings) == 1
    assert outcome.findings[0].comparison is not None
    assert outcome.findings[0].comparison.expected_value == "69.625"


def test_duplicated_table_copies_collapse_to_one_finding() -> None:
    """Identical table copies in two documents are one representation."""
    grid = [row[:] for row in _WASTE_GRID]
    grid[1] = ["Всего:", "-", "80,0"]
    records = [
        table(DOC_NDV, 1, grid, page=2),
        table(DOC_SUMMARY, 1, grid, page=4, doc_type="nontechnical_summary"),
    ]
    outcome = _run_aggregation(records, doc_ids=[DOC_NDV, DOC_SUMMARY])
    findings = outcome.findings
    assert len(findings) == 1, [f.finding_id for f in findings]
    assert "коп" in findings[0].explanation.casefold()  # copies noted


def test_overlap_resolution_requires_exact_match() -> None:
    """Production FP shape: a coarse row («0,1») must NOT be treated as a
    subtotal of following rows just because display quanta open a wide
    tolerance window — the table below is exactly consistent."""
    grid = [
        ["Номер источника", "Наименование", "г/с"],
        ["6001", "(2908) Пыль неорганическая", "0.0024"],
        ["6002", "(2908) Пыль неорганическая", "0.1"],
        ["6003", "(2908) Пыль неорганическая", "0.001575"],
        ["6004", "(2908) Пыль неорганическая", "0.000562"],
        ["6005", "(2908) Пыль неорганическая", "0.00609"],
        ["6006", "(2908) Пыль неорганическая", "0.0181"],
        ["6007", "(2908) Пыль неорганическая", "0.02625"],
        ["Всего:", "", "0.154977"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []
    assert outcome.checks_consistent >= 1


def test_exact_subtotal_overlap_still_resolved() -> None:
    """A STRUCTURALLY LABELED nested subtotal is excluded from the grand
    total; per the second audit, numerical equality alone is never
    hierarchy evidence, so the subtotal must be labeled («Подытог…») and
    its children introduced by «в том числе»."""
    grid = [
        ["Наименование", "т/год"],
        ["Категория А", "10"],
        ["Подытог Б:", "2,625"],
        ["в том числе:", ""],
        ["Деталь Б1", "2,5"],
        ["Деталь Б2", "0,125"],
        ["Итого:", "12,625"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []  # 10 + 2.625 = 12.625 (details not double counted)
    assert outcome.checks_consistent >= 2  # subtotal check + grand check


def test_aggregation_findings_carry_complete_conversion_evidence() -> None:
    grid = [row[:] for row in _WASTE_GRID]
    grid[1] = ["Всего:", "-", "80,0"]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    comparison = outcome.findings[0].comparison
    assert comparison is not None and comparison.conversions
    for conversion in comparison.conversions:
        assert conversion.parsed_value
        assert conversion.conversion_factor is not None
        assert conversion.canonical_value is not None
        assert conversion.canonical_unit is not None
    assert comparison.aggregation is not None
    included = [c for c in comparison.aggregation.components if c.included]
    # «Всего: 80» is checked against its own «в том числе» children
    # (67 + 2,625 = 69,625) — the enumeration IS the breakdown.
    assert {c.value for c in included} == {"67", "2.625"}


# --- audit: P3__f5134ca75118 — dash classification ---------------------------------------


def test_dash_after_parenthesis_is_separator_not_sign() -> None:
    result = scan_text("УОНИ 13/55 (аналог Э42) -0,3 кг/год;")
    spans = [s for s in result.spans if s.unit is not None]
    assert len(spans) == 1
    assert spans[0].value == Decimal("0.3")  # positive


def test_equipment_name_dash_value_is_not_a_range() -> None:
    result = scan_text("Электросварка МР -3 -2,0 кг/год;")
    assert all(s.kind == "scalar" for s in result.spans)
    valued = [s for s in result.spans if s.unit is not None]
    assert len(valued) == 1 and valued[0].value == Decimal("2.0")
    assert not any("range_inversion" in s.flags for s in result.spans)


def test_genuine_negative_after_colon_preserved() -> None:
    result = scan_text("температура: -7,2 °C")
    assert result.spans[0].value == Decimal("-7.2")


def test_symmetric_dash_range_preserved() -> None:
    result = scan_text("подача 10–12 т и 5 - 8 га")
    ranges = [s for s in result.spans if s.kind == "range"]
    assert {(str(r.low), str(r.high)) for r in ranges} == {("10", "12"), ("5", "8")}


def test_asymmetric_dash_is_not_a_range() -> None:
    result = scan_text("Расход топлива -0,14 кг/час подача 3 -2,0 кг/год")
    assert all(s.kind == "scalar" for s in result.spans)
    assert all(s.value is not None and s.value > 0 for s in result.spans)


# --- audit: emergency / limit qualifiers ----------------------------------------------------


def _qualified_sections(qual_a: str, qual_b: str):
    return {
        DOC_NDV: [
            section(
                DOC_NDV,
                1,
                f"{qual_a} выброс диоксида серы составляет 10 т/год.",
                title="Раздел A",
                page=1,
            ),
            section(
                DOC_NDV,
                2,
                f"{qual_b} выброс диоксида серы составляет 15 т/год.",
                title="Раздел B",
                page=3,
            ),
        ]
    }


def test_emergency_vs_unstated_suppressed() -> None:
    doc = document(DOC_NDV, page_count=3)
    extraction = _extract([doc], _qualified_sections("Аварийный", ""), {DOC_NDV: []})
    pairs, suppressed = _direct_pairs(extraction)
    assert pairs == []
    assert any(reason.startswith("qualifier") for reason in suppressed)


def test_limit_vs_unstated_suppressed_for_direct() -> None:
    doc = document(DOC_NDV, page_count=3)
    extraction = _extract([doc], _qualified_sections("Норматив ПДВ:", ""), {DOC_NDV: []})
    pairs, _ = _direct_pairs(extraction)
    assert [p for p in pairs if p.rule == "direct"] == []


def test_planned_vs_actual_still_suppressed() -> None:
    doc = document(DOC_NDV, page_count=3)
    extraction = _extract([doc], _qualified_sections("Планируемый", "Фактический"), {DOC_NDV: []})
    pairs, suppressed = _direct_pairs(extraction)
    assert pairs == []
    assert any(reason.startswith("qualifier_conflict") for reason in suppressed)


# --- audit: ambiguous 1,234 --------------------------------------------------------------


def test_ambiguous_comma_decimal_style_resolves_decimal() -> None:
    span = scan_text("масса 1,234 т", "comma").spans[0]
    assert span.value == Decimal("1.234")
    assert "ambiguous_decimal_grouping" not in span.flags


def test_ambiguous_comma_dot_style_resolves_thousands() -> None:
    # A thousands reading needs BOTH a dot-decimal style and positive
    # comma-grouping evidence in the document («1,234,567» elsewhere).
    span = scan_text("масса 1,234 т", "dot", frozenset({"comma"})).spans[0]
    assert span.value == Decimal("1234")
    assert "thousands_from_document_style" in span.flags
    assert "ambiguous_decimal_grouping" not in span.flags


def test_dot_style_without_grouping_evidence_stays_ambiguous() -> None:
    # This corpus mixes decimal conventions WITHIN documents: a dot-style
    # document without comma-grouping evidence must NOT reinterpret «69,625»
    # as 69625 (a ×1000 corruption) — the token stays ambiguous.
    span = scan_text("лимит 69,625 т/год", "dot").spans[0]
    assert span.value == Decimal("69.625")
    assert "ambiguous_decimal_grouping" in span.flags


def test_unresolved_ambiguous_excluded_from_comparisons() -> None:
    span = scan_text("масса 1,234 т", None).spans[0]
    assert "ambiguous_decimal_grouping" in span.flags
    doc = document(DOC_NDV, page_count=3)
    # Force an unknown document style: comma and dot decimals tie (integers
    # like «1900» never vote).
    sections_by_doc = {
        DOC_NDV: [
            section(DOC_NDV, 1, "калибровка 0,5 т и 0.5 т", title="A", page=1),
            section(DOC_NDV, 2, "выброс сажи 1,234 т/год.", title="B", page=2),
            section(DOC_NDV, 3, "выброс сажи 1900 кг/год.", title="C", page=3),
        ]
    }
    extraction = _extract([doc], sections_by_doc, {DOC_NDV: []})
    ambiguous = [m for m in extraction.mentions if "ambiguous_decimal_grouping" in m.flags]
    assert ambiguous, "unresolved token must still be preserved as a mention"
    pairs, suppressed = _direct_pairs(extraction)
    assert pairs == []
    assert suppressed.get("ambiguous_number_format")


# --- audit: unicode powers ------------------------------------------------------------------


def test_bare_unicode_power_single_token() -> None:
    result = scan_text("значение 10⁵ мг")
    assert len(result.spans) == 1
    assert result.spans[0].value == Decimal("100000")


def test_negative_unicode_power() -> None:
    result = scan_text("значение 2 · 10⁻⁵ г/с")
    assert len(result.spans) == 1
    assert result.spans[0].value == Decimal("0.00002")


def test_caret_power_without_mantissa() -> None:
    result = scan_text("порядка 10^3 м3")
    assert len(result.spans) == 1
    assert result.spans[0].value == Decimal("1000")


def test_damaged_scientific_notation_suppressed() -> None:
    result = scan_text("выброс 2 · 10 мг/м3")
    assert result.spans == []
    assert any(s.reason == "missing_scientific_exponent" for s in result.suppressed)


# --- audit: unit prefix collision -------------------------------------------------------------


def test_density_not_matched_as_mass_prefix() -> None:
    span = scan_text("плотность 1,2 г/см3").spans[0]
    assert span.unit is not None and span.unit.kind == "density"
    assert span.unit_raw == "г/см3"


def test_unsupported_compound_unit_left_unmatched() -> None:
    match = match_unit_after("5 кДж/кг", 2, 24)
    assert match is None  # no prefix match of «к» or similar


def test_density_conversions() -> None:
    g_cm3 = lookup_unit("г/см3")
    kg_m3 = lookup_unit("кг/м3")
    assert g_cm3 is not None and kg_m3 is not None
    assert convert_to_canonical(Decimal("1"), g_cm3) == Decimal("1000")
    assert convert_to_canonical(Decimal("1"), kg_m3) == Decimal("1")


def test_english_percentage_points() -> None:
    unit = lookup_unit("percentage points")
    assert unit is not None and unit.kind == "percent_points"
    assert lookup_unit("percentage point") is not None


# --- audit: identifier columns not materialized ------------------------------------------------


def test_identifier_and_year_columns_suppressed() -> None:
    doc = document(DOC_NDV, page_count=3)
    grid = [
        ["№ п/п", "Код", "Наименование", "Год достижения НДВ", "Выброс, т/год"],
        ["1", "0301", "Азота диоксид", "2027", "1,5"],
        ["2", "0330", "Серы диоксид", "2028", "2,5"],
    ]
    extraction = _extract([doc], {DOC_NDV: []}, {DOC_NDV: [table(DOC_NDV, 1, grid, page=2)]})
    values = {m.raw_number for m in extraction.mentions}
    assert values == {"1,5", "2,5"}
    assert extraction.suppressed_counts.get("identifier_column")


# --- audit: input error handling ----------------------------------------------------------------


def test_malformed_json_line_raises_p3runerror(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path, [document(DOC_NDV)], [], [])
    sections_path = dataset / "sections.jsonl"
    sections_path.write_text('{"broken json\n', encoding="utf-8")
    options = P3Options(
        dataset_dir=dataset,
        output_dir=tmp_path / "out",
        annotations_root=tmp_path / "ann",
    )
    with pytest.raises(P3RunError) as exc:
        run_p3(options)
    assert "sections.jsonl" in str(exc.value)
    assert "line 1" in str(exc.value)


def test_missing_required_key_raises_p3runerror(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path, [document(DOC_NDV)], [], [])
    (dataset / "tables.jsonl").write_text(
        json.dumps({"table_id": "x", "cells": [["a"]]}) + "\n", encoding="utf-8"
    )
    options = P3Options(
        dataset_dir=dataset,
        output_dir=tmp_path / "out",
        annotations_root=tmp_path / "ann",
    )
    with pytest.raises(P3RunError) as exc:
        run_p3(options)
    assert "tables.jsonl" in str(exc.value)


def test_cli_malformed_json_no_traceback(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from dalel.cli import app

    dataset = write_dataset(tmp_path, [document(DOC_NDV)], [], [])
    (dataset / "pages.jsonl").write_text("{oops\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app, ["run-p3", "--dataset", str(dataset), "--output", str(tmp_path / "o")]
    )
    assert result.exit_code == 1
    assert "ERROR:" in result.output
    assert "Traceback" not in result.output


# --- audit: suppression provenance ---------------------------------------------------------------


def test_suppressed_samples_artifact_has_provenance(tmp_path: Path) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "см. стр. 15 и ГОСТ 12.1.005-88; выброс сажи 1,5 т/год", page=1),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [])
    options = P3Options(
        dataset_dir=dataset,
        output_dir=tmp_path / "out",
        annotations_root=tmp_path / "ann",
    )
    run_p3(options)
    samples_path = tmp_path / "out" / "suppressed_samples.jsonl"
    assert samples_path.is_file()
    samples = [json.loads(line) for line in samples_path.read_text().splitlines()]
    assert samples
    reasons = {s["reason"] for s in samples}
    assert "reference_identifier" in reasons
    for sample in samples:
        assert sample["sample_id"].startswith("P3S__")
        assert sample["document_id"] == DOC_NDV
        assert sample["raw"]
        assert sample["context"]
        assert sample["source_kind"] in ("section_text", "table_cell")


# --- audit: high-severity eligibility gate --------------------------------------------


def _high_gate_dataset(tmp_path: Path, flags_text: str = ""):
    """Two enterprise inventory tables with a large substance conflict,
    with periods and qualifiers stated (tri-state high needs positive
    matches on every dimension)."""
    docs = [document(DOC_NDV, page_count=4)]
    sections_by_doc = [
        section(DOC_NDV, 1, "перечень", title="Перечень загрязняющих веществ", page=1, page_end=4),
    ]
    tables_by_doc = [
        _inventory_table_period(DOC_NDV, 1, 2, "1.0"),
        _inventory_table_period(DOC_NDV, 2, 3, "9.0"),
    ]
    return write_dataset(tmp_path, docs, sections_by_doc, tables_by_doc)


def _inventory_table_period(doc_id, index, page, gs_value):
    return table(
        doc_id,
        index,
        [
            [
                "Код ЗВ",
                "Наименование",
                "Выброс вещества с учетом очистки за 2025 год, г/с",
            ],
            ["0337", "Углерод оксид", gs_value],
        ],
        page=page,
    )


def test_high_requires_fully_established_context(tmp_path: Path) -> None:
    dataset = _high_gate_dataset(tmp_path)
    options = P3Options(
        dataset_dir=dataset,
        output_dir=tmp_path / "out",
        annotations_root=tmp_path / "ann",
    )
    result = run_p3(options)
    conflicts = [f for f in result.findings if f.finding_type == "direct_value_conflict"]
    assert conflicts, "fully-established enterprise conflict must be reported"
    assert conflicts[0].severity == "high"  # everything established -> high allowed


def test_ocr_blocks_high_severity(tmp_path: Path) -> None:
    from fixtures.p3_builders import page_record

    docs = [document(DOC_NDV, page_count=4, ocr_pages=[2, 3])]
    sections_by_doc = [
        section(DOC_NDV, 1, "перечень", title="Перечень загрязняющих веществ", page=1, page_end=4),
    ]
    tables_by_doc = [
        _inventory_table_period(DOC_NDV, 1, 2, "1.0"),
        _inventory_table_period(DOC_NDV, 2, 3, "9.0"),
    ]
    pages = [page_record(DOC_NDV, n, ocr_applied=n in (2, 3)) for n in range(1, 5)]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, tables_by_doc, pages=pages)
    options = P3Options(
        dataset_dir=dataset,
        output_dir=tmp_path / "out",
        annotations_root=tmp_path / "ann",
    )
    result = run_p3(options)
    conflicts = [f for f in result.findings if f.finding_type == "direct_value_conflict"]
    assert conflicts
    assert all(f.severity != "high" for f in conflicts), "OCR ambiguity must block high"
