"""Human-readable P4 run report (deterministic, timestamp-free)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dalel.pillars.cross_document_coherence import P4_VERSION

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for typing only
    from dalel.pillars.cross_document_coherence.pipeline import P4RunResult

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def render_p4_report(result: P4RunResult) -> str:
    metrics = result.metrics
    lines: list[str] = [
        f"# P4 Cross-Document Coherence — deterministic baseline (v{P4_VERSION})",
        "",
        "P4 отвечает на вопрос: описывают ли документы одного пакета один и тот же"
        " проект, оператора, объект, местоположение, деятельность и отчётный"
        " период согласованно. Каждое finding — ПОТЕНЦИАЛЬНОЕ расхождение или"
        " диагностика для проверки экспертом, НЕ юридический или административный"
        " вывод. LLM, embeddings, OCR и геоанализ не использовались; вход — только"
        " принятый Curated Dataset v1.",
        "",
        "## Входные данные",
        "",
        f"- Документов проанализировано: {metrics['documents_analyzed']}",
        f"- Проектов: {metrics['projects_analyzed']}",
        f"- Разделов просмотрено (ведущие разделы): {metrics['sections_scanned']}",
        "",
        "## Извлечённые утверждения (claims)",
        "",
        f"- Всего: {metrics['claims_total']}",
    ]
    for attribute, count in sorted(metrics["claims_by_attribute"].items()):
        lines.append(f"  - {attribute}: {count}")

    lines += [
        "",
        "## Граф сущностей",
        "",
        f"- Сущностей: {metrics['entities_total']}",
    ]
    for entity_type, count in sorted(metrics["entities_by_type"].items()):
        lines.append(f"  - {entity_type}: {count}")
    lines += [
        f"- Связей (рёбер): {metrics['edges_total']}",
    ]
    for relation, count in sorted(metrics["edges_by_relation"].items()):
        lines.append(f"  - {relation}: {count}")

    lines += [
        "",
        "## Разрешение идентичности",
        "",
        f"- Решений о разрешении: {metrics['resolution_decisions_total']}",
    ]
    for decision, count in sorted(metrics["resolution_by_decision"].items()):
        lines.append(f"  - {decision}: {count}")
    lines += [
        f"- Связанных документов (подтверждённые межкументные связи):"
        f" {metrics['linked_documents_total']}",
        f"- Неразрешённых сущностей: {metrics['unresolved_entities_total']}",
    ]

    lines += [
        "",
        "## Исключённые сравнения (suppressed)",
        "",
        f"- Всего: {metrics['suppressed_comparisons_total']}",
    ]
    for reason, count in sorted(metrics["suppressed_comparisons_by_reason"].items()):
        lines.append(f"  - {reason}: {count}")

    lines += [
        "",
        "## Findings",
        "",
        f"- Всего: {metrics['findings_total']}",
        f"- Доказанных межкументных противоречий: {metrics['proven_cross_document_conflicts']}",
        f"- По severity: {metrics['findings_by_severity']}",
        "",
        "### По типам",
        "",
    ]
    for finding_type, count in sorted(metrics["findings_by_type"].items()):
        lines.append(f"- {finding_type}: {count}")
    if not metrics["findings_by_type"]:
        lines.append("- находок нет")

    if metrics["proven_cross_document_conflicts"] == 0:
        lines += [
            "",
            "> Доказанных междокументных противоречий не обнаружено. Сопоставления"
            " с недостаточной идентичностью или контекстом были исключены из"
            " выводов. Это не подтверждает корректность документов.",
        ]

    top = sorted(
        result.findings,
        key=lambda f: (
            _SEVERITY_ORDER.get(f.severity, 9),
            f.finding_type,
            f.finding_id,
        ),
    )[:10]
    lines += ["", "### Находки (severity, тип)", ""]
    for finding in top:
        lines.append(f"- [{finding.severity}] {finding.finding_id}: {finding.title}")
    if not top:
        lines.append("- находок нет")

    lines += ["", "## Приоритеты по проектам", ""]
    for project_score in result.project_scores:
        lines.append(
            f"- {project_score.project_id}:"
            f" {project_score.cross_document_coherence_priority_score}"
            f" (сущностей {project_score.entity_count},"
            f" связей {project_score.edge_count},"
            f" связанных документов {project_score.linked_document_count},"
            f" исключено сравнений {project_score.suppressed_comparison_count})"
        )

    lines += [
        "",
        "## Ограничения",
        "",
        "- Конфликт поднимается только из явного несовместимого ИДЕНТИФИКАТОРА или"
        " явного несовместимого структурированного значения при совпадении"
        " сущности и контекста; различия написания, кавычек и транслитерации —"
        " это алиасы, не противоречия.",
        "- Свободный текст адресов и описаний объектов не сравнивается лексически;"
        " неопределённая идентичность остаётся неразрешённой.",
        "- Внутридокументная нумерация источников выбросов не является"
        " межкументным идентификатором объекта.",
        "- P4 не делает юридических, административных выводов и не рассчитывает интегральный риск.",
        "",
        "## Воспроизводимость",
        "",
        "- Повторный запуск на тех же входных данных даёт байт-в-байт те же"
        " артефакты (в файлах P4 нет таймстемпов и абсолютных путей).",
        f"- Конфигурация: p4_version={P4_VERSION},"
        f" scoring={metrics['scoring_config_version']}; см. config_snapshot.json.",
        "- Решения фиксируются в data/annotations/p4_review_template.jsonl"
        " (человеческие поля сохраняются при повторных запусках).",
    ]
    return "\n".join(lines) + "\n"


def summarize_for_cli(metrics: dict[str, Any]) -> str:
    return (
        f"P4 complete: documents={metrics['documents_analyzed']}"
        f" entities={metrics['entities_total']}"
        f" edges={metrics['edges_total']}"
        f" linked_documents={metrics['linked_documents_total']}"
        f" suppressed={metrics['suppressed_comparisons_total']}"
        f" findings={metrics['findings_total']}"
        f" proven_conflicts={metrics['proven_cross_document_conflicts']}"
        f" by_severity={metrics['findings_by_severity']}"
    )
