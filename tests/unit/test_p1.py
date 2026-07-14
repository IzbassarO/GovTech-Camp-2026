"""Tests for the P1 Document Integrity deterministic baseline."""

import json
from pathlib import Path

import pytest

from dalel.curation.builder import CurateOptions, build_curated_dataset
from dalel.pillars.document_integrity.document_completeness import (
    duplicate_heading_findings,
    section_findings,
    table_and_length_findings,
)
from dalel.pillars.document_integrity.normalization import normalize_title
from dalel.pillars.document_integrity.package_completeness import (
    date_range_findings,
    package_findings,
)
from dalel.pillars.document_integrity.pipeline import (
    P1Options,
    is_false_positive_review_candidate,
    run_p1,
)
from dalel.pillars.document_integrity.quality import quality_findings
from dalel.pillars.document_integrity.schemas import FindingRecord
from dalel.pillars.document_integrity.scoring import score_document
from dalel.pillars.document_integrity.section_matcher import (
    HeadingCandidate,
    match_rule,
)
from dalel.pillars.document_integrity.taxonomy import SECTION_RULES, SectionRule
from fixtures.curation_builders import make_processed_repo


def _id_gen():
    counter = {"n": 0}

    def gen() -> str:
        counter["n"] += 1
        return f"T__{counter['n']:04d}"

    return gen


def _headings(*titles: str) -> list[HeadingCandidate]:
    return [HeadingCandidate(title=t, page_number=i + 1) for i, t in enumerate(titles)]


def _doc(document_type: str = "ndv", **overrides) -> dict:
    base = {
        "project_id": "p1",
        "document_id": "p1__doc__001",
        "document_type": document_type,
        "page_count": 20,
        "table_records": 3,
        "section_records": 5,
        "languages": ["ru"],
        "ocr": {"ocr_page_count": 0},
    }
    base.update(overrides)
    return base


def _page(number: int, text: str) -> dict:
    return {"page_number": number, "text": text, "char_count": len(text.strip())}


# --- normalization / matching -------------------------------------------------


def test_normalize_title() -> None:
    assert normalize_title("1.2. ВВЕДЕНИЕ:") == "введение"
    assert normalize_title("  Охрана атмосферного   воздуха!  ") == ("охрана атмосферного воздуха")
    assert normalize_title("Учёт отходов") == normalize_title("Учет отходов")


def test_exact_equality_russian_alias() -> None:
    rule = SECTION_RULES["ndv"][0]  # введение
    match = match_rule(rule, _headings("3. ВВЕДЕНИЕ"))
    assert match.matched and match.method == "exact_equality"
    assert match.matched_alias is not None
    assert match.page_number == 1


def test_exact_equality_kazakh_alias() -> None:
    rule = SECTION_RULES["ndv"][0]
    match = match_rule(rule, _headings("Кіріспе"))
    assert match.matched and match.method == "exact_equality"


def test_substring_classified_separately_from_equality() -> None:
    rule = SECTION_RULES["ndv"][6]  # контроль за соблюдением нормативов
    match = match_rule(
        rule, _headings("КОНТРОЛЬ ЗА СОБЛЮДЕНИЕМ НОРМАТИВОВ ПРЕДЕЛЬНО ДОПУСТИМЫХ ВЫБРОСОВ")
    )
    assert match.matched
    assert match.method == "normalized_substring"  # NOT exact
    equality = match_rule(rule, _headings("Контроль за соблюдением нормативов"))
    assert equality.method == "exact_equality"


def test_token_overlap_match() -> None:
    rule = SECTION_RULES["ndv"][2]  # инвентаризация источников выбросов
    match = match_rule(
        rule, _headings("Инвентаризация стационарных источников выбросов предприятия")
    )
    assert match.matched and match.method == "token_overlap"
    assert match.discriminative_tokens  # e.g. инвентаризация/источников


def test_false_fuzzy_thermal_vs_noise_rejected() -> None:
    """Regression for the verified blocker: «шумовое воздействие» must NOT
    match «Тепловое воздействие» (shared token is generic-only)."""
    rule = next(r for r in SECTION_RULES["roos"] if r.rule_id == "ROOS-S05")
    match = match_rule(rule, _headings("Тепловое воздействие"))
    assert not match.matched
    assert match.method == "none"
    assert match.rejected_fuzzy, "the candidate must be recorded as rejected"
    assert match.rejected_fuzzy[0].observed_heading == "Тепловое воздействие"
    assert "generic" in match.rejected_fuzzy[0].reason


def test_valid_fuzzy_accepted() -> None:
    """Fuzzy must survive for genuine OCR-style distortions."""
    rule = SECTION_RULES["ndv"][0]  # введение
    match = match_rule(rule, _headings("Введени"))  # truncated OCR heading
    assert match.matched and match.method == "fuzzy"
    assert match.score is not None and match.score >= 0.82
    assert match.discriminative_tokens


def test_generic_token_only_match_rejected() -> None:
    rule = SectionRule(
        rule_id="T-GEN",
        document_type="ndv",
        canonical_section="шумовое воздействие",
        aliases_ru=("шумовое воздействие",),
    )
    match = match_rule(rule, _headings("Вредное воздействие"))
    assert not match.matched


def test_no_match_returns_none_method() -> None:
    rule = SECTION_RULES["ndv"][0]
    match = match_rule(rule, _headings("Совершенно другой заголовок"))
    assert not match.matched and match.method == "none"


# --- findings -----------------------------------------------------------------


def test_required_vs_recommended_severity() -> None:
    findings, _ = section_findings(_doc(), [], _id_gen())
    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["NDV-S03"].severity == "medium"  # required
    assert by_rule["NDV-S05"].severity == "low"  # recommended
    assert all(f.confidence is None for f in findings)
    assert all(f.review_status == "pending" for f in findings)


def test_missing_finding_created_only_after_rejected_match() -> None:
    doc = _doc("roos", document_id="p1__roos__001")
    findings, _matches = section_findings(doc, _headings("Тепловое воздействие"), _id_gen())
    s05 = [f for f in findings if f.rule_id == "ROOS-S05"]
    assert len(s05) == 1  # rejected fuzzy => missing finding IS created
    assert "Отклонён fuzzy-кандидат" in s05[0].explanation

    accepted, _ = section_findings(doc, _headings("Шумовое воздействие"), _id_gen())
    assert not [f for f in accepted if f.rule_id == "ROOS-S05"]  # accepted => no finding


def test_empty_and_low_coverage_pages() -> None:
    pages = [_page(1, ""), _page(2, "x"), _page(3, "Достаточно длинный текст " * 5)]
    findings = quality_findings(_doc(), pages, _id_gen())
    types = {f.finding_type for f in findings}
    assert "empty_page" in types
    assert "low_text_coverage" in types


def test_high_ocr_dependency() -> None:
    doc = _doc(ocr={"ocr_page_count": 10}, page_count=20)
    findings = quality_findings(doc, [_page(n, "текст " * 20) for n in range(1, 21)], _id_gen())
    assert any(f.finding_type == "high_ocr_dependency" for f in findings)


def test_missing_tables_and_short_document() -> None:
    doc = _doc(table_records=0, page_count=2)
    findings = table_and_length_findings(doc, _id_gen())
    types = {f.finding_type for f in findings}
    assert types == {"missing_expected_tables", "suspicious_document_length"}


def test_duplicate_headings_threshold() -> None:
    titles = ["Введение", "1. Введение", "ВВЕДЕНИЕ", "Отходы", "Отходы"]
    findings = duplicate_heading_findings(_doc(), titles, _id_gen())
    assert len(findings) == 1
    assert findings[0].finding_type == "duplicate_heading"


def test_date_range_cross_document_inconsistency() -> None:
    project = {"project_id": "p1", "languages": ["ru"]}
    pages_by_doc = {
        "d1": [_page(1, "Проект нормативов на 2025-2034 годы")],
        "d2": [_page(1, "Программа на период 2026-2035 гг.")],
    }
    findings = date_range_findings(project, pages_by_doc, _id_gen())
    assert len(findings) == 1
    assert findings[0].finding_type == "date_range_inconsistency"
    assert findings[0].document_id is None


def test_date_range_single_document_multiple_ranges_not_flagged() -> None:
    project = {"project_id": "p1", "languages": ["ru"]}
    pages_by_doc = {"d1": [_page(1, "Наблюдения 2015-2019 и 2018-2021; проект на 2026-2035")]}
    assert date_range_findings(project, pages_by_doc, _id_gen()) == []


def test_package_completeness_missing_required() -> None:
    project = {"project_id": "p1", "languages": ["ru"]}
    documents = [_doc("ndv"), _doc("pek", document_id="p1__pek__001")]
    findings, profile = package_findings(project, documents, _id_gen())
    missing_types = {f.title for f in findings if f.severity == "high"}
    assert any("puo" in t for t in missing_types)
    assert any("action_plan" in t for t in missing_types)
    assert profile["profile_id"] == "permit_package"
    assert all(f.document_id is None for f in findings)


# --- scoring / FP single source -------------------------------------------------


def _fake_finding(
    severity: str, points: int, n: int, finding_type: str = "empty_page"
) -> FindingRecord:
    return FindingRecord(
        finding_id=f"F{n}",
        project_id="p1",
        document_id="d1",
        finding_type=finding_type,
        severity=severity,
        priority_score=points,
        rule_id="R",
        title=f"t{n}",
        explanation="e",
        limitations="l",
    )


def test_scoring_monotonic_and_capped_and_deterministic() -> None:
    subset = [_fake_finding("medium", 12, 1)]
    superset = [*subset, _fake_finding("high", 25, 2)]
    s1 = score_document("p1", "d1", "ndv", subset)
    s2 = score_document("p1", "d1", "ndv", superset)
    s2_again = score_document("p1", "d1", "ndv", superset)
    assert s2.document_integrity_priority_score >= s1.document_integrity_priority_score
    assert s2.model_dump() == s2_again.model_dump()  # deterministic

    many = [_fake_finding("high", 25, i) for i in range(10)]
    capped = score_document("p1", "d1", "ndv", many)
    assert capped.document_integrity_priority_score == 100
    assert len(capped.contributions) == 10


def test_score_zero_without_findings() -> None:
    assert score_document("p1", "d1", "ndv", []).document_integrity_priority_score == 0


def test_fp_candidate_single_source() -> None:
    assert is_false_positive_review_candidate(
        _fake_finding("info", 2, 1, finding_type="duplicate_heading")
    )
    assert is_false_positive_review_candidate(
        _fake_finding("low", 5, 2, finding_type="missing_appendix_reference")
    )
    low_section = _fake_finding("low", 5, 3, finding_type="missing_expected_section")
    assert is_false_positive_review_candidate(low_section)
    medium_section = _fake_finding("medium", 12, 4, finding_type="missing_expected_section")
    assert not is_false_positive_review_candidate(medium_section)
    assert not is_false_positive_review_candidate(_fake_finding("medium", 12, 5))


# --- end-to-end / CLI ----------------------------------------------------------


@pytest.fixture()
def curated(tmp_path: Path) -> dict[str, Path]:
    paths = make_processed_repo(tmp_path)
    output = tmp_path / "data" / "curated" / "v1"
    build_curated_dataset(
        CurateOptions(
            input_root=paths["processed"],
            output_dir=output,
            repo_root=tmp_path,
            manifest_path=paths["manifest"],
            annotations_root=paths["annotations_root"],
        )
    )
    return {"root": tmp_path, "dataset": output}


def _p1_options(curated: dict[str, Path]) -> P1Options:
    return P1Options(
        dataset_dir=curated["dataset"],
        output_dir=curated["root"] / "data" / "results" / "p1" / "v1",
        annotations_root=curated["root"] / "data" / "annotations",
    )


def test_run_p1_end_to_end_with_match_evidence(curated) -> None:
    result = run_p1(_p1_options(curated))
    output = curated["root"] / "data" / "results" / "p1" / "v1"
    for name in (
        "project_scores.jsonl",
        "document_scores.jsonl",
        "findings.jsonl",
        "section_matches.jsonl",
        "metrics.json",
        "config_snapshot.json",
        "report.md",
    ):
        assert (output / name).is_file(), name

    # Match evidence is serialized: the fixture "Введение" heading satisfies
    # NDV-S01 by exact equality.
    matches = [
        json.loads(x)
        for x in (output / "section_matches.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert matches, "successful matches must be serialized"
    ndv_s01 = [m for m in matches if m["rule_id"] == "NDV-S01"]
    assert ndv_s01 and ndv_s01[0]["method"] == "exact_equality"
    assert ndv_s01[0]["observed_heading"] == "Введение"
    assert ndv_s01[0]["matched_alias"]
    assert "match_id" in ndv_s01[0] and "limitations" in ndv_s01[0]

    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    ablation = metrics["section_matching_ablation"]
    for key in (
        "matched_exact_equality",
        "matched_normalized_substring",
        "matched_token_overlap",
        "matched_fuzzy",
        "rejected_fuzzy_candidates",
    ):
        assert key in ablation
    assert metrics["section_matches_serialized"] == len(matches)
    # FP count single source: list length == count field, report uses the same.
    assert metrics["false_positive_review_candidate_count"] == len(
        metrics["false_positive_review_candidates"]
    )
    report_text = (output / "report.md").read_text(encoding="utf-8")
    assert str(metrics["false_positive_review_candidate_count"]) in report_text

    assert all(f.confidence is None for f in result.findings)


def test_review_template_preserves_human_decisions(curated) -> None:
    result1 = run_p1(_p1_options(curated))
    template = curated["root"] / "data" / "annotations" / "p1_review_template.jsonl"
    rows = [json.loads(x) for x in template.read_text(encoding="utf-8").splitlines()]
    assert rows and all(r["expert_decision"] is None for r in rows)

    # An expert fills one decision.
    rows[0]["expert_decision"] = "confirmed"
    rows[0]["expert_comment"] = "проверено вручную"
    rows[0]["reviewed_at"] = "2026-07-14T10:00:00+00:00"
    rows[0]["reviewer_id"] = "expert-1"
    with template.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    result2 = run_p1(_p1_options(curated))
    merged = [json.loads(x) for x in template.read_text(encoding="utf-8").splitlines()]
    by_id = {r["finding_id"]: r for r in merged}
    preserved = by_id[rows[0]["finding_id"]]
    assert preserved["expert_decision"] == "confirmed"
    assert preserved["expert_comment"] == "проверено вручную"
    assert preserved["reviewer_id"] == "expert-1"
    assert result2.review_template_preserved_decisions == 1
    assert result2.review_template_created is False
    # Same inputs => same stable finding ids => no stale rows.
    assert result2.review_template_stale_rows == 0
    assert len(merged) == len(result1.findings)


def test_stable_finding_ids_across_runs(curated) -> None:
    result1 = run_p1(_p1_options(curated))
    result2 = run_p1(_p1_options(curated))
    assert [f.finding_id for f in result1.findings] == [f.finding_id for f in result2.findings]


def test_cli_smoke(curated) -> None:
    from typer.testing import CliRunner

    from dalel.cli import app

    output = curated["root"] / "data" / "results" / "p1" / "v1"
    runner = CliRunner()
    result = runner.invoke(
        app, ["run-p1", "--dataset", str(curated["dataset"]), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    assert "P1 complete" in result.output
