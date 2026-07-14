"""Page/OCR quality checks (deterministic)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dalel.pillars.document_integrity.config import (
    HIGH_OCR_DEPENDENCY_RATIO,
    LOW_TEXT_COVERAGE_RATIO,
    MIN_USABLE_CHARS_PER_PAGE,
    SEVERITY_POINTS,
)
from dalel.pillars.document_integrity.schemas import Evidence, FindingRecord

IdGen = Callable[[], str]


def _finding(
    id_gen: IdGen,
    project_id: str,
    document_id: str | None,
    finding_type: str,
    severity: str,
    rule_id: str,
    title: str,
    explanation: str,
    limitations: str,
    evidence: list[Evidence] | None = None,
    page_references: list[int] | None = None,
    observed_value: str | None = None,
    expected_value: str | None = None,
) -> FindingRecord:
    return FindingRecord(
        finding_id=id_gen(),
        project_id=project_id,
        document_id=document_id,
        finding_type=finding_type,
        severity=severity,
        priority_score=SEVERITY_POINTS[severity],
        confidence=None,
        rule_id=rule_id,
        title=title,
        explanation=explanation,
        evidence=evidence or [],
        page_references=page_references or [],
        observed_value=observed_value,
        expected_value=expected_value,
        limitations=limitations,
        review_status="pending",
    )


def quality_findings(
    document: dict[str, Any], pages: list[dict[str, Any]], id_gen: IdGen
) -> list[FindingRecord]:
    findings: list[FindingRecord] = []
    project_id = str(document["project_id"])
    document_id = str(document["document_id"])
    page_count = len(pages)
    if page_count == 0:
        return findings

    empty_pages = [p for p in pages if int(p.get("char_count") or 0) == 0]
    near_empty_pages = [
        p for p in pages if 0 < int(p.get("char_count") or 0) < MIN_USABLE_CHARS_PER_PAGE
    ]

    for page in empty_pages:
        number = int(page.get("page_number") or 0)
        findings.append(
            _finding(
                id_gen,
                project_id,
                document_id,
                "empty_page",
                "low",
                "P1-QUAL-EMPTY-PAGE",
                f"Пустая страница {number}",
                "Страница не содержит извлечённого текста (char_count=0).",
                "Страница может содержать только графику/карту; пустота текстового"
                " слоя не доказывает отсутствие содержимого.",
                evidence=[Evidence(document_id=document_id, page_number=number)],
                page_references=[number],
                observed_value="char_count=0",
                expected_value=f">= {MIN_USABLE_CHARS_PER_PAGE} символов",
            )
        )

    low_pages = empty_pages + near_empty_pages
    ratio = len(low_pages) / page_count
    if ratio > LOW_TEXT_COVERAGE_RATIO:
        numbers = sorted(int(p.get("page_number") or 0) for p in low_pages)
        findings.append(
            _finding(
                id_gen,
                project_id,
                document_id,
                "low_text_coverage",
                "medium",
                "P1-QUAL-LOW-COVERAGE",
                "Низкое текстовое покрытие документа",
                f"{len(low_pages)} из {page_count} страниц ({ratio:.0%}) содержат"
                f" менее {MIN_USABLE_CHARS_PER_PAGE} символов текста.",
                "Высокая доля страниц-схем/сканов снижает извлекаемость, но не"
                " доказывает неполноту документа.",
                evidence=[Evidence(document_id=document_id, page_number=n) for n in numbers[:10]],
                page_references=numbers,
                observed_value=f"{ratio:.2f}",
                expected_value=f"<= {LOW_TEXT_COVERAGE_RATIO}",
            )
        )

    ocr = document.get("ocr") or {}
    ocr_pages = int(ocr.get("ocr_page_count") or 0)
    ocr_ratio = ocr_pages / page_count
    if ocr_ratio > HIGH_OCR_DEPENDENCY_RATIO:
        findings.append(
            _finding(
                id_gen,
                project_id,
                document_id,
                "high_ocr_dependency",
                "low",
                "P1-QUAL-OCR-DEP",
                "Высокая зависимость от OCR",
                f"{ocr_pages} из {page_count} страниц ({ocr_ratio:.0%}) получены"
                " через OCR: текстовые проверки для них менее надёжны.",
                "OCR-текст пригоден для анализа, но с повышенным риском ошибок"
                " распознавания; это признак качества источника, не нарушение.",
                observed_value=f"{ocr_ratio:.2f}",
                expected_value=f"<= {HIGH_OCR_DEPENDENCY_RATIO}",
            )
        )
    return findings
