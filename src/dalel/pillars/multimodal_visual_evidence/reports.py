"""Deterministic Russian Markdown report and CLI summary for P5."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dalel.pillars.multimodal_visual_evidence.config import RUSSIAN_CLASS_LABELS

if TYPE_CHECKING:
    from dalel.pillars.multimodal_visual_evidence.pipeline import P5RunResult

_TRIAGE_LABELS = {
    "analyzed_representative": "Анализируемые представители",
    "excluded_duplicate": "Исключённые дубликаты",
    "excluded_low_information": "Малоинформативные растры",
    "excluded_repeated_header": "Повторяемые текстовые колонтитулы",
    "excluded_logo_or_branding": "Логотипы и оформление",
    "unsupported": "Без пригодных байтов",
}

_SEVERITY_LABELS = {"high": "высокая", "medium": "средняя", "low": "низкая", "info": "инфо"}


def render_p5_report(result: P5RunResult) -> str:
    from dalel.pillars.multimodal_visual_evidence import P5_VERSION

    metrics = result.metrics
    lines: list[str] = []
    lines.append(f"# P5 Multimodal Visual Evidence — отчёт (v{P5_VERSION})")
    lines.append("")
    lines.append(
        "Мультимодальный анализ визуальных материалов: инвентаризация с"
        " провенансом, подавление дубликатов, модельная классификация, OCR и"
        " кросс-модальные проверки. Результат — приоритет проверки визуальных"
        " доказательств, а НЕ вероятность экологического вреда, соответствия"
        " законодательству или подлинности изображений."
    )
    lines.append("")
    lines.append("## Входные данные")
    lines.append(f"- Проектов: {metrics.get('projects_analyzed', 0)}")
    lines.append(f"- Документов: {metrics.get('documents_analyzed', 0)}")
    lines.append(f"- Визуальных активов: {len(result.assets)}")
    fingerprint = metrics.get("input_fingerprint")
    lines.append(f"- Отпечаток входного набора: {fingerprint or 'недоступен'}")
    lines.append(f"- Статус модели: {metrics.get('model_status', 'unavailable')}")
    lines.append("")
    lines.append("## Триаж активов")
    by_triage: dict[str, int] = metrics.get("assets_by_triage_status", {})
    for status, count in sorted(by_triage.items()):
        lines.append(f"- {_TRIAGE_LABELS.get(status, status)}: {count}")
    lines.append("")
    lines.append("## Кластеры дубликатов")
    lines.append(f"- Всего кластеров: {len(result.clusters)}")
    by_kind: dict[str, int] = metrics.get("duplicate_clusters_by_kind", {})
    kind_labels = {
        "exact_duplicate": "точные дубликаты",
        "near_duplicate": "перцептивные почти-дубликаты",
        "repeated_text_header": "повторяемые текстовые колонтитулы",
        "logo_or_branding": "логотипы/оформление",
    }
    for kind, count in sorted(by_kind.items()):
        lines.append(f"- {kind_labels.get(kind, kind)}: {count}")
    largest = sorted(result.clusters, key=lambda c: (-c.member_count, c.cluster_id))[:5]
    if largest:
        lines.append("")
        lines.append("Крупнейшие кластеры:")
        for cluster in largest:
            repeated = (
                f" — повторяемый текст: «{cluster.repeated_ocr_text}»"
                if cluster.repeated_ocr_text
                else ""
            )
            lines.append(
                f"- {cluster.cluster_id}: {cluster.member_count} вхождений,"
                f" тип {kind_labels.get(cluster.kind, cluster.kind)},"
                f" представитель {cluster.representative_asset_id}{repeated}"
            )
    lines.append("")
    lines.append("## Классификация представителей")
    by_class: dict[str, int] = metrics.get("classifications_by_class", {})
    for name, count in sorted(by_class.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {RUSSIAN_CLASS_LABELS.get(name, name)}: {count}")
    lines.append("")
    lines.append("## OCR и контекст")
    ocr_status: dict[str, int] = metrics.get("ocr_by_status", {})
    for status, count in sorted(ocr_status.items()):
        lines.append(f"- OCR {status}: {count}")
    lines.append(f"- С подписью на странице: {metrics.get('contexts_with_caption', 0)}")
    lines.append(f"- С пересечением сущностей P4: {metrics.get('contexts_with_entity_overlap', 0)}")
    lines.append("")
    lines.append("## Findings")
    lines.append(f"- Всего: {len(result.findings)}")
    by_severity: dict[str, int] = metrics.get("findings_by_severity", {})
    for severity in ("medium", "low", "info"):
        if severity in by_severity:
            lines.append(f"- Серьёзность {_SEVERITY_LABELS[severity]}: {by_severity[severity]}")
    if not result.findings:
        lines.append(
            "- Кросс-модальные проверки не выявили сигналов для приоритетной"
            " проверки. Это НЕ подтверждает корректность визуальных материалов."
        )
    top = sorted(
        result.findings,
        key=lambda f: (
            {"high": 0, "medium": 1, "low": 2, "info": 3}.get(f.severity, 9),
            f.finding_type,
            f.finding_id,
        ),
    )[:10]
    for finding in top:
        location = finding.document_id or "пакет документов"
        lines.append(
            f"- [{_SEVERITY_LABELS.get(finding.severity, finding.severity)}]"
            f" {finding.title} ({location})"
        )
    lines.append("")
    lines.append("## Подавленные проверки (suppressions)")
    lines.append(f"- Всего: {len(result.suppressions)}")
    by_reason: dict[str, int] = metrics.get("suppressions_by_reason", {})
    for reason, count in sorted(by_reason.items()):
        lines.append(f"- {reason}: {count}")
    lines.append("")
    lines.append("## Приоритеты по проектам")
    for score in sorted(result.project_scores, key=lambda s: s.project_id):
        coverage = f"{score.visual_coverage:.3f}" if score.visual_coverage is not None else "н/д"
        lines.append(
            f"- {score.project_id}: приоритет {score.visual_evidence_review_priority_score},"
            f" активов {score.total_asset_count},"
            f" представителей {score.analyzed_representative_count},"
            f" дубликатов исключено {score.excluded_duplicate_count},"
            f" покрытие {coverage},"
            f" уверенность {score.assessment_confidence:.2f}"
        )
    lines.append("")
    lines.append("## Ограничения")
    lines.append(
        "- Модельная классификация — аффинность по сходству эмбеддингов;"
        " она требует подтверждения экспертом и не доказывает содержание."
    )
    lines.append(
        "- Низкое сходство изображения с текстом — сигнал для проверки,"
        " а не доказанное противоречие."
    )
    lines.append(
        "- OCR ограничен по качеству на мелких шрифтах и рукописном тексте;"
        " отсутствие текста в OCR не означает его отсутствия на изображении."
    )
    lines.append(
        "- Оцифровка значений графиков не выполняется; сверка чисел с P3"
        " ограничена контекстными сигналами."
    )
    lines.append(
        "- P5 не входит в интегральную оценку Meta v1"
        " (meta_integration_status = pending_p6_meta_v2)."
    )
    lines.append("")
    lines.append("## Воспроизводимость")
    lines.append(
        "- Идентификаторы производны от содержимого; артефакты не содержат"
        " временных меток и абсолютных путей; решения классификации"
        " воспроизводятся из сохранённых модельных сигналов (`dalel validate-p5`)."
    )
    return "\n".join(lines) + "\n"


def summarize_for_cli(metrics: dict[str, Any]) -> str:
    per_project: dict[str, dict[str, Any]] = metrics.get("per_project", {})
    priorities = ", ".join(
        f"{project}={values.get('review_priority')}"
        for project, values in sorted(per_project.items())
    )
    return (
        f"P5 complete: assets={metrics.get('assets_total', 0)}"
        f" representatives={metrics.get('analyzed_representatives', 0)}"
        f" clusters={metrics.get('duplicate_clusters_total', 0)}"
        f" findings={metrics.get('findings_total', 0)}"
        f" model={metrics.get('model_status', 'unavailable')}"
        f" priorities=[{priorities}]"
    )
