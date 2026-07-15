"""Markdown report and CLI summary for P2 (no timestamps — deterministic)."""

from __future__ import annotations

from typing import Any

from dalel.pillars.regulatory_compliance.config import DEMO_CORPUS_WARNING


def render_p2_report(result: Any) -> str:
    metrics = result.metrics
    lines: list[str] = [
        "# P2 — Соответствие регуляторным требованиям (экспертная поддержка)",
        "",
    ]
    if metrics.get("corpus_demo_only"):
        lines += [
            f"> **ВНИМАНИЕ.** {DEMO_CORPUS_WARNING}",
            "> Оценки выполнены по синтетическому демонстрационному корпусу"
            " требований; выводы о соответствии законодательству Республики"
            " Казахстан из этого отчёта делать нельзя.",
            "",
        ]
    lines += [
        "P2 не делает юридических выводов: каждая запись — кандидат на"
        " экспертную проверку, а не утверждение о нарушении или"
        " соответствии закону.",
        "",
        "## Сводка",
        "",
        f"- Проектов проанализировано: {metrics['projects_analyzed']}",
        f"- Документов: {metrics['documents_analyzed']}",
        f"- Требований в корпусе: {metrics['requirements_total']}"
        f" (авторитетных: {metrics['requirements_authoritative']},"
        f" демо: {metrics['requirements_demo_only']})",
        f"- Запросов ретривала: {metrics['queries_total']};"
        f" записей ретривала: {metrics['retrievals_total']}",
        f"- Оценок (проект × требование): {metrics['assessments_total']}",
        f"- Меток: {metrics['assessments_by_label']}",
        f"- Находок: {metrics['findings_total']} по серьёзности: {metrics['findings_by_severity']}",
        f"- Механизм вывода: {metrics['assessments_by_engine']}",
        "",
        "## Находки по типам",
        "",
    ]
    for finding_type, count in sorted(metrics.get("findings_by_type", {}).items()):
        lines.append(f"- `{finding_type}`: {count}")
    lines += [
        "",
        "## Ограничения",
        "",
        "- Метки основаны на лексических свидетельствах куративного набора;"
        " отсутствие совпадения не доказывает отсутствие содержания (OCR,"
        " синонимия).",
        "- Применимость нормы к объекту подтверждает только эксперт.",
        "- Количественные пороги не сопоставляются с проектными значениями"
        " в детерминированной базовой проверке.",
    ]
    if metrics.get("corpus_demo_only"):
        lines.append(
            "- Корпус синтетический: высокая серьёзность запрещена, находки"
            " не ссылаются на действующие правовые акты."
        )
    lines.append("")
    return "\n".join(lines)


def summarize_for_cli(metrics: dict[str, Any]) -> str:
    parts = [
        f"P2 complete: projects={metrics['projects_analyzed']}",
        f"requirements={metrics['requirements_total']}",
        f"assessments={metrics['assessments_total']}",
        f"findings={metrics['findings_total']}",
        f"by_severity={metrics['findings_by_severity']}",
    ]
    return " ".join(parts)
