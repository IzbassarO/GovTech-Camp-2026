"""Concise deterministic Markdown report for integrated review priority."""

from __future__ import annotations

from typing import Any

from dalel.meta_review.schemas import ProjectMetaAssessment

_LEVEL_RU = {
    "low": "низкая",
    "moderate": "умеренная",
    "elevated": "повышенная",
    "high": "высокая",
}


def render_meta_report(assessments: list[ProjectMetaAssessment], metrics: dict[str, Any]) -> str:
    lines = [
        "# Meta Analysis — интегральная приоритетность проверки",
        "",
        (
            "Баллы отвечают на вопрос, какой проектный пакет эксперту следует изучить раньше "
            "по сигналам P1–P4. Это не вероятность нарушения, экологического вреда или "
            "несоответствия и не административное решение."
        ),
        "",
        "## Проекты",
        "",
        "| Порядок | Проект | Балл | Уровень | Покрытие | Уверенность |",
        "|---:|---|---:|---|---:|---:|",
    ]
    ordered = sorted(assessments, key=lambda item: (-item.review_priority_score, item.project_id))
    for index, assessment in enumerate(ordered, start=1):
        lines.append(
            f"| {index} | {assessment.project_id} | {assessment.review_priority_score:.2f} "
            f"| {_LEVEL_RU[assessment.review_priority_level]} "
            f"| {assessment.evidence_coverage:.1%} "
            f"| {assessment.assessment_confidence:.1%} |"
        )

    for assessment in ordered:
        lines.extend(
            [
                "",
                f"## {assessment.project_id}",
                "",
                (
                    f"Итог: **{assessment.review_priority_score:.2f}/100**; "
                    f"покрытие {assessment.evidence_coverage:.1%}; "
                    f"уверенность {assessment.assessment_confidence:.1%}."
                ),
                "",
                "### Точный вклад столпов",
                "",
                "| Столп | До корректировок | Скидка | Ограничение | Итог |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for pillar in assessment.pillar_contributions:
            availability = pillar.pillar_id if pillar.available else f"{pillar.pillar_id} (нет)"
            lines.append(
                f"| {availability} | {pillar.raw_subtotal:.2f} | "
                f"{pillar.discount_amount:.2f} | {pillar.cap_adjustment:.2f} | "
                f"{pillar.subtotal:.2f} |"
            )
        lines.extend(["", "### Наиболее влиятельные факторы", ""])
        if assessment.top_positive_factors:
            for factor in assessment.top_positive_factors:
                refs = ", ".join(factor.source_finding_ids or factor.source_artifact_ids)
                lines.append(
                    f"- {factor.pillar_source} / `{factor.feature_name}`: "
                    f"+{factor.contribution:.2f} — {factor.explanation} Источники: {refs}."
                )
        else:
            lines.append("- Положительные факторы приоритета не сформированы.")
        lines.extend(["", "### Ограничения", ""])
        for limitation in assessment.limitations:
            lines.append(f"- {limitation}")

    lines.extend(
        [
            "",
            "## Калибровка и SHAP",
            "",
            (
                f"Завершённых экспертных меток: {metrics['completed_expert_labels']}. "
                "Калибровка недоступна без достаточной экспертной разметки. "
                "Production calibrated_probability=null и shap_contributions=null."
            ),
            "",
        ]
    )
    return "\n".join(lines)
