"""Regression tests for every blocker from the SECOND independent audit.

Fixtures replicate production defect STRUCTURES synthetically; no project,
document, table or finding identifiers from production appear here as
production-code exclusions — only as shapes inside these fixtures.
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
    run_p3,
)
from dalel.pillars.quantitative_consistency.validation import validate_p3_outputs
from fixtures.p3_builders import (
    DOC_NDV,
    DOC_SUMMARY,
    document,
    section,
    table,
    write_dataset,
)

# =====================================================================
# 2. Full input contract validation (CLI matrix)
# =====================================================================


def _valid_dataset(tmp_path: Path) -> Path:
    return write_dataset(
        tmp_path,
        [document(DOC_NDV)],
        [section(DOC_NDV, 1, "выброс сажи 1,5 т/год", page=1)],
        [
            table(
                DOC_NDV,
                1,
                [["Вещество", "Выброс, т/год"], ["Сажа", "1,5"], ["Зола", "2,5"]],
                page=2,
            )
        ],
    )


def _invoke_run(dataset: Path, output: Path):
    from typer.testing import CliRunner

    from dalel.cli import app

    runner = CliRunner()
    return runner.invoke(app, ["run-p3", "--dataset", str(dataset), "--output", str(output)])


def _assert_clean_failure(result, output: Path) -> None:
    assert result.exit_code == 1, result.output
    assert "ERROR:" in result.output
    assert "Traceback" not in result.output
    assert "─" not in result.output  # no Rich exception frame
    # No output directory that looks successfully completed.
    assert not (output / "findings.jsonl").exists()
    assert not (output / "metrics.json").exists()


def test_cli_invalid_json(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    (dataset / "sections.jsonl").write_text("{broken\n", encoding="utf-8")
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")
    assert "sections.jsonl" in result.output and "line 1" in result.output


def test_cli_invalid_jsonl_non_object(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    (dataset / "pages.jsonl").write_text("[1, 2, 3]\n", encoding="utf-8")
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")


def test_cli_truncated_jsonl(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    text = (dataset / "tables.jsonl").read_text(encoding="utf-8")
    (dataset / "tables.jsonl").write_text(text[: len(text) // 2], encoding="utf-8")
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")


def test_cli_missing_required_file(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    (dataset / "documents.jsonl").unlink()
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")
    assert "documents.jsonl" in result.output


def test_cli_missing_required_field(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    records = [json.loads(line) for line in (dataset / "sections.jsonl").read_text().splitlines()]
    del records[0]["section_id"]
    (dataset / "sections.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")
    assert "section_id" in result.output


def test_cli_wrong_primitive_type(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    records = [json.loads(line) for line in (dataset / "pages.jsonl").read_text().splitlines()]
    records[0]["page_number"] = "NOT_AN_INT"
    (dataset / "pages.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")
    assert "page_number" in result.output


def test_cli_wrong_nested_type(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    records = [json.loads(line) for line in (dataset / "tables.jsonl").read_text().splitlines()]
    records[0]["cells"] = "not-a-grid"
    records[0]["provenance"]["page_number"] = {"nested": "object"}
    (dataset / "tables.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")
    assert "cells" in result.output or "provenance" in result.output


def test_cli_unexpected_extra_field(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    records = [json.loads(line) for line in (dataset / "sections.jsonl").read_text().splitlines()]
    records[0]["unexpected_extra"] = {"array": [1, 2]}
    (dataset / "sections.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")


def test_cli_unsupported_schema_version(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    records = [json.loads(line) for line in (dataset / "sections.jsonl").read_text().splitlines()]
    records[0]["schema_version"] = "99.0.0"
    (dataset / "sections.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")
    assert "schema" in result.output.casefold()


def test_cli_unreadable_file(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    (dataset / "pages.jsonl").unlink()
    (dataset / "pages.jsonl").mkdir()  # a directory where a file must be
    result = _invoke_run(dataset, tmp_path / "out")
    _assert_clean_failure(result, tmp_path / "out")


def test_valid_dataset_still_runs(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path)
    result = _invoke_run(dataset, tmp_path / "out")
    assert result.exit_code == 0, result.output


# =====================================================================
# 3. Damaged scientific notation
# =====================================================================


def _spans(text: str):
    return scan_text(text).spans


def test_variable_coefficient_damaged_power_suppressed() -> None:
    for text in ("выброс N · 10 мг", "выброс N × 10 мг", "выброс G · 10 мг/м3"):
        result = scan_text(text)
        assert result.spans == [], text
        assert any(s.reason == "missing_scientific_exponent" for s in result.suppressed), text


def test_numeric_coefficient_damaged_power_suppressed() -> None:
    result = scan_text("значение 2 · 10 в поврежденном контексте")
    assert result.spans == []
    assert any(s.reason == "missing_scientific_exponent" for s in result.suppressed)


def test_valid_powers_still_parse() -> None:
    assert _spans("2 · 10⁵ мг")[0].value == Decimal("200000")
    assert _spans("2 × 10⁻⁵ мг")[0].value == Decimal("0.00002")


def test_plain_ten_still_parses() -> None:
    spans = _spans("возьмите 10 мг вещества")
    assert len(spans) == 1 and spans[0].value == Decimal("10")


# =====================================================================
# 4. Dash / equipment-name / ratio parsing
# =====================================================================


def test_electrode_model_ratio_em_dash() -> None:
    result = scan_text("УОНИ 13/55 — 0,3 кг/год;")
    valued = [s for s in result.spans if s.unit is not None]
    assert len(valued) == 1
    assert valued[0].value == Decimal("0.3")
    assert valued[0].kind == "scalar"
    assert result.spans == valued, "13/55 must not create scalar or range spans"
    assert not any("range_inversion" in s.flags for s in result.spans)


def test_electrode_model_ratio_attached_dash() -> None:
    result = scan_text("УОНИ 13/55 (аналог Э42) -0,3 кг/год;")
    valued = [s for s in result.spans if s.unit is not None]
    assert len(valued) == 1 and valued[0].value == Decimal("0.3")
    assert all(s.kind == "scalar" for s in result.spans)


def test_model_em_dash_value() -> None:
    result = scan_text("МР-3 — 2,0 кг/год;")
    valued = [s for s in result.spans if s.unit is not None]
    assert len(valued) == 1 and valued[0].value == Decimal("2.0")


def test_model_spaced_dash_no_range() -> None:
    result = scan_text("МР -3 -2,0 кг/год;")
    assert all(s.kind == "scalar" for s in result.spans)
    assert not any("range_inversion" in s.flags for s in result.spans)


def test_key_value_dash_positive() -> None:
    result = scan_text("Количество ПГС — 7,2 т")
    assert result.spans[0].value == Decimal("7.2")


def test_genuine_negative_preserved_audit2() -> None:
    assert _spans("температура: -7,2 °C")[0].value == Decimal("-7.2")


def test_ranges_preserved_audit2() -> None:
    for text in ("подача 10–12 т", "подача 10 - 12 т"):
        span = _spans(text)[0]
        assert span.kind == "range" and (span.low, span.high) == (
            Decimal("10"),
            Decimal("12"),
        )


def test_sentence_punctuation_creates_no_quantities() -> None:
    result = scan_text("Работы завершены — объект сдан. Проверка — выполнена.")
    assert result.spans == []


# =====================================================================
# 5. High-precision decimals are quantities
# =====================================================================


def test_long_comma_decimal_preserved() -> None:
    span = _spans("расход 23,929263576 т/год")[0]
    assert span.value == Decimal("23.929263576")
    assert span.raw == "23,929263576"
    assert span.display_quantum == Decimal("1E-9")
    assert span.unit is not None and span.unit.canonical == "т/год"


def test_long_dot_decimal_preserved() -> None:
    span = _spans("объем 3.141592653 м3")[0]
    assert span.value == Decimal("3.141592653")


def test_small_long_decimal_preserved() -> None:
    span = _spans("расход 0,123456789 т/год")[0]
    assert span.value == Decimal("0.123456789")


def test_true_identifiers_still_suppressed() -> None:
    result = scan_text("БИН 111240021512, тел. 8-705-908-35-30, счет KZ123456789012")
    assert result.spans == []
    result2 = scan_text("широта 50.283056 СШ")
    assert result2.spans == []  # coordinate context


def test_item_number_header_is_identifier_not_percent_points() -> None:
    """Header «№ п.п.» is a row-number column («по порядку»), not the
    percentage-points unit «п.п.» — its dotted spelling must not turn plan
    item numbers 1.1/2.1 into unit-bearing quantities (found in the final
    production mention review)."""
    doc = document(DOC_NDV, page_count=3)
    grid = [
        ["№ п.п.", "Мероприятие", "Объем, т/год"],
        ["1.1", "Пылеподавление", "1,5"],
        ["2.1", "Мониторинг", "2,5"],
    ]
    extraction = _extract([doc], {DOC_NDV: []}, {DOC_NDV: [table(DOC_NDV, 1, grid, page=2)]})
    assert {m.raw_number for m in extraction.mentions} == {"1,5", "2,5"}
    assert all(m.unit_canonical != "п.п." for m in extraction.mentions)
    assert extraction.suppressed_counts.get("identifier_column", 0) >= 2


def test_real_percent_points_column_still_parsed() -> None:
    doc = document(DOC_NDV, page_count=3)
    grid = [
        ["Показатель", "Изменение, п.п."],
        ["Доля очистки", "5,2"],
    ]
    extraction = _extract([doc], {DOC_NDV: []}, {DOC_NDV: [table(DOC_NDV, 1, grid, page=2)]})
    units = {m.raw_number: m.unit_canonical for m in extraction.mentions}
    assert units.get("5,2") == "п.п."


def test_bare_pp_token_is_not_percent_points() -> None:
    """Dotless «пп» comes from OCR fragments («гру пп ы суммации», «NI ПП»
    row-number headers), never from the percentage-points unit — accepting it
    turned substance codes into unit-bearing quantities (found in the final
    production mention review)."""
    from dalel.pillars.quantitative_consistency.extractor import find_unit_in_label
    from dalel.pillars.quantitative_consistency.units import lookup_unit

    assert lookup_unit("пп") is None
    assert lookup_unit("ПП") is None
    assert lookup_unit("п.п.") is not None
    assert lookup_unit("процентных пункта") is not None
    assert find_unit_in_label("Код веще ств а гру пп ы сумм ац ии") is None
    assert find_unit_in_label("NI ПП") is None


# =====================================================================
# 6-7. Semantic identity: sub-entities and positive source compatibility
# =====================================================================

_EMISSION_HEADER = [
    "Код",
    "Наименование ЗВ",
    "Валовый выброс за 2025 год, г/с",
    "Валовый выброс за 2025 год, т/год",
]


def _emission_calc_table(doc_id, index, page, gs, ty):
    return table(
        doc_id,
        index,
        [_EMISSION_HEADER, ["0328", "Сажа", gs, ty]],
        page=page,
    )


def _extract(documents, sections_by_doc, tables_by_doc):
    return extract_mentions(
        documents,
        sections_by_doc,
        tables_by_doc,
        {d["document_id"]: [] for d in documents},
    )


def _sub_entity_dataset(equipment_a: str, equipment_b: str, gs_a: str, gs_b: str):
    """One source block (heading page 2) with two release-point sub-blocks."""
    doc = document(DOC_NDV, page_count=10)
    sections_by_doc = {
        DOC_NDV: [
            section(DOC_NDV, 1, "расчет", title="Цех - источник №6001", page=2),
            section(DOC_NDV, 2, "расчет", title=equipment_a, page=3),
            section(DOC_NDV, 3, "расчет", title=equipment_b, page=6),
        ]
    }
    tables_by_doc = {
        DOC_NDV: [
            _emission_calc_table(DOC_NDV, 1, 4, gs_a, "1,0"),
            _emission_calc_table(DOC_NDV, 2, 7, gs_b, "2,0"),
        ]
    }
    return _extract([doc], sections_by_doc, tables_by_doc)


def test_same_source_different_equipment_suppressed() -> None:
    extraction = _sub_entity_dataset(
        "Источник выделения N 6001 05, Автоматическая сварка",
        "Источник выделения N 6001 06, Портальная установка",
        "0.01",
        "0.06",
    )
    result = build_candidates(extraction.mentions)
    assert [p for p in result.pairs if p.rule == "direct"] == []
    assert result.suppressed_counts.get("sub_entity_mismatch")


def test_same_source_same_equipment_conflict_found() -> None:
    from dalel.pillars.quantitative_consistency.comparisons import compare_pair

    extraction = _sub_entity_dataset(
        "Источник выделения N 6001 05, Автоматическая сварка",
        "Источник выделения N 6001 05, Автоматическая сварка (продолжение)",
        "0.01",
        "0.06",
    )
    mentions = [m for m in extraction.mentions if m.unit_canonical == "г/с"]
    assert all(m.sub_entity is not None for m in mentions)
    result = build_candidates(extraction.mentions)
    pairs = [p for p in result.pairs if p.rule == "direct"]
    assert pairs, "same source + same release point must be comparable"
    findings = [finding for pair in pairs if (finding := compare_pair(pair)) is not None]
    assert findings and all(finding.severity == "high" for finding in findings)


def test_same_source_unknown_equipment_is_suppressed() -> None:
    doc = document(DOC_NDV, page_count=8)
    sections_by_doc = {
        DOC_NDV: [section(DOC_NDV, 1, "расчет", title="Цех - источник №6001", page=2)]
    }
    tables_by_doc = {
        DOC_NDV: [
            _emission_calc_table(DOC_NDV, 1, 3, "0.01", "1,0"),
            _emission_calc_table(DOC_NDV, 2, 5, "0.06", "2,0"),
        ]
    }
    extraction = _extract([doc], sections_by_doc, tables_by_doc)
    result = build_candidates(extraction.mentions)
    assert [pair for pair in result.pairs if pair.rule == "direct"] == []
    diagnostics = [
        candidate
        for candidate in result.candidates
        if candidate.status == "suppressed"
        and "identity_not_established" in candidate.suppression_reasons
    ]
    assert diagnostics
    assert all(candidate.dimension_states["sub_entity"] == "unknown" for candidate in diagnostics)
    assert all("unknown_sub_entity" in candidate.suppression_reasons for candidate in diagnostics)


def test_same_source_same_equipment_equivalent_units_consistent() -> None:
    doc = document(DOC_NDV, page_count=10)
    sections_by_doc = {
        DOC_NDV: [
            section(DOC_NDV, 1, "расчет", title="Цех - источник №6001", page=2),
            section(DOC_NDV, 2, "расчет", title="Источник выделения N 6001 05, Сварка", page=3),
        ]
    }
    tables_by_doc = {
        DOC_NDV: [
            table(
                DOC_NDV,
                1,
                [["Вещество", "Валовый выброс за 2025 год, т/год"], ["Сажа", "1,2"]],
                page=4,
            ),
            table(
                DOC_NDV,
                2,
                [["Вещество", "Валовый выброс за 2025 год, кг/год"], ["Сажа", "1200"]],
                page=5,
            ),
        ]
    }
    from dalel.pillars.quantitative_consistency.comparisons import compare_pair

    extraction = _extract([doc], sections_by_doc, tables_by_doc)
    result = build_candidates(extraction.mentions)
    pairs = [p for p in result.pairs if p.rule == "direct"]
    assert pairs, "equivalent-unit same-sub-entity pair must be compared"
    assert all(compare_pair(p) is None for p in pairs)  # 1.2 т == 1200 кг


def test_different_facilities_same_substance_suppressed() -> None:
    doc = document(DOC_NDV, page_count=10)
    sections_by_doc = {
        DOC_NDV: [
            section(DOC_NDV, 1, "расчет", title="Площадка А - источник №6001", page=2),
            section(DOC_NDV, 2, "расчет", title="Площадка Б - источник №6002", page=5),
        ]
    }
    tables_by_doc = {
        DOC_NDV: [
            _emission_calc_table(DOC_NDV, 1, 3, "0.01", "1,0"),
            _emission_calc_table(DOC_NDV, 2, 6, "0.06", "2,0"),
        ]
    }
    extraction = _extract([doc], sections_by_doc, tables_by_doc)
    result = build_candidates(extraction.mentions)
    assert [p for p in result.pairs if p.rule == "direct"] == []


# =====================================================================
# 8. Tri-state high-severity eligibility
# =====================================================================


def _inventory_table(doc_id, index, page, gs_value, period="за 2025 год"):
    return table(
        doc_id,
        index,
        [
            ["Код ЗВ", "Наименование", f"Валовый выброс {period}, т/год"],
            ["0337", "Углерод оксид", gs_value],
        ],
        page=page,
    )


def _enterprise_pair_dataset(
    tmp_path, value_a, value_b, period_a="за 2025 год", period_b="за 2025 год"
):
    docs = [document(DOC_NDV, page_count=5)]
    sections_by_doc = [
        section(DOC_NDV, 1, "перечень", title="Перечень загрязняющих веществ", page=1, page_end=5),
    ]
    tables_by_doc = [
        _inventory_table(DOC_NDV, 1, 2, value_a, period_a),
        _inventory_table(DOC_NDV, 2, 3, value_b, period_b),
    ]
    return write_dataset(tmp_path, docs, sections_by_doc, tables_by_doc)


def _run(tmp_path, dataset):
    return run_p3(
        P3Options(
            dataset_dir=dataset,
            output_dir=tmp_path / "out",
            annotations_root=tmp_path / "ann",
        )
    )


def test_fully_aligned_contradiction_reaches_high(tmp_path: Path) -> None:
    dataset = _enterprise_pair_dataset(tmp_path, "1.0", "9.0")
    result = _run(tmp_path, dataset)
    conflicts = [f for f in result.findings if f.finding_type == "direct_value_conflict"]
    assert conflicts and conflicts[0].severity == "high", [
        (f.severity, f.confidence) for f in conflicts
    ]


def test_missing_period_prevents_high_and_medium(tmp_path: Path) -> None:
    dataset = _enterprise_pair_dataset(tmp_path, "1.0", "9.0", period_a="", period_b="")
    result = _run(tmp_path, dataset)
    conflicts = [f for f in result.findings if f.finding_type == "direct_value_conflict"]
    assert conflicts == []
    diagnostics = [
        candidate
        for candidate in result.candidates
        if "identity_not_established" in candidate.suppression_reasons
    ]
    assert diagnostics
    assert all(candidate.dimension_states["period"] == "unknown" for candidate in diagnostics)


def test_missing_qualifiers_prevent_high(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, page_count=5)]
    sections_by_doc = [
        section(DOC_NDV, 1, "перечень", title="Перечень загрязняющих веществ", page=1, page_end=5),
    ]
    # periods stated and equal, but NO qualifiers anywhere
    tables_by_doc = [
        table(
            DOC_NDV,
            1,
            [
                ["Код ЗВ", "Наименование", "Выброс за 2025 год, т/год"],
                ["0337", "Углерод оксид", "1.0"],
            ],
            page=2,
        ),
        table(
            DOC_NDV,
            2,
            [
                ["Код ЗВ", "Наименование", "Выброс за 2025 год, т/год"],
                ["0337", "Углерод оксид", "9.0"],
            ],
            page=3,
        ),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, tables_by_doc)
    result = _run(tmp_path, dataset)
    conflicts = [f for f in result.findings if f.finding_type == "direct_value_conflict"]
    assert conflicts == []
    diagnostics = [
        candidate
        for candidate in result.candidates
        if "identity_not_established" in candidate.suppression_reasons
    ]
    assert diagnostics
    assert all(candidate.dimension_states["qualifiers"] == "unknown" for candidate in diagnostics)


def test_unknown_facility_prevents_high(tmp_path: Path) -> None:
    docs = [document(DOC_NDV, page_count=5)]
    tables_by_doc = [
        _inventory_table(DOC_NDV, 1, 2, "1.0"),
        _inventory_table(DOC_NDV, 2, 3, "9.0"),
    ]
    dataset = write_dataset(tmp_path, docs, [], tables_by_doc)  # no enterprise section
    result = _run(tmp_path, dataset)
    assert all(f.severity != "high" for f in result.findings)


# =====================================================================
# 9-10. Aggregation hierarchy
# =====================================================================


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


def test_coincidental_equality_is_not_hierarchy() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["А", "5"],
        ["Б", "2"],
        ["В", "3"],
        ["Г", "4"],
        ["Итого:", "14"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == [], [f.title for f in outcome.findings]
    assert outcome.checks_consistent == 1


def test_real_mismatch_with_coincidental_equality_still_detected() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["А", "5"],
        ["Б", "2"],
        ["В", "3"],
        ["Г", "4"],
        ["Итого:", "15"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert len(outcome.findings) == 1
    assert outcome.findings[0].comparison.expected_value == "14"


def test_equal_valued_independent_components_both_counted() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["А", "5"],
        ["Б", "5"],
        ["Итого:", "10"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []
    assert outcome.checks_consistent == 1


def test_total_then_including_consistent() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["Всего:", "5"],
        ["в том числе:", ""],
        ["А", "2"],
        ["Б", "3"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []
    assert outcome.checks_consistent == 1


def test_total_then_including_mismatch() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["Всего:", "9"],
        ["в том числе:", ""],
        ["А", "2"],
        ["Б", "3"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert len(outcome.findings) == 1
    assert outcome.findings[0].comparison.expected_value == "5"
    assert outcome.findings[0].comparison.observed_value == "9"


def test_labeled_subtotal_with_including_children_not_double_counted() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["Категория А", "10"],
        ["Итого по категории Б:", "2,625"],
        ["в том числе:", ""],
        ["Деталь Б1", "2,5"],
        ["Деталь Б2", "0,125"],
        ["Всего:", "12,625"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == [], [f.title for f in outcome.findings]
    assert outcome.checks_consistent >= 2  # subtotal check + grand check


def test_incomplete_child_group_is_diagnostic_not_contradiction() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["Всего:", "9"],
        ["в том числе:", ""],
        ["А", "2"],
        ["Б", "нет данных 1 и 2"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []
    assert (outcome.suppressed_counts or {}).get("aggregation_incomplete_components")


def test_mixed_chain_requires_established_subtotals() -> None:
    """A grand total must not chain an independent row with a subtotal whose
    own children were never established locally (page-fragment layout): the
    subtotal may already COVER that row, and the chain double counts
    (production false positive: 0.002106 + «Итого 0.047866» vs «Всего
    0.047866»)."""
    grid = [
        ["Наименование", "т/год"],
        ["А", "0.002106"],
        ["Итого:", "0.047866"],  # span=[А] < min components: unestablished
        ["Всего по указанным веществам:", "0.047866"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []
    assert all(c.decision == "consistent" for c in outcome.checks)


def test_established_mixed_chain_still_checked() -> None:
    grid_ok = [
        ["Наименование", "т/год"],
        ["А", "1"],
        ["Б", "2"],
        ["Итого:", "3"],  # established from [А, Б]
        ["В", "4"],
        ["Всего:", "7"],  # mixed chain [В, Итого] = 7
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid_ok, page=2)])
    assert outcome.findings == []
    assert any(c.direction == "mixed_chain" for c in outcome.checks)
    grid_bad = [row[:] for row in grid_ok]
    grid_bad[5][1] = "8"  # 4 + 3 = 7, stated 8: real mismatch
    outcome_bad = _run_aggregation([table(DOC_NDV, 1, grid_bad, page=2)])
    assert len(outcome_bad.findings) == 1


def test_subtotal_chain_requires_identical_labels() -> None:
    """«Всего по загрязняющему веществу» and «Всего по объекту» share a
    first word but are DIFFERENT hierarchy levels (restatements, not
    siblings) — chaining them double counted a production table."""
    grid = [
        ["Наименование", "т/год"],
        ["Всего по загрязняющему веществу:", "2"],
        ["Всего по объекту:", "2,5"],  # object total: substance + background
        ["Всего с учетом фона:", "2,5"],  # restatement, NOT a sibling of both
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []
    assert outcome.checks == []


def test_identically_labeled_subtotal_chain_still_checked() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["Всего по веществу:", "2"],
        ["Всего по веществу:", "3"],
        ["Итого:", "6"],  # 2 + 3 = 5: real mismatch
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert len(outcome.findings) == 1
    assert any(c.direction == "subtotals" for c in outcome.checks)


def test_near_duplicate_tables_stay_distinct() -> None:
    grid_a = [
        ["Наименование", "т/год"],
        ["А", "5"],
        ["Б", "2"],
        ["Итого:", "9"],
    ]
    grid_b = [row[:] for row in grid_a]
    grid_b[1][1] = "6"  # changed value: NOT a copy
    outcome = _run_aggregation(
        [
            table(DOC_NDV, 1, grid_a, page=2),
            table(DOC_SUMMARY, 1, grid_b, page=2, doc_type="nontechnical_summary"),
        ],
        doc_ids=[DOC_NDV, DOC_SUMMARY],
    )
    # 5+2=7 vs 9 mismatch AND 6+2=8 vs 9 mismatch: both must be reported.
    assert len(outcome.findings) == 2


def test_mixed_periods_suppress_aggregation() -> None:
    grid = [
        ["Наименование", "т/год"],
        ["А за 2024 год", "5"],
        ["Б за 2025 год", "2"],
        ["Итого:", "9"],
    ]
    outcome = _run_aggregation([table(DOC_NDV, 1, grid, page=2)])
    assert outcome.findings == []
    assert (outcome.suppressed_counts or {}).get("aggregation_mixed_periods")


# =====================================================================
# 11. Aggregation checks serialized for consistent checks too
# =====================================================================


def test_consistent_aggregation_checks_serialized(tmp_path: Path) -> None:
    grid = [
        ["Наименование", "Лимит, т/год"],
        ["А", "5"],
        ["Б", "2"],
        ["Итого:", "7"],
    ]
    dataset = write_dataset(tmp_path, [document(DOC_NDV)], [], [table(DOC_NDV, 1, grid, page=2)])
    _run(tmp_path, dataset)
    checks_path = tmp_path / "out" / "aggregation_checks.jsonl"
    assert checks_path.is_file()
    checks = [json.loads(line) for line in checks_path.read_text().splitlines()]
    assert len(checks) == 1
    check = checks[0]
    assert check["decision"] == "consistent"
    assert check["expected_total"] == "7"
    assert check["observed_total"] == "7"
    assert check["components"]
    assert all(c["conversion_factor"] for c in check["components"] if c["included"])
    assert check["check_id"].startswith("P3A__")


# =====================================================================
# 12. Suppression diagnostics
# =====================================================================


def test_suppressed_comparison_samples_cover_reasons(tmp_path: Path) -> None:
    """Pair-level suppression families get stratified candidate samples with
    per-side semantic context and ALL rejection reasons."""
    docs = [document(DOC_NDV, page_count=8)]
    sections_by_doc = [
        section(DOC_NDV, 1, "расчет", title="Цех - источник №6001", page=2),
        section(DOC_NDV, 2, "расчет", title="Источник выделения N 6001 05, Сварка", page=3),
        section(DOC_NDV, 3, "расчет", title="Источник выделения N 6001 06, Резка", page=5),
        section(
            DOC_NDV,
            7,
            "Аварийный выброс сажи 5 т/год. Планируемый выброс сажи 6 т/год.",
            title="Сценарии",
            page=8,
        ),
    ]
    tables_by_doc = [
        _emission_calc_table(DOC_NDV, 1, 4, "0.01", "1,0"),
        _emission_calc_table(DOC_NDV, 2, 6, "0.06", "2,0"),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, tables_by_doc)
    _run(tmp_path, dataset)
    candidates = [
        json.loads(line)
        for line in (tmp_path / "out" / "candidates.jsonl").read_text().splitlines()
    ]
    suppressed = [c for c in candidates if c["status"] == "suppressed"]
    reasons = {r for c in suppressed for r in c["suppression_reasons"]}
    assert "sub_entity_mismatch" in reasons
    for c in suppressed:
        assert c["suppression_reasons"], "all rejection reasons must be recorded"
        assert "aggregation_scope" in c["compatibility"]
        assert "sub_entity" in c["compatibility"]


def _qm(n: int, value: str, *, substance: str = "no2", table: str | None = None, page: int = 1):
    from decimal import Decimal as D

    from dalel.pillars.quantitative_consistency.schemas import MentionLocation, QuantMention

    return QuantMention(
        mention_id=f"P3Q__guard{n:04d}",
        project_id="project_x",
        document_id=DOC_NDV,
        location=MentionLocation(
            source_kind="table_cell" if table else "section_text",
            table_id=table,
            section_id=None if table else f"sec-{n}",
            row=1 if table else None,
            col=n if table else None,
            page_number=page,
            char_start=None if table else n * 100,
            char_end=None if table else n * 100 + 5,
        ),
        raw_text=f"guard fixture {n}",
        raw_number=value,
        kind="scalar",
        modifier="none",
        value=value,
        unit_raw="т/год",
        unit_canonical="т/год",
        unit_source="inline",
        dimension="mass_rate/year",
        canonical_unit="г/год",
        canonical_value=str(D(value) * D("1000000")),
        conversion_factor="1000000",
        display_quantum="0.1",
        canonical_quantum="100000",
        metric_group="emission",
        substance=substance,
        aggregation_scope="enterprise",
        extraction_confidence=0.9,
    )


def test_guard_stage_suppressions_serialize_pair_samples() -> None:
    """Group- and pair-level GUARD rejections (same physical table, entity
    under-resolution) must leave serialized candidate samples, not bare
    counters — an auditor needs at least one concrete example per family."""
    same_table = [_qm(1, "1.0", table="tab-1"), _qm(2, "1.0", table="tab-1")]
    under_resolved = [
        _qm(3, "1.0", substance="so2", page=2),
        _qm(4, "2.0", substance="so2", page=3),
        _qm(5, "3.0", substance="so2", page=4),
    ]
    result = build_candidates(same_table + under_resolved)
    suppressed = [c for c in result.candidates if c.status == "suppressed"]
    reasons = {r for c in suppressed for r in c.suppression_reasons}
    assert "same_physical_location" in reasons
    assert "ambiguous_entity_resolution" in reasons
    for candidate in suppressed:
        assert candidate.dimension_states  # semantic context kept on samples


def test_suppressed_number_samples_have_state_and_secondary_reasons(
    tmp_path: Path,
) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "см. ГОСТ 12.1.005-88 и стр. 15; выброс 1,5 т/год", page=1),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [])
    _run(tmp_path, dataset)
    samples = [
        json.loads(line)
        for line in (tmp_path / "out" / "suppressed_samples.jsonl").read_text().splitlines()
    ]
    assert samples
    for sample in samples:
        assert sample.get("parser_state")
        assert isinstance(sample["secondary_reasons"], list)


# =====================================================================
# 13. Validator tamper matrix
# =====================================================================


@pytest.fixture()
def tampering_run(tmp_path: Path) -> dict[str, Path]:
    docs = [document(DOC_NDV, page_count=5)]
    sections_by_doc = [
        section(DOC_NDV, 1, "перечень", title="Перечень загрязняющих веществ", page=1, page_end=5),
    ]
    tables_by_doc = [
        _inventory_table(DOC_NDV, 1, 2, "1.0"),
        _inventory_table(DOC_NDV, 2, 3, "9.0"),
        table(
            DOC_NDV,
            3,
            [["Наименование", "Лимит, т/год"], ["А", "5"], ["Б", "2"], ["Итого:", "9"]],
            page=4,
        ),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, tables_by_doc)
    _run(tmp_path, dataset)
    return {"dataset": dataset, "output": tmp_path / "out", "root": tmp_path}


def _tamper_jsonl(path: Path, mutate) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(rows)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _first_conflict(rows):
    return next(r for r in rows if r["finding_type"] == "direct_value_conflict")


TAMPER_CASES = {
    "canonical_unit": lambda rows: _first_conflict(rows)["comparison"].update(
        {"canonical_unit": "кг/год"}
    ),
    "conversion_factor": lambda rows: _first_conflict(rows)["comparison"]["conversions"][0].update(
        {"conversion_factor": "999"}
    ),
    "canonical_value": lambda rows: _first_conflict(rows)["comparison"]["conversions"][0].update(
        {"canonical_value": "123456"}
    ),
    "tolerance_abs": lambda rows: _first_conflict(rows)["comparison"].update(
        {"tolerance_abs": "99999"}
    ),
    "tolerance_rel": lambda rows: _first_conflict(rows)["comparison"].update(
        {"tolerance_rel": "0.9"}
    ),
    "rounding_tolerance": lambda rows: _first_conflict(rows)["comparison"].update(
        {"rounding_tolerance": "99999"}
    ),
    "formula": lambda rows: _first_conflict(rows)["comparison"].update(
        {"formula": "tampered formula"}
    ),
    "severity": lambda rows: _first_conflict(rows).update(
        {"severity": "info", "priority_score": 2}
    ),
    "confidence": lambda rows: _first_conflict(rows).update({"confidence": 0.99}),
    "evidence_page": lambda rows: _first_conflict(rows)["evidence"][0].update({"page_number": 999}),
    "evidence_quote": lambda rows: _first_conflict(rows)["evidence"][0].update(
        {"quote": "fabricated quote"}
    ),
    "observed_value": lambda rows: _first_conflict(rows)["comparison"].update(
        {"observed_value": "42"}
    ),
    "finding_ordering": lambda rows: rows.reverse(),
}


@pytest.mark.parametrize("field", sorted(TAMPER_CASES))
def test_tamper_findings_detected(tampering_run, field) -> None:
    _tamper_jsonl(tampering_run["output"] / "findings.jsonl", TAMPER_CASES[field])
    result = validate_p3_outputs(tampering_run["dataset"], tampering_run["output"])
    assert not result.ok, f"tampering {field} must fail validation"


def test_tamper_mention_unit_detected(tampering_run) -> None:
    def mutate(rows):
        target = next(r for r in rows if r["unit_canonical"] == "т/год")
        target["canonical_unit"] = "мг/м3"

    _tamper_jsonl(tampering_run["output"] / "mentions.jsonl", mutate)
    result = validate_p3_outputs(tampering_run["dataset"], tampering_run["output"])
    assert not result.ok


def test_tamper_aggregation_total_detected(tampering_run) -> None:
    def mutate(rows):
        rows[0]["expected_total"] = "77777"

    _tamper_jsonl(tampering_run["output"] / "aggregation_checks.jsonl", mutate)
    result = validate_p3_outputs(tampering_run["dataset"], tampering_run["output"])
    assert not result.ok


def test_tamper_project_score_detected(tampering_run) -> None:
    def mutate(rows):
        rows[0]["quantitative_consistency_priority_score"] = 1

    _tamper_jsonl(tampering_run["output"] / "project_scores.jsonl", mutate)
    result = validate_p3_outputs(tampering_run["dataset"], tampering_run["output"])
    assert not result.ok


def test_tamper_review_template_detected(tampering_run) -> None:
    template = tampering_run["root"] / "ann" / "p3_review_template.jsonl"

    def mutate(rows):
        rows[0]["finding_id"] = "P3__000000000000"

    _tamper_jsonl(template, mutate)
    result = validate_p3_outputs(
        tampering_run["dataset"],
        tampering_run["output"],
        annotations_root=tampering_run["root"] / "ann",
    )
    assert not result.ok


def test_untampered_run_validates(tampering_run) -> None:
    result = validate_p3_outputs(
        tampering_run["dataset"],
        tampering_run["output"],
        annotations_root=tampering_run["root"] / "ann",
    )
    assert result.ok, result.errors[:5]


# =====================================================================
# 14. Contextual resolution of ambiguous numerals
# =====================================================================


def test_aggregation_equality_resolves_ambiguity(tmp_path: Path) -> None:
    """«69,625» in a dot-style document resolves to 69.625 because the
    component sum matches exactly; no ambiguity finding remains."""
    grid = [
        ["Наименование отходов", "Лимит, тонн/год"],
        ["Всего:", "69,625"],
        ["в том числе:", ""],
        ["Опасные", "67"],
        ["Прочие", "2,625"],
    ]
    # dot-style corpus (unambiguous dot decimals elsewhere)
    docs = [document(DOC_NDV)]
    sections_by_doc = [section(DOC_NDV, 1, "калибровка 0.5 т и 1.5 т и 2.5 т", page=1)]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [table(DOC_NDV, 1, grid, page=2)])
    result = _run(tmp_path, dataset)
    ambiguous = [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]
    assert ambiguous == [], [f.title for f in ambiguous]
    assert result.metrics["aggregation_checks_consistent"] >= 1


def test_mixed_table_uses_local_decimal_comma_style(tmp_path: Path) -> None:
    grid = [
        ["Режим", "Напор, м", "Расход, м3/сут", "Расход, м3/ч", "Расход, л/с"],
        ["А", "0,187", "2,760", "5,659", "1,903"],
        ["Б", "", "3,240", "6,354", "2,121"],
        ["В", "", "6,0", "11,767", "5,226"],
    ]
    docs = [document(DOC_NDV)]
    sections_by_doc = [section(DOC_NDV, 1, "калибровка 0.5 и 1.5", page=1)]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [table(DOC_NDV, 1, grid, page=2)])
    result = _run(tmp_path, dataset)
    targets = {"6,354", "5,659", "1,903", "3,240", "2,760", "2,121", "11,767", "5,226"}
    resolved = [m for m in result.mentions if m.raw_number in targets]
    assert {m.raw_number for m in resolved} == targets
    assert all("ambiguous_decimal_grouping" not in m.flags for m in resolved)
    assert all("resolved_by:table_decimal_comma" in m.flags for m in resolved)
    assert not [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]


def test_column_local_decimal_comma_style_resolves_ambiguous_cell(tmp_path: Path) -> None:
    grid = [
        ["Режим", "Расход, м3/ч", "Масса, кг"],
        ["А", "6,0", "1"],
        ["Б", "6,354", "2"],
    ]
    docs = [document(DOC_NDV)]
    sections_by_doc = [section(DOC_NDV, 1, "калибровка 0.5 и 1.5", page=1)]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [table(DOC_NDV, 1, grid, page=2)])
    result = _run(tmp_path, dataset)
    mention = next(m for m in result.mentions if m.raw_number == "6,354")
    assert mention.value == "6.354"
    assert "resolved_by:table_decimal_comma" in mention.flags


def test_table_with_positive_comma_grouping_keeps_thousands_reading(tmp_path: Path) -> None:
    grid = [
        ["Материал", "Масса, кг"],
        ["Всего", "1,234,567"],
        ["Партия", "1,234"],
    ]
    docs = [document(DOC_NDV)]
    sections_by_doc = [section(DOC_NDV, 1, "калибровка 0.5 и 1.5", page=1)]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [table(DOC_NDV, 1, grid, page=2)])
    result = _run(tmp_path, dataset)
    mention = next(m for m in result.mentions if m.raw_number == "1,234")
    assert mention.value == "1234"
    assert "resolved_by:table_decimal_comma" not in mention.flags
    assert "thousands_from_document_style" in mention.flags


def test_formula_resolves_ambiguity(tmp_path: Path) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "проверка 0.5 т и 1.5 т и 2.5 т", page=1),
        section(
            DOC_NDV,
            2,
            "М год = 0,66 * 2000 * 3600 / 1000000 = 4,752 т/год выброс пыли",
            page=2,
        ),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [])
    result = _run(tmp_path, dataset)
    ambiguous = [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]
    assert ambiguous == []
    resolved = [m for m in result.mentions if m.raw_number == "4,752"]
    assert resolved and resolved[0].value == "4.752"
    assert "resolved_from_context" in resolved[0].flags


def test_engineering_magnitude_resolves_dimensions(tmp_path: Path) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "проверка 0.5 т и 1.5 т и 2.5 т", page=1),
        section(
            DOC_NDV,
            2,
            "Резервуар с наружным диаметром 9,129м. На высоте 4,246 м балки."
            " Камеры на отметке +2,500 м от пола.",
            page=2,
        ),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [])
    result = _run(tmp_path, dataset)
    ambiguous = [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]
    assert ambiguous == [], [f.title for f in ambiguous]
    values = {m.raw_number: m.value for m in result.mentions}
    assert values.get("9,129") == "9.129"


def test_descending_elevations_are_not_a_range_inversion(tmp_path: Path) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "проверка 0.5 т и 1.5 т", page=1),
        section(
            DOC_NDV,
            2,
            "Уклон кровли создается за счет разной высоты стоек (от 5,500 до 5,150 м).",
            page=2,
        ),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [])
    result = _run(tmp_path, dataset)
    assert not [f for f in result.findings if f.finding_type == "range_inversion"]
    assert not [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]


def test_genuinely_unresolved_ambiguity_keeps_info_cue(tmp_path: Path) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "проверка 0.5 т и 1.5 т", page=1),
        section(DOC_NDV, 2, "выброс углерода оксида 22,716 т/год по расчету", page=2),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [])
    result = _run(tmp_path, dataset)
    ambiguous = [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]
    assert len(ambiguous) == 1


def test_isolated_1234_stays_unresolved(tmp_path: Path) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "калибровка 0.5 и 1.5", page=1),
        section(DOC_NDV, 2, "масса отходов 1,234 т/год", page=2),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [])
    result = _run(tmp_path, dataset)
    mention = next(m for m in result.mentions if m.raw_number == "1,234")
    assert "ambiguous_decimal_grouping" in mention.flags
    ambiguous = [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]
    assert len(ambiguous) == 1


def test_table_local_resolution_propagates_to_narrative_twin(tmp_path: Path) -> None:
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "калибровка 0.5 и 1.5", page=1),
        section(DOC_NDV, 2, "Расход установки составляет 6,354 м3/ч.", page=2),
    ]
    grid = [
        ["Режим", "Расход, м3/ч"],
        ["А", "6,0"],
        ["Б", "6,354"],
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, [table(DOC_NDV, 1, grid, page=3)])
    result = _run(tmp_path, dataset)
    twins = [m for m in result.mentions if m.raw_number == "6,354"]
    assert len(twins) == 2
    assert all(m.value == "6.354" for m in twins)
    assert all("ambiguous_decimal_grouping" not in m.flags for m in twins)
    narrative = next(m for m in twins if m.location.source_kind == "section_text")
    assert "resolved_by:twin:table_decimal_comma" in narrative.flags
    assert not [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]


def test_twin_representation_resolution_dedupes(tmp_path: Path) -> None:
    """A narrative formula resolves «4,752»; the same token in a table of the
    same document resolves identically — no ambiguity cue for either."""
    docs = [document(DOC_NDV)]
    sections_by_doc = [
        section(DOC_NDV, 1, "проверка 0.5 т и 1.5 т", page=1),
        section(
            DOC_NDV,
            2,
            "М год = 0,66 * 2000 * 3600 / 1000000 = 4,752 т/год",
            page=2,
        ),
    ]
    tables_by_doc = [
        table(DOC_NDV, 1, [["Вещество", "Выброс, т/год"], ["Пыль зерновая", "4,752"]], page=3),
    ]
    dataset = write_dataset(tmp_path, docs, sections_by_doc, tables_by_doc)
    result = _run(tmp_path, dataset)
    ambiguous = [f for f in result.findings if f.finding_type == "ambiguous_numeric_format"]
    assert ambiguous == []
    table_twin = [
        m
        for m in result.mentions
        if m.raw_number == "4,752" and m.location.source_kind == "table_cell"
    ]
    assert table_twin and table_twin[0].value == "4.752"
