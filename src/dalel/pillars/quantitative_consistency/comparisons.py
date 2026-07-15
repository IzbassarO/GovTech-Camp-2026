"""Comparison rules over matched pairs + single-mention sanity checks.

Documented mismatch condition (also in config_snapshot.json)::

    abs_diff > max(absolute_tolerance, rounding_tolerance)
    AND rel_diff > relative_tolerance

``rel_diff = abs_diff / max(|a|, |b|)`` — symmetric and zero-safe. When the
reference side is exactly zero the relative difference is undefined; the
mismatch then requires ``abs_diff`` above a stricter zero-case gate.
Approximate values widen the relative tolerance instead of being treated
as exact. Rounding tolerance is the worst-case display-rounding error:
``0.5 * (quantum_a + quantum_b)`` in canonical units.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dalel.pillars.quantitative_consistency.config import (
    APPROX_REL_MULTIPLIER,
    DEFAULT_ABS_TOLERANCE,
    DIRECT_ABS_TOLERANCE,
    DIRECT_REL_TOLERANCE,
    PERCENT_ABS_TOLERANCE_PP,
    PERCENT_SHARE_EPSILON,
    ZERO_CASE_ABS_MULTIPLIER,
)
from dalel.pillars.quantitative_consistency.extractor import PercentTriple
from dalel.pillars.quantitative_consistency.matcher import ComparablePair
from dalel.pillars.quantitative_consistency.number_parser import decimal_str
from dalel.pillars.quantitative_consistency.schemas import (
    ComparisonDetail,
    ConfidenceFactor,
    ConversionDetail,
    P3Evidence,
    P3FindingRecord,
    QuantMention,
    deterministic_id,
)
from dalel.pillars.quantitative_consistency.scoring import (
    cap_severity,
    finding_confidence,
    high_severity_eligible,
    points_for,
    severity_for_conflict,
)

_REVIEW_NOTE = (
    "Это ПОТЕНЦИАЛЬНОЕ несоответствие, требующее проверки экспертом;"
    " вывод о нарушении или недостоверности документа не делается."
)

_AMBIGUOUS_FINDINGS_PER_DOCUMENT = 5


@dataclass
class ToleranceEval:
    abs_diff: Decimal
    rel_diff: Decimal | None
    abs_tolerance: Decimal
    rel_tolerance: Decimal
    rounding_tolerance: Decimal
    mismatch: bool


def _abs_tolerance_for(kind: str) -> Decimal:
    return DIRECT_ABS_TOLERANCE.get(kind, DEFAULT_ABS_TOLERANCE)


def evaluate_tolerance(
    a: Decimal,
    b: Decimal,
    quantum_a: Decimal,
    quantum_b: Decimal,
    dimension_kind: str,
    approximate: bool,
) -> ToleranceEval:
    abs_diff = abs(a - b)
    rounding_tolerance = (quantum_a + quantum_b) * Decimal("0.5")
    abs_tolerance = _abs_tolerance_for(dimension_kind)
    rel_tolerance = DIRECT_REL_TOLERANCE * (APPROX_REL_MULTIPLIER if approximate else Decimal(1))
    denominator = max(abs(a), abs(b))
    if denominator == 0:
        return ToleranceEval(
            abs_diff, None, abs_tolerance, rel_tolerance, rounding_tolerance, mismatch=False
        )
    if a == 0 or b == 0:
        gate = max(abs_tolerance * ZERO_CASE_ABS_MULTIPLIER, rounding_tolerance)
        return ToleranceEval(
            abs_diff, None, gate, rel_tolerance, rounding_tolerance, mismatch=abs_diff > gate
        )
    rel = abs_diff / denominator
    mismatch = abs_diff > max(abs_tolerance, rounding_tolerance) and rel > rel_tolerance
    return ToleranceEval(
        abs_diff, rel, abs_tolerance, rel_tolerance, rounding_tolerance, mismatch=mismatch
    )


def _mention_note(mention: QuantMention) -> str:
    loc = mention.location
    if loc.source_kind == "table_cell":
        return f"таблица {loc.table_id}, строка {loc.row}, столбец {loc.col}"
    return f"раздел {loc.section_id}" + (f" («{loc.section_title}»)" if loc.section_title else "")


def _evidence_for(mentions: list[QuantMention]) -> list[P3Evidence]:
    return [
        P3Evidence(
            document_id=m.document_id,
            page_number=m.location.page_number,
            quote=m.raw_text[:200],
            note=_mention_note(m),
        )
        for m in mentions
    ]


def _pages_for(mentions: list[QuantMention]) -> list[int]:
    return sorted({m.location.page_number for m in mentions if m.location.page_number})


def _conversion_for(mention: QuantMention) -> ConversionDetail:
    raw = mention.raw_number + (f" {mention.unit_raw}" if mention.unit_raw else "")
    if mention.unit_source == "column_header" and mention.unit_canonical:
        raw += f" [{mention.unit_canonical} из заголовка столбца]"
    return ConversionDetail(
        mention_id=mention.mention_id,
        raw=raw,
        parsed_value=mention.value or mention.value_low or "",
        unit=mention.unit_canonical,
        conversion_factor=mention.conversion_factor,
        canonical_value=mention.canonical_value or mention.canonical_low,
        canonical_unit=mention.canonical_unit,
    )


def _finding_id(
    project_id: str, document_id: str | None, finding_type: str, rule_id: str, *parts: str
) -> str:
    return deterministic_id(
        "P3", project_id, document_id or "__package__", finding_type, rule_id, *parts
    )


def _semantic_rationale(pair: ComparablePair) -> str:
    compat = pair.compatibility
    unknown_note = (
        f" Не установлены измерения: {', '.join(pair.unknown_dimensions)}"
        " — severity ограничена, сопоставление является ориентиром для"
        " проверки, а не установленным противоречием."
        if pair.unknown_dimensions
        else " Все семантические измерения установлены положительно."
    )
    return (
        f"Сопоставление признано корректным: размерность {compat['dimension']},"
        f" вещество/объект {compat['substance']}, метрика {compat['metric_group']},"
        f" период {compat['period']}, источник {compat['source']},"
        f" под-объект {compat.get('sub_entity', '(n/a)')},"
        f" охват {compat['scope']}, квалификаторы {compat['qualifiers']}."
        f"{unknown_note}"
    )


def compare_pair(pair: ComparablePair) -> P3FindingRecord | None:
    """Rules A/B (direct + equivalent-unit) and F (bounds) for one pair."""
    if pair.rule == "direct":
        return _compare_direct(pair)
    return _compare_bound(pair)


def _dimension_kind(mention: QuantMention) -> str:
    return (mention.dimension or "").split("/")[0]


def _compare_direct(pair: ComparablePair) -> P3FindingRecord | None:
    a, b = pair.a, pair.b
    value_a = Decimal(a.canonical_value or "0")
    value_b = Decimal(b.canonical_value or "0")
    quantum_a = Decimal(a.canonical_quantum or a.display_quantum)
    quantum_b = Decimal(b.canonical_quantum or b.display_quantum)
    approximate = a.modifier == "approximate" or b.modifier == "approximate"
    kind = _dimension_kind(a)
    evaluation = evaluate_tolerance(value_a, value_b, quantum_a, quantum_b, kind, approximate)
    if not evaluation.mismatch:
        return None

    same_unit = a.unit_canonical == b.unit_canonical
    finding_type = "direct_value_conflict" if same_unit else "equivalent_unit_conflict"
    rule_id = "P3-DIRECT" if same_unit else "P3-EQUIV-UNIT"
    document_id = a.document_id if a.document_id == b.document_id else None
    confidence, factors = finding_confidence(finding_type, [a, b], pair.confidence_factors)
    severity = severity_for_conflict(
        evaluation.rel_diff, max(abs(value_a), abs(value_b)), kind, confidence
    )
    # Tri-state gates: any UNKNOWN semantic dimension (period, qualifiers,
    # sub-entity, facility …) means the comparison is a review cue, never a
    # medium/high contradiction; HIGH additionally needs full positive
    # establishment and reliable extraction.
    if pair.unknown_dimensions:
        severity = cap_severity(severity, "low")
    if severity == "high" and not high_severity_eligible(pair.dimension_states, [a, b]):
        severity = "medium"
    subject = pair.compatibility["substance"]
    if subject == "(not identified)":
        subject = pair.compatibility["metric_group"]
    if same_unit:
        title = (
            f"Расхождение значений: {subject} — {a.raw_number} vs {b.raw_number} {a.unit_canonical}"
        )
    else:
        title = (
            f"Расхождение значений: {subject} — {a.raw_number} {a.unit_canonical}"
            f" vs {b.raw_number} {b.unit_canonical}"
            f" (в {a.canonical_unit}: {decimal_str(value_a)} vs {decimal_str(value_b)})"
        )
    rel_text = (
        f"{decimal_str((evaluation.rel_diff * 100).quantize(Decimal('0.1')))}%"
        if evaluation.rel_diff is not None
        else "не определена (одно из значений равно нулю)"
    )
    explanation = (
        f"Одна и та же величина заявлена по-разному: {a.raw_number}"
        f" {a.unit_canonical or ''} ({_mention_note(a)}) и {b.raw_number}"
        f" {b.unit_canonical or ''} ({_mention_note(b)})."
        f" После приведения к канонической единице {a.canonical_unit}:"
        f" {decimal_str(value_a)} vs {decimal_str(value_b)};"
        f" абсолютная разница {decimal_str(evaluation.abs_diff)},"
        f" относительная {rel_text}."
        f" Порог: abs_diff > max({decimal_str(evaluation.abs_tolerance)},"
        f" {decimal_str(evaluation.rounding_tolerance)} округление)"
        f" и rel_diff > {decimal_str(evaluation.rel_tolerance)}. {_REVIEW_NOTE}"
    )
    quality_flags = sorted({*a.flags, *b.flags})
    return P3FindingRecord(
        finding_id=_finding_id(
            a.project_id, document_id, finding_type, rule_id, a.mention_id, b.mention_id
        ),
        project_id=a.project_id,
        document_id=document_id,
        finding_type=finding_type,
        severity=severity,
        priority_score=points_for(severity),
        confidence=confidence,
        confidence_factors=factors,
        rule_id=rule_id,
        title=title,
        explanation=explanation,
        evidence=_evidence_for([a, b]),
        page_references=_pages_for([a, b]),
        mention_ids=sorted([a.mention_id, b.mention_id]),
        candidate_id=pair.candidate_id,
        comparison=ComparisonDetail(
            formula=(
                "mismatch <=> |a-b| > max(abs_tol, rounding_tol) AND |a-b|/max(|a|,|b|) > rel_tol"
            ),
            expected_value=decimal_str(value_a),
            observed_value=decimal_str(value_b),
            abs_diff=decimal_str(evaluation.abs_diff),
            rel_diff=(
                decimal_str(evaluation.rel_diff.quantize(Decimal("0.000001")))
                if evaluation.rel_diff is not None
                else None
            ),
            tolerance_abs=decimal_str(evaluation.abs_tolerance),
            tolerance_rel=decimal_str(evaluation.rel_tolerance),
            rounding_tolerance=decimal_str(evaluation.rounding_tolerance),
            canonical_unit=a.canonical_unit,
            conversions=[_conversion_for(a), _conversion_for(b)],
        ),
        semantic_rationale=_semantic_rationale(pair),
        observed_value=f"{decimal_str(value_b)} {b.canonical_unit}",
        expected_value=f"{decimal_str(value_a)} {a.canonical_unit}",
        quality_flags=quality_flags,
        limitations=(
            "Semantic alignment построен на детерминированных лексиконах;"
            " контекст (сценарий, площадка, режим работы) мог быть распознан"
            " неполностью — требуется подтверждение эксперта."
        ),
    )


def _compare_bound(pair: ComparablePair) -> P3FindingRecord | None:
    bound, observed = pair.a, pair.b
    if observed.canonical_value is None:
        return None
    value = Decimal(observed.canonical_value)
    quantum_observed = Decimal(observed.canonical_quantum or observed.display_quantum)
    kind = _dimension_kind(bound)
    abs_tolerance = _abs_tolerance_for(kind)

    violations: list[tuple[str, Decimal, Decimal]] = []  # (side, limit, excess)
    if bound.kind == "range":
        low = Decimal(bound.canonical_low or "0")
        high = Decimal(bound.canonical_high or "0")
        quantum_bound = Decimal(bound.canonical_quantum or bound.display_quantum)
        tolerance = max(abs_tolerance, (quantum_bound + quantum_observed) * Decimal("0.5"))
        if value > high + tolerance:
            violations.append(("выше верхней границы", high, value - high))
        elif value < low - tolerance:
            violations.append(("ниже нижней границы", low, low - value))
    else:
        limit = Decimal(bound.canonical_value or "0")
        quantum_bound = Decimal(bound.canonical_quantum or bound.display_quantum)
        tolerance = max(abs_tolerance, (quantum_bound + quantum_observed) * Decimal("0.5"))
        if bound.modifier == "upper_bound" and value > limit + tolerance:
            violations.append(("выше заявленного максимума", limit, value - limit))
        elif bound.modifier == "lower_bound" and value < limit - tolerance:
            violations.append(("ниже заявленного минимума", limit, limit - value))
    if not violations:
        return None
    side, limit, excess = violations[0]
    rel = excess / abs(limit) if limit != 0 else None
    if rel is not None and rel <= DIRECT_REL_TOLERANCE:
        return None  # noise-level excess

    document_id = bound.document_id if bound.document_id == observed.document_id else None
    confidence, factors = finding_confidence(
        "bound_violation", [bound, observed], pair.confidence_factors
    )
    severity = severity_for_conflict(rel, max(abs(value), abs(limit)), kind, confidence)
    severity = cap_severity(severity, "medium")  # bound linkage is contextual
    if pair.unknown_dimensions:
        severity = cap_severity(severity, "low")
    boundary_kind = (
        ("включительно" if bound.bound_inclusive else "строго")
        if bound.kind == "scalar"
        else "диапазон"
    )
    subject = pair.compatibility["substance"]
    title = (
        f"Значение вне заявленного ограничения: {subject},"
        f" {observed.canonical_unit} ({decimal_str(value)} {side})"
    )
    explanation = (
        f"Заявленное ограничение: {bound.raw_number} {bound.unit_canonical or ''}"
        f" ({boundary_kind}; {_mention_note(bound)}), фактическое значение"
        f" {observed.raw_number} {observed.unit_canonical or ''}"
        f" ({_mention_note(observed)})."
        f" В канонических единицах {bound.canonical_unit}: ограничение"
        f" {decimal_str(limit)}, значение {decimal_str(value)},"
        f" превышение {decimal_str(excess)}"
        + (f" ({decimal_str((rel * 100).quantize(Decimal('0.1')))}%)." if rel is not None else ".")
        + f" Допуск: {decimal_str(tolerance)} (округление + абсолютный порог)."
        f" {_REVIEW_NOTE}"
    )
    return P3FindingRecord(
        finding_id=_finding_id(
            bound.project_id,
            document_id,
            "bound_violation",
            "P3-BOUND",
            bound.mention_id,
            observed.mention_id,
        ),
        project_id=bound.project_id,
        document_id=document_id,
        finding_type="bound_violation",
        severity=severity,
        priority_score=points_for(severity),
        confidence=confidence,
        confidence_factors=factors,
        rule_id="P3-BOUND",
        title=title,
        explanation=explanation,
        evidence=_evidence_for([bound, observed]),
        page_references=_pages_for([bound, observed]),
        mention_ids=sorted([bound.mention_id, observed.mention_id]),
        candidate_id=pair.candidate_id,
        comparison=ComparisonDetail(
            formula=(
                "violation <=> observed > limit + tol (upper)"
                " / observed < limit - tol (lower); tol = max(abs_tol, rounding_tol)"
            ),
            expected_value=decimal_str(limit),  # violated boundary, canonical
            observed_value=decimal_str(value),
            abs_diff=decimal_str(excess),
            rel_diff=(decimal_str(rel.quantize(Decimal("0.000001"))) if rel is not None else None),
            tolerance_abs=decimal_str(abs_tolerance),
            tolerance_rel=decimal_str(DIRECT_REL_TOLERANCE),
            rounding_tolerance=decimal_str((quantum_bound + quantum_observed) * Decimal("0.5")),
            canonical_unit=bound.canonical_unit,
            conversions=[_conversion_for(bound), _conversion_for(observed)],
        ),
        semantic_rationale=_semantic_rationale(pair),
        observed_value=f"{decimal_str(value)} {observed.canonical_unit}",
        expected_value=f"{side}: {decimal_str(limit)} {bound.canonical_unit}",
        quality_flags=sorted({*bound.flags, *observed.flags}),
        limitations=(
            "Связь «ограничение — фактическое значение» установлена по"
            " совпадению контекста, а не по явной ссылке в тексте;"
            " эксперт должен подтвердить применимость ограничения."
        ),
    )


def percent_triple_findings(triples: list[PercentTriple]) -> list[P3FindingRecord]:
    """Rule D: explicit «N из M (P%)» statements recomputed."""
    findings: list[P3FindingRecord] = []
    for triple in sorted(triples, key=lambda t: t.mention_ids):
        if triple.denominator == 0:
            continue
        expected = (triple.numerator / triple.denominator * 100).quantize(Decimal("0.000001"))
        tolerance = PERCENT_ABS_TOLERANCE_PP + triple.percent_quantum * Decimal("0.5")
        diff = abs(expected - triple.percent)
        if diff <= tolerance:
            continue
        project_id = triple.project_id
        confidence, factors = finding_confidence(
            "percentage_mismatch",
            [],
            [("ocr_source", -0.15)] if triple.ocr_source else [],
        )
        severity = "low" if diff <= Decimal("5") else "medium"
        if confidence < 0.5:
            severity = "low"
        findings.append(
            P3FindingRecord(
                finding_id=_finding_id(
                    project_id,
                    triple.document_id,
                    "percentage_mismatch",
                    "P3-PCT-TRIPLE",
                    *triple.mention_ids,
                ),
                project_id=project_id,
                document_id=triple.document_id,
                finding_type="percentage_mismatch",
                severity=severity,
                priority_score=points_for(severity),
                confidence=confidence,
                confidence_factors=factors,
                rule_id="P3-PCT-TRIPLE",
                title=(
                    f"Процент не совпадает с расчётом: заявлено {triple.percent}%,"
                    f" расчёт {decimal_str(expected.quantize(Decimal('0.01')))}%"
                ),
                explanation=(
                    f"В тексте явно связаны числитель {decimal_str(triple.numerator)},"
                    f" знаменатель {decimal_str(triple.denominator)} и доля"
                    f" {triple.percent}%. Проверка: {decimal_str(triple.numerator)}"
                    f" / {decimal_str(triple.denominator)} × 100 ="
                    f" {decimal_str(expected.quantize(Decimal('0.01')))}%;"
                    f" расхождение {decimal_str(diff.quantize(Decimal('0.01')))} п.п."
                    f" при допуске {decimal_str(tolerance)} п.п. {_REVIEW_NOTE}"
                ),
                evidence=[
                    P3Evidence(
                        document_id=triple.document_id,
                        page_number=triple.page_number,
                        quote=triple.quote[:200],
                        note=f"раздел {triple.section_id}",
                    )
                ],
                page_references=[triple.page_number] if triple.page_number else [],
                mention_ids=sorted(triple.mention_ids),
                candidate_id=None,
                comparison=ComparisonDetail(
                    formula="percentage ≈ numerator / denominator × 100",
                    expected_value=decimal_str(expected.quantize(Decimal("0.01"))),
                    observed_value=decimal_str(triple.percent),
                    abs_diff=decimal_str(diff.quantize(Decimal("0.01"))),
                    rel_diff=None,
                    tolerance_abs=decimal_str(tolerance),
                    tolerance_rel=None,
                    rounding_tolerance=decimal_str(triple.percent_quantum * Decimal("0.5")),
                    canonical_unit="%",
                    conversions=[],
                ),
                semantic_rationale=(
                    "Числитель, знаменатель и процент связаны явной конструкцией"
                    " «N из M (P%)» в одном предложении."
                ),
                observed_value=f"{decimal_str(triple.percent)} %",
                expected_value=f"{decimal_str(expected.quantize(Decimal('0.01')))} %",
                quality_flags=["ocr_source"] if triple.ocr_source else [],
                limitations=(
                    "Проверка применима только к явным конструкциям «N из M (P%)»;"
                    " округление в исходном тексте учтено в допуске."
                ),
            )
        )
    return findings


# Kinds where negative values are legitimate: temperatures, elevations
# («отметка -0.150 м»), speeds/directions, power balances and percent
# CHANGES. Truly sign-definite kinds remain: mass, rates, volumes, areas,
# concentrations, mass fractions.
_NEGATIVE_ALLOWED_KINDS = frozenset({"temperature", "length", "velocity", "power", "percent"})
_CHANGE_CONTEXT_TOKENS = ("изменение", "снижение", "прирост", "баланс", "сокращение", "динамика")


def single_mention_findings(mentions: list[QuantMention]) -> list[P3FindingRecord]:
    """Rule G: impossible values and malformed ranges; ambiguity cues."""
    findings: list[P3FindingRecord] = []
    ambiguous_emitted: dict[str, int] = {}
    for mention in mentions:
        kind = _dimension_kind(mention)

        # -- malformed range (ambiguous-format values excluded) --------------------
        if (
            "range_inversion" in mention.flags
            and mention.unit_canonical is not None
            and "ambiguous_decimal_grouping" not in mention.flags
            and "spatial_sequence" not in mention.flags
        ):
            confidence, factors = finding_confidence("range_inversion", [mention], [])
            findings.append(
                _single_finding(
                    mention,
                    "range_inversion",
                    "P3-RANGE-INV",
                    "low",
                    confidence,
                    factors,
                    title=(
                        f"Некорректный диапазон: нижняя граница больше верхней"
                        f" ({mention.value_low}–{mention.value_high}"
                        f" {mention.unit_canonical})"
                    ),
                    explanation=(
                        f"Диапазон «{mention.raw_number}» ({_mention_note(mention)})"
                        f" имеет нижнюю границу {mention.value_low} больше верхней"
                        f" {mention.value_high}. Возможна опечатка, OCR-ошибка или"
                        f" обозначение, не являющееся диапазоном. {_REVIEW_NOTE}"
                    ),
                    observed=f"{mention.value_low}–{mention.value_high}",
                    expected="нижняя граница ≤ верхняя граница",
                )
            )
            continue

        # -- impossible negative physical quantity ---------------------------------
        if (
            mention.kind == "scalar"
            and mention.canonical_value is not None
            and Decimal(mention.canonical_value) < 0
            and mention.dimension is not None
            and kind not in _NEGATIVE_ALLOWED_KINDS
            and kind != "percent_points"
        ):
            label = (mention.metric_label or "") + " " + (mention.raw_text or "")
            if not any(token in label for token in _CHANGE_CONTEXT_TOKENS):
                confidence, factors = finding_confidence("impossible_value", [mention], [])
                severity = "medium" if confidence >= 0.5 else "low"
                findings.append(
                    _single_finding(
                        mention,
                        "impossible_value",
                        "P3-NEG-VALUE",
                        severity,
                        confidence,
                        factors,
                        title=(
                            f"Физически невозможное отрицательное значение:"
                            f" {mention.value} {mention.unit_canonical}"
                        ),
                        explanation=(
                            f"Значение {mention.raw_number} {mention.unit_canonical}"
                            f" ({_mention_note(mention)}) отрицательно, хотя величина"
                            f" размерности «{kind}» не может быть отрицательной"
                            f" (масса, объём, площадь, концентрация)."
                            f" Контекст изменения/динамики не обнаружен. {_REVIEW_NOTE}"
                        ),
                        observed=f"{mention.value} {mention.unit_canonical}",
                        expected=">= 0",
                    )
                )
                continue

        # -- share outside 0..100 ---------------------------------------------------
        if (
            mention.kind == "scalar"
            and kind == "percent"
            and mention.value is not None
            and _SHARE_CONTEXT(mention)
        ):
            value = Decimal(mention.value)
            if value > Decimal(100) + PERCENT_SHARE_EPSILON or value < -PERCENT_SHARE_EPSILON:
                confidence, factors = finding_confidence("impossible_value", [mention], [])
                findings.append(
                    _single_finding(
                        mention,
                        "impossible_value",
                        "P3-SHARE-RANGE",
                        "low" if confidence < 0.5 else "medium",
                        confidence,
                        factors,
                        title=f"Доля вне диапазона 0–100%: {mention.value}%",
                        explanation=(
                            f"Значение {mention.raw_number}% ({_mention_note(mention)})"
                            f" описано как доля, но выходит за пределы 0–100%"
                            f" (допуск {PERCENT_SHARE_EPSILON} п.п. на округление)."
                            f" {_REVIEW_NOTE}"
                        ),
                        observed=f"{mention.value} %",
                        expected="0–100 %",
                    )
                )
                continue

        # -- ambiguous format cue (info, capped per document) -------------------------
        if (
            "ambiguous_decimal_grouping" in mention.flags
            and mention.unit_canonical is not None
            and ambiguous_emitted.get(mention.document_id, 0) < _AMBIGUOUS_FINDINGS_PER_DOCUMENT
        ):
            ambiguous_emitted[mention.document_id] = (
                ambiguous_emitted.get(mention.document_id, 0) + 1
            )
            confidence, factors = finding_confidence("ambiguous_numeric_format", [mention], [])
            findings.append(
                _single_finding(
                    mention,
                    "ambiguous_numeric_format",
                    "P3-AMBIG-NUM",
                    "info",
                    confidence,
                    factors,
                    title=f"Неоднозначный числовой формат: «{mention.raw_number}»",
                    explanation=(
                        f"Запись «{mention.raw_number}» ({_mention_note(mention)})"
                        f" допускает два прочтения (десятичная дробь или разряды"
                        f" тысяч); принято прочтение {mention.value}"
                        f" {mention.unit_canonical or ''} по преобладающему стилю"
                        f" документа. Значение исключено из сравнений с высокой"
                        f" уверенностью. {_REVIEW_NOTE}"
                    ),
                    observed=mention.raw_number,
                    expected="однозначный числовой формат",
                )
            )
    findings.sort(key=lambda f: f.finding_id)
    return findings


def _SHARE_CONTEXT(mention: QuantMention) -> bool:
    label = (mention.metric_label or "") + " " + (mention.raw_text or "")
    lowered = label.casefold()
    return any(token in lowered for token in ("доля", "удельный вес", "share", "үлес"))


def _single_finding(
    mention: QuantMention,
    finding_type: str,
    rule_id: str,
    severity: str,
    confidence: float,
    factors: list[ConfidenceFactor],
    title: str,
    explanation: str,
    observed: str,
    expected: str,
) -> P3FindingRecord:
    return P3FindingRecord(
        finding_id=_finding_id(
            mention.project_id, mention.document_id, finding_type, rule_id, mention.mention_id
        ),
        project_id=mention.project_id,
        document_id=mention.document_id,
        finding_type=finding_type,
        severity=severity,
        priority_score=points_for(severity),
        confidence=confidence,
        confidence_factors=factors,
        rule_id=rule_id,
        title=title,
        explanation=explanation,
        evidence=_evidence_for([mention]),
        page_references=_pages_for([mention]),
        mention_ids=[mention.mention_id],
        candidate_id=None,
        comparison=None,
        semantic_rationale="Проверка одиночного значения; сопоставление не требуется.",
        observed_value=observed,
        expected_value=expected,
        quality_flags=list(mention.flags),
        limitations=(
            "Одиночная проверка значения; возможна OCR-ошибка или особый"
            " контекст, который делает значение корректным."
        ),
    )
