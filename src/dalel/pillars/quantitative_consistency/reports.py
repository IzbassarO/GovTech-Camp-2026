"""Human-readable P3 run report (deterministic, timestamp-free)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dalel.pillars.quantitative_consistency import P3_VERSION

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for typing only
    from dalel.pillars.quantitative_consistency.pipeline import P3RunResult

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def render_p3_report(result: P3RunResult) -> str:
    metrics = result.metrics
    lines: list[str] = [
        f"# P3 Quantitative Consistency — deterministic baseline (v{P3_VERSION})",
        "",
        "Каждое finding — ПОТЕНЦИАЛЬНОЕ несоответствие для проверки экспертом,"
        " НЕ вывод о нарушении. LLM, embeddings и OCR в P3 не использовались;"
        " вход — только принятый Curated Dataset v1.",
        "",
        "## Входные данные",
        "",
        f"- Документов проанализировано: {metrics['documents_analyzed']}",
        f"- Проектов: {metrics['projects_analyzed']}",
        "",
        "## Извлечение количественных упоминаний",
        "",
        f"- Упоминаний извлечено: {metrics['mentions_total']}"
        f" (таблицы {metrics['mentions_from_tables']},"
        f" текст {metrics['mentions_from_sections']})",
        f"- С распознанной единицей: {metrics['mentions_with_unit']}"
        f" (inline {metrics['unit_source_inline']},"
        f" из заголовка столбца {metrics['unit_source_column_header']})",
        f"- Подавлено при извлечении (не количества): {metrics['suppressed_numbers_total']}",
    ]
    for reason, count in sorted(metrics["suppressed_numbers_by_reason"].items()):
        examples = metrics["suppressed_examples"].get(reason, [])
        example_text = f" (например: {', '.join(examples[:3])})" if examples else ""
        lines.append(f"  - {reason}: {count}{example_text}")

    lines += [
        "",
        "## Нормализация единиц",
        "",
    ]
    for unit, count in sorted(metrics["mentions_by_canonical_unit"].items()):
        lines.append(f"- {unit}: {count}")

    lines += [
        "",
        "## Кандидаты сравнения",
        "",
        f"- Сравнений выполнено: {metrics['candidates_compared']}",
        f"- Агрегационных проверок (итоги таблиц): {metrics['aggregation_checks_total']}"
        f" (сошлись: {metrics['aggregation_checks_consistent']})",
        f"- Подавлено сравнений (семантика не совпала): {metrics['suppressed_candidates_total']}",
    ]
    for reason, count in sorted(metrics["suppressed_candidates_by_reason"].items()):
        lines.append(f"  - {reason}: {count}")

    lines += [
        "",
        "## Findings",
        "",
        f"- Всего: {metrics['findings_total']}",
        f"- По severity: {metrics['findings_by_severity']}",
        "",
        "### По типам",
        "",
    ]
    for finding_type, count in sorted(metrics["findings_by_type"].items()):
        lines.append(f"- {finding_type}: {count}")

    top = sorted(
        result.findings,
        key=lambda f: (
            _SEVERITY_ORDER.get(f.severity, 9),
            -(f.confidence or 0),
            f.finding_id,
        ),
    )[:10]
    lines += ["", "### Топ-10 находок (severity, затем confidence)", ""]
    for finding in top:
        lines.append(
            f"- [{finding.severity}/conf={finding.confidence}] {finding.finding_id}:"
            f" {finding.title}"
        )
    if not top:
        lines.append("- находок нет")

    lines += ["", "## Приоритеты по документам", ""]
    for document_id, score in sorted(
        metrics["score_distribution"]["documents"].items(), key=lambda kv: (-kv[1], kv[0])
    ):
        lines.append(f"- {document_id}: {score}")

    lines += ["", "## Приоритеты по проектам", ""]
    for project_score in result.project_scores:
        lines.append(
            f"- {project_score.project_id}:"
            f" {project_score.quantitative_consistency_priority_score}"
            f" (cross-document findings: {project_score.package_finding_count})"
        )

    lines += [
        "",
        "## Качество и неоднозначность",
        "",
        f"- Упоминаний с неоднозначным форматом числа: {metrics['mentions_ambiguous']}",
        f"- Упоминаний с OCR-источником: {metrics['mentions_ocr']}",
        f"- Документные стили десятичного разделителя: {metrics['doc_decimal_styles']}",
        "",
        "## Ограничения",
        "",
        "- Сопоставление контекста построено на детерминированных лексиконах"
        " (вещества, метрики, квалификаторы); нераспознанный контекст ведёт к"
        " подавлению сравнения, а не к догадке.",
        "- Переводы между мгновенными (г/с) и годовыми (т/год) величинами не"
        " выполняются: режим работы источника неизвестен.",
        "- «N · 10» с потерянной степенью, коды источников и веществ, годы,"
        " телефоны и реквизиты исключены из количеств (см. диагностику выше).",
        "- OCR-страницы дают пониженную confidence; сами OCR-прогоны в P3 не выполнялись.",
        "",
        "## Воспроизводимость",
        "",
        "- Повторный запуск на тех же входных данных даёт байт-в-байт те же"
        " артефакты (в файлах P3 нет таймстемпов).",
        "- Формулы сравнения и допуски: см. config_snapshot.json;"
        " каждое finding содержит воспроизводимый расчёт.",
        f"- Конфигурация: p3_version={P3_VERSION}, scoring={metrics['scoring_config_version']}.",
        "",
        "## Как работать с находками",
        "",
        "- Решения фиксируются в data/annotations/p3_review_template.jsonl"
        " (человеческие поля сохраняются при повторных запусках).",
        "- confidence — детерминированная оценка надёжности сопоставления,"
        " НЕ вероятностная модель; severity — материальность расхождения.",
    ]
    return "\n".join(lines) + "\n"


def summarize_for_cli(metrics: dict[str, Any]) -> str:
    return (
        f"P3 complete: documents={metrics['documents_analyzed']}"
        f" mentions={metrics['mentions_total']}"
        f" compared={metrics['candidates_compared']}"
        f" findings={metrics['findings_total']}"
        f" by_severity={metrics['findings_by_severity']}"
    )
