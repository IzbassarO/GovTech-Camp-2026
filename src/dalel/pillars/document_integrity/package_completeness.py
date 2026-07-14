"""Package-level checks: composition, metadata and date-range consistency."""

from __future__ import annotations

import re
from typing import Any

from dalel.pillars.document_integrity.config import (
    DATE_RANGE_MAX_YEAR,
    DATE_RANGE_MIN_YEAR,
)
from dalel.pillars.document_integrity.quality import IdGen, _finding
from dalel.pillars.document_integrity.schemas import Evidence, FindingRecord
from dalel.pillars.document_integrity.taxonomy import infer_package_profile

_DATE_RANGE_RE = re.compile(r"(20\d{2})\s*[-–—]\s*(20\d{2})")


def package_findings(
    project: dict[str, Any], documents: list[dict[str, Any]], id_gen: IdGen
) -> tuple[list[FindingRecord], dict[str, Any]]:
    """missing_document findings + profile info for the report."""
    findings: list[FindingRecord] = []
    project_id = str(project["project_id"])
    present_types = {str(d["document_type"]) for d in documents}
    profile = infer_package_profile(present_types)

    for required_type in profile.required_types:
        if required_type not in present_types:
            findings.append(
                _finding(
                    id_gen,
                    project_id,
                    None,
                    "missing_document",
                    "high",
                    f"P1-PKG-{profile.profile_id.upper()}-{required_type.upper()}",
                    f"В пакете отсутствует ожидаемый документ: {required_type}",
                    f"Профиль пакета «{profile.profile_id}» структурно ожидает"
                    f" документ типа {required_type}; в model inputs проекта он"
                    " отсутствует.",
                    profile.limitations,
                    observed_value=f"present: {', '.join(sorted(present_types))}",
                    expected_value=f"required: {', '.join(profile.required_types)}",
                )
            )
    for recommended_type in profile.recommended_types:
        if recommended_type not in present_types:
            findings.append(
                _finding(
                    id_gen,
                    project_id,
                    None,
                    "missing_document",
                    "low",
                    f"P1-PKG-{profile.profile_id.upper()}-{recommended_type.upper()}-REC",
                    f"В пакете нет рекомендуемого документа: {recommended_type}",
                    f"Профиль «{profile.profile_id}» обычно включает {recommended_type}.",
                    profile.limitations,
                    observed_value=f"present: {', '.join(sorted(present_types))}",
                    expected_value=f"recommended: {recommended_type}",
                )
            )

    profile_info = {
        "project_id": project_id,
        "profile_id": profile.profile_id,
        "present_types": sorted(present_types),
        "required_types": list(profile.required_types),
        "missing_required": [t for t in profile.required_types if t not in present_types],
    }
    return findings, profile_info


def metadata_findings(
    project: dict[str, Any], documents: list[dict[str, Any]], id_gen: IdGen
) -> list[FindingRecord]:
    """Deterministic metadata consistency: document vs project language sets."""
    findings: list[FindingRecord] = []
    project_languages = set(project.get("languages") or [])
    for document in documents:
        document_languages = set(document.get("languages") or [])
        if (
            document_languages
            and project_languages
            and not (document_languages <= project_languages)
        ):
            findings.append(
                _finding(
                    id_gen,
                    str(project["project_id"]),
                    str(document["document_id"]),
                    "metadata_inconsistency",
                    "low",
                    "P1-PKG-LANG-MISMATCH",
                    "Языки документа не согласованы с языками проекта",
                    f"Документ заявляет языки {sorted(document_languages)}, проект —"
                    f" {sorted(project_languages)}.",
                    "Языковые метаданные ведутся на уровне проекта; расхождение —"
                    " повод сверить карточку, а не доказанная ошибка.",
                    observed_value=str(sorted(document_languages)),
                    expected_value=str(sorted(project_languages)),
                )
            )
    return findings


def extract_date_ranges(pages: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Distinct plausible year ranges found in a document's text with pages."""
    ranges: dict[str, list[int]] = {}
    for page in pages:
        text = str(page.get("text") or "")
        for match in _DATE_RANGE_RE.finditer(text):
            start, end = int(match.group(1)), int(match.group(2))
            if not (
                DATE_RANGE_MIN_YEAR <= start < end <= DATE_RANGE_MAX_YEAR and end - start <= 15
            ):
                continue
            key = f"{start}-{end}"
            pages_list = ranges.setdefault(key, [])
            number = int(page.get("page_number") or 0)
            if number not in pages_list:
                pages_list.append(number)
    return ranges


def date_range_findings(
    project: dict[str, Any],
    pages_by_document: dict[str, list[dict[str, Any]]],
    id_gen: IdGen,
) -> list[FindingRecord]:
    """Cross-document validity-period candidates (finding, not proven violation).

    Compares the DOMINANT (most frequently mentioned) year range per document
    across the package. Multiple ranges inside one document are normal
    (historical observation periods, baseline data) and are not flagged.
    A portal-vs-local period discrepancy (e.g. the known Sintez Ural
    2025-2034 portal narrative) is NOT detectable from local text alone.
    """
    dominant: dict[str, tuple[str, list[int]]] = {}
    for document_id, pages in pages_by_document.items():
        ranges = extract_date_ranges(pages)
        if not ranges:
            continue
        best_key = max(ranges, key=lambda key: (len(ranges[key]), key))
        dominant[document_id] = (best_key, ranges[best_key])

    distinct = {key for key, _pages in dominant.values()}
    if len(dominant) < 2 or len(distinct) <= 1:
        return []

    evidence = [
        Evidence(
            document_id=document_id,
            page_number=page_numbers[0],
            note=f"доминирующий период {key} (стр. {', '.join(map(str, page_numbers[:5]))})",
        )
        for document_id, (key, page_numbers) in sorted(dominant.items())
    ]

    return [
        _finding(
            id_gen,
            str(project["project_id"]),
            None,
            "date_range_inconsistency",
            "medium",
            "P1-PKG-DATE-RANGE",
            "Документы пакета указывают разные доминирующие периоды: "
            + ", ".join(sorted(distinct)),
            "Доминирующие годовые периоды документов одного пакета не совпадают."
            " Это КАНДИДАТ на проверку версии/актуальности документов, а не"
            " автоматически доказанное нарушение.",
            "Сравниваются только доминирующие периоды по частоте упоминаний;"
            " контекст упоминания regex не различает. Расхождение локального"
            " пакета с порталом (пример Sintez Ural 2025-2034 vs 2026-2035)"
            " локальным текстом не детектируется.",
            evidence=evidence[:12],
            observed_value=f"{len(distinct)} различных доминирующих периодов",
            expected_value="один согласованный период действия пакета",
        )
    ]
