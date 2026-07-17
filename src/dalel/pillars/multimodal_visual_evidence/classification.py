"""Model-assisted visual classification with a conservative decision hierarchy.

Order: (1) deterministic exclusion happens upstream in the asset triage;
(2) duplicates resolve to one representative; (3) zero-shot model
classification over the prompt ensembles; (4) context-based adjustment from
captions/filename hints when the model is undecided; (5) honest ``unknown``
fallback. ``classification_confidence`` is the softmax share of similarity
mass over the label set — an affinity, deliberately NOT a probability that
the label is correct.

The decision layer is a pure function of serialized signals, so the validator
replays it byte-for-byte from the artifacts without re-running the model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from dalel.pillars.multimodal_visual_evidence.config import (
    CAPTION_CLASS_HINTS,
    CONFIDENCE_DECIMALS,
    CONTEXT_ADJUST_MIN_AFFINITY,
    CONTEXT_ADJUST_TOP_K,
    MODEL_MIN_MARGIN,
    MODEL_MIN_TOP_AFFINITY,
    SOFTMAX_TEMPERATURE,
)
from dalel.pillars.multimodal_visual_evidence.schemas import ClassSimilarity


@dataclass
class DecisionInputs:
    """Serialized signals the classification decision depends on."""

    model_available: bool
    similarities: dict[str, float]  # class -> rounded mean-ensemble cosine
    caption: str | None = None
    display_hint: str = ""
    procedural_section: bool = False
    incoming_triage_state: str | None = None


@dataclass
class Decision:
    predicted_class: str
    classification_confidence: float | None
    decision_path: str
    competing: list[ClassSimilarity] = field(default_factory=list)
    deterministic_signals: list[str] = field(default_factory=list)
    context_signals: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def softmax_affinities(similarities: dict[str, float]) -> dict[str, float]:
    """Softmax over rounded cosine similarities with the fixed temperature."""
    if not similarities:
        return {}
    values = {name: SOFTMAX_TEMPERATURE * value for name, value in similarities.items()}
    peak = max(values.values())
    exponentials = {name: math.exp(value - peak) for name, value in values.items()}
    total = sum(exponentials.values())
    return {name: exponentials[name] / total for name in similarities}


def caption_hint_classes(caption: str | None, display_hint: str) -> list[tuple[str, str]]:
    """(hinted_class, signal_tag) pairs from the caption and filename hint."""
    hints: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source_name, text in (("caption", caption), ("filename", display_hint)):
        if not text:
            continue
        lowered = text.casefold()
        for visual_class, keywords in CAPTION_CLASS_HINTS.items():
            if visual_class in seen:
                continue
            if any(keyword in lowered for keyword in keywords):
                seen.add(visual_class)
                hints.append((visual_class, f"{source_name}_hint:{visual_class}"))
    return hints


def _competing(
    similarities: dict[str, float], affinities: dict[str, float]
) -> list[ClassSimilarity]:
    ordered = sorted(
        similarities,
        key=lambda name: (-affinities.get(name, 0.0), name),
    )
    return [
        ClassSimilarity(
            visual_class=name,
            similarity=similarities[name],
            affinity=round(affinities.get(name, 0.0), CONFIDENCE_DECIMALS),
        )
        for name in ordered
    ]


def decide_classification(inputs: DecisionInputs) -> Decision:
    """Pure decision over serialized signals (replayed by the validator)."""
    context_signals: list[str] = []
    if inputs.incoming_triage_state:
        context_signals.append(f"incoming_triage:{inputs.incoming_triage_state}")

    if inputs.procedural_section:
        return Decision(
            predicted_class="procedural_notice",
            classification_confidence=None,
            decision_path="deterministic_supporting",
            competing=(
                _competing(inputs.similarities, softmax_affinities(inputs.similarities))
                if inputs.similarities
                else []
            ),
            deterministic_signals=["procedural_dossier_section"],
            context_signals=sorted(context_signals),
            limitations=[
                "Класс назначен по процедурному разделу досье; модельная"
                " классификация не является решающим сигналом."
            ],
        )

    if not inputs.model_available or not inputs.similarities:
        limitations = (
            ["Мультимодальная модель недоступна; семантический класс не определён."]
            if not inputs.model_available
            else ["Изображение не удалось закодировать моделью; класс не определён."]
        )
        return Decision(
            predicted_class="unknown",
            classification_confidence=None,
            decision_path="unknown_fallback",
            deterministic_signals=[],
            context_signals=sorted(context_signals),
            limitations=limitations,
        )

    affinities = softmax_affinities(inputs.similarities)
    competing = _competing(inputs.similarities, affinities)
    top = competing[0]
    runner_up_affinity = competing[1].affinity if len(competing) > 1 else 0.0
    margin = top.affinity - runner_up_affinity

    if top.affinity >= MODEL_MIN_TOP_AFFINITY and margin >= MODEL_MIN_MARGIN:
        return Decision(
            predicted_class=top.visual_class,
            classification_confidence=round(top.affinity, CONFIDENCE_DECIMALS),
            decision_path="model_zero_shot",
            competing=competing,
            deterministic_signals=[],
            context_signals=sorted(context_signals),
            limitations=[],
        )

    hints = caption_hint_classes(inputs.caption, inputs.display_hint)
    if hints:
        top_k = {entry.visual_class for entry in competing[:CONTEXT_ADJUST_TOP_K]}
        adjustable = [
            (affinities.get(visual_class, 0.0), visual_class, tag)
            for visual_class, tag in hints
            if visual_class in top_k
            and affinities.get(visual_class, 0.0) >= CONTEXT_ADJUST_MIN_AFFINITY
        ]
        if adjustable:
            affinity, visual_class, tag = max(adjustable, key=lambda item: (item[0], item[1]))
            context_signals.append(tag)
            return Decision(
                predicted_class=visual_class,
                classification_confidence=round(affinity, CONFIDENCE_DECIMALS),
                decision_path="context_adjusted",
                competing=competing,
                deterministic_signals=[],
                context_signals=sorted(context_signals),
                limitations=[
                    "Модель не была уверена; класс скорректирован по подписи или"
                    " имени файла и требует подтверждения экспертом."
                ],
            )

    return Decision(
        predicted_class="unknown",
        classification_confidence=None,
        decision_path="unknown_fallback",
        competing=competing,
        deterministic_signals=[],
        context_signals=sorted(context_signals),
        limitations=[
            "Модельная уверенность ниже порога; изображение честно отмечено как неопределённое."
        ],
    )
