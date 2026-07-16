"""Exact deterministic explanation helpers (never labelled as SHAP)."""

from __future__ import annotations

from dalel.meta_review.schemas import FeatureContribution

COUNTERFACTUAL = (
    "Чтобы снизить этот балл, необходимо устранить наиболее влиятельные факторы проверки. "
    "Изменение документов ради снижения балла само по себе не доказывает соответствие."
)


def top_positive_factors(
    contributions: list[FeatureContribution], limit: int = 5
) -> list[FeatureContribution]:
    return sorted(
        (item for item in contributions if item.contribution > 0),
        key=lambda item: (
            -item.contribution,
            item.pillar_source,
            item.feature_name,
            item.contribution_id,
        ),
    )[:limit]


def integrated_limitations(missing_pillars: list[str], p2_available: bool) -> list[str]:
    limitations = [
        "Баллы P1–P4 являются ориентирами экспертной проверки, а не юридическими выводами.",
        "Интегральный балл не является вероятностью нарушения или экологического вреда.",
        "Низкий балл не является рекомендацией выдать разрешение или административным решением.",
    ]
    if p2_available:
        limitations.append(
            "Вклад P2 ограничен: используется синтетический демонстрационный нормативный корпус."
        )
    if missing_pillars:
        limitations.append(
            "Недоступные столпы не считаются пройденными: "
            "они отдельно снижают покрытие и уверенность."
        )
    limitations.append(
        "Калибровка и SHAP недоступны без достаточной проверенной экспертной разметки."
    )
    return limitations
