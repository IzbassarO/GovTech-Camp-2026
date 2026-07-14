"""Document-level structural completeness checks (deterministic)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from dalel.pillars.document_integrity.config import (
    DUPLICATE_HEADING_MIN_OCCURRENCES,
    MIN_EXPECTED_PAGES,
    TABLE_EXPECTED_TYPES,
)
from dalel.pillars.document_integrity.normalization import normalize_title
from dalel.pillars.document_integrity.quality import IdGen, _finding
from dalel.pillars.document_integrity.schemas import Evidence, FindingRecord
from dalel.pillars.document_integrity.section_matcher import (
    HeadingCandidate,
    SectionMatch,
    match_document_sections,
)
from dalel.pillars.document_integrity.taxonomy import SECTION_RULES

_APPENDIX_REF_RE = re.compile(r"приложени\w*\s*№?\s*(\d{1,3})", re.IGNORECASE)


def section_findings(
    document: dict[str, Any],
    headings: list[HeadingCandidate],
    id_gen: IdGen,
) -> tuple[list[FindingRecord], list[SectionMatch]]:
    """missing_expected_section findings + raw matches (evidence/ablation).

    A missing-section finding is created ONLY when no accepted match exists;
    rejected fuzzy candidates are mentioned in the explanation for auditability.
    """
    findings: list[FindingRecord] = []
    document_type = str(document["document_type"])
    rules = SECTION_RULES.get(document_type, [])
    matches = match_document_sections(rules, headings)
    for match in matches:
        if match.matched:
            continue
        rule = match.rule
        rejected_note = ""
        if match.rejected_fuzzy:
            first = match.rejected_fuzzy[0]
            rejected_note = (
                f" Отклонён fuzzy-кандидат «{first.observed_heading}»"
                f" (ratio {first.ratio}): {first.reason}."
            )
        findings.append(
            _finding(
                id_gen,
                str(document["project_id"]),
                str(document["document_id"]),
                "missing_expected_section",
                rule.severity,
                rule.rule_id,
                f"Не найден ожидаемый структурный раздел: «{rule.canonical_section}»",
                "Ни один заголовок не дал accepted match"
                " (exact_equality/normalized_substring/token_overlap/fuzzy;"
                f" лучший score {match.score}).{rejected_note}",
                rule.limitations,
                observed_value="раздел не обнаружен среди заголовков",
                expected_value=f"expected structural section: {rule.canonical_section}"
                + ("" if rule.required else " (recommended)"),
            )
        )
    return findings, matches


def table_and_length_findings(document: dict[str, Any], id_gen: IdGen) -> list[FindingRecord]:
    findings: list[FindingRecord] = []
    project_id = str(document["project_id"])
    document_id = str(document["document_id"])
    document_type = str(document["document_type"])

    if document_type in TABLE_EXPECTED_TYPES and int(document.get("table_records") or 0) == 0:
        findings.append(
            _finding(
                id_gen,
                project_id,
                document_id,
                "missing_expected_tables",
                "medium",
                "P1-DOC-NO-TABLES",
                "Не извлечено ни одной таблицы",
                f"Для документов типа {document_type} структурно ожидаются таблицы"
                " (нормативы, перечни источников/отходов, планы), но в документе"
                " не сериализовано ни одной валидной таблицы.",
                "Таблицы могли не распознаться парсером (скан/качество) — это"
                " кандидат на ручную проверку, а не доказанное отсутствие.",
                observed_value="table_records=0",
                expected_value=">= 1 извлечённая таблица",
            )
        )

    page_count = int(document.get("page_count") or 0)
    minimum = MIN_EXPECTED_PAGES.get(document_type)
    if minimum is not None and page_count < minimum:
        findings.append(
            _finding(
                id_gen,
                project_id,
                document_id,
                "suspicious_document_length",
                "medium",
                "P1-DOC-SHORT",
                "Подозрительно короткий документ",
                f"Документ типа {document_type} содержит {page_count} страниц(ы) при"
                f" структурно ожидаемом минимуме {minimum}.",
                "Минимум выведен из практики корпуса, не является нормативом.",
                observed_value=str(page_count),
                expected_value=f">= {minimum} страниц",
            )
        )
    return findings


def duplicate_heading_findings(
    document: dict[str, Any], section_titles: list[str], id_gen: IdGen
) -> list[FindingRecord]:
    findings: list[FindingRecord] = []
    counts = Counter(normalize_title(title) for title in section_titles if normalize_title(title))
    for normalized, count in sorted(counts.items()):
        if count >= DUPLICATE_HEADING_MIN_OCCURRENCES:
            findings.append(
                _finding(
                    id_gen,
                    str(document["project_id"]),
                    str(document["document_id"]),
                    "duplicate_heading",
                    "info",
                    "P1-DOC-DUP-HEADING",
                    f"Заголовок повторяется {count} раз: «{normalized[:60]}»",
                    "Многократное повторение одного заголовка может указывать на"
                    " дублирование раздела или артефакты распознавания структуры.",
                    "Повторы (оглавление + текст, колонтитулы) частично нормальны;"
                    f" порог {DUPLICATE_HEADING_MIN_OCCURRENCES}+ снижает шум.",
                    observed_value=f"{count} повторов",
                    expected_value=f"< {DUPLICATE_HEADING_MIN_OCCURRENCES}",
                )
            )
    return findings


def structural_anomaly_findings(document: dict[str, Any], id_gen: IdGen) -> list[FindingRecord]:
    findings: list[FindingRecord] = []
    if int(document.get("section_records") or 0) == 0:
        findings.append(
            _finding(
                id_gen,
                str(document["project_id"]),
                str(document["document_id"]),
                "structural_anomaly",
                "medium",
                "P1-DOC-NO-SECTIONS",
                "Не обнаружена структура разделов",
                "Парсер не выделил ни одного заголовка/секции: проверка ожидаемых"
                " разделов для документа невозможна.",
                "Отсутствие распознанных заголовков может быть следствием OCR или"
                " нетипичной вёрстки, а не отсутствия структуры.",
                observed_value="section_records=0",
                expected_value=">= 1 распознанный раздел",
            )
        )
    return findings


def appendix_reference_findings(
    document: dict[str, Any],
    pages: list[dict[str, Any]],
    section_titles: list[str],
    id_gen: IdGen,
) -> list[FindingRecord]:
    """References like «приложение №13» with no appendix heading in the document."""
    findings: list[FindingRecord] = []
    referenced: dict[str, int] = {}
    for page in pages:
        for match in _APPENDIX_REF_RE.finditer(str(page.get("text") or "")):
            number = match.group(1)
            referenced.setdefault(number, int(page.get("page_number") or 0))
    if not referenced:
        return findings

    has_appendix_heading = any(
        "приложени" in normalize_title(title) or "қосымша" in normalize_title(title)
        for title in section_titles
    )
    if has_appendix_heading:
        return findings

    numbers = sorted(referenced, key=int)
    evidence = [
        Evidence(
            document_id=str(document["document_id"]),
            page_number=referenced[number],
            note=f"ссылка на приложение №{number}",
        )
        for number in numbers[:10]
    ]
    findings.append(
        _finding(
            id_gen,
            str(document["project_id"]),
            str(document["document_id"]),
            "missing_appendix_reference",
            "low",
            "P1-DOC-APPENDIX-REF",
            "Ссылки на приложения без обнаруженных заголовков приложений",
            f"В тексте встречаются ссылки на приложения №{', '.join(numbers[:10])}"
            f" (всего {len(numbers)}), но среди распознанных заголовков документа"
            " нет ни одного раздела «Приложение…».",
            "Приложения часто свёрстаны в том же PDF без распознанных заголовков"
            " или поставляются отдельными файлами; это кандидат для ручной"
            " проверки комплектности, а не доказанное отсутствие.",
            evidence=evidence,
            page_references=sorted(set(referenced.values()))[:20],
            observed_value=f"ссылки на {len(numbers)} приложений; заголовков приложений: 0",
            expected_value="заголовки приложений или отдельные файлы приложений",
        )
    )
    return findings
