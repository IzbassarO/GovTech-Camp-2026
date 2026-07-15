"""Deterministic NLI baseline: requirement × project evidence → label.

Conservative by construction:

- ``insufficient_evidence`` is ALWAYS preferred over an unsupported
  conflict claim;
- legal applicability is never inferred from keyword overlap alone —
  applicability comes from declared tags checked against the package;
- a ``potential_conflict`` additionally requires retrieval confidence at
  or above CONFLICT_MIN_RETRIEVAL_SCORE (weak retrieval can never become
  a conflict);
- quantitative limits are never judged by the baseline (no safe numeric
  linkage between requirement thresholds and project values here — P3
  owns numeric consistency);
- explicit negation is recognized only INSIDE the matched snippet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dalel.pillars.regulatory_compliance.config import (
    CONFLICT_MIN_RETRIEVAL_SCORE,
    NEGATION_MARKERS,
    NLI_CONFIDENCE,
    SNIPPET_WINDOW,
)
from dalel.pillars.regulatory_compliance.evidence import (
    ProjectEvidenceStore,
    add_text_snippet,
)
from dalel.pillars.regulatory_compliance.normalization import (
    concept_in_text,
    find_snippet,
    normalize_text,
)
from dalel.pillars.regulatory_compliance.schemas import (
    ConfidenceFactor,
    P2Evidence,
    ProjectEvidence,
    RegulatoryRequirement,
)


@dataclass
class NLIResult:
    label: str
    confidence: float
    confidence_factors: list[ConfidenceFactor] = field(default_factory=list)
    applicability: str = "unknown"
    applicability_reasons: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    evidence_snippets: list[P2Evidence] = field(default_factory=list)
    rationale: str = ""
    missing_information: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)


def _confidence(path: str) -> tuple[float, list[ConfidenceFactor]]:
    value = NLI_CONFIDENCE[path]
    return value, [ConfidenceFactor(factor=f"baseline:{path}", delta=value)]


def check_applicability(
    requirement: RegulatoryRequirement, store: ProjectEvidenceStore
) -> tuple[str, list[str]]:
    """Declared-tag applicability: applicable / not_applicable / unknown.

    Tags the dataset cannot evaluate (e.g. ``category:I`` — the curated
    dataset has no object category) yield ``unknown``, never a guess."""
    reasons: list[str] = []
    state = "applicable"
    for tag in requirement.applicability_tags:
        key, _, value = tag.partition(":")
        if key == "package" and value == "any":
            reasons.append("package:any")
        elif key == "industry" and value == "any":
            reasons.append("industry:any")
        elif key == "industry":
            if store.industry == value:
                reasons.append(f"industry:{value}=match")
            else:
                # The project's declared industry does not match the
                # requirement's declared industry condition.
                reasons.append(f"industry:{value}!={store.industry}")
                return "not_applicable", reasons
        elif key == "document_type":
            if value in store.document_types:
                reasons.append(f"document_type:{value}=present")
            else:
                # The target document itself is absent: the requirement's
                # applicability to THIS package cannot be confirmed from
                # tags alone (required_document handles absence separately).
                reasons.append(f"document_type:{value}=absent")
                state = "unknown"
        elif key == "topic":
            reasons.append(f"topic:{value}=declared")
        else:
            reasons.append(f"{tag}=not_evaluable")
            state = "unknown"
    return state, reasons


def _match_concepts_in_headings(
    requirement: RegulatoryRequirement,
    store: ProjectEvidenceStore,
    target_types: set[str] | None,
) -> ProjectEvidence | None:
    for item in store.ordered():
        if item.kind != "section_heading":
            continue
        if target_types and (item.document_type or "") not in target_types:
            continue
        for concept in requirement.required_concepts:
            if concept_in_text(concept, item.text):
                return item
    return None


def _match_concepts_in_texts(
    requirement: RegulatoryRequirement,
    store: ProjectEvidenceStore,
    target_types: set[str] | None,
) -> tuple[ProjectEvidence | None, str | None]:
    for (document_id, section_id), text in sorted(store.section_texts.items()):
        document_type = document_id.split("__")[1] if "__" in document_id else None
        if target_types and (document_type or "") not in target_types:
            continue
        for concept in requirement.required_concepts:
            if concept_in_text(concept, text):
                snippet = find_snippet(concept, text, SNIPPET_WINDOW)
                if snippet is None:
                    continue
                item = add_text_snippet(store, document_id, document_type, section_id, snippet)
                return item, snippet
    return None, None


def _snippet_negated(snippet: str) -> str | None:
    normalized = normalize_text(snippet)
    for marker in NEGATION_MARKERS:
        if marker in normalized:
            return marker
    return None


def _evidence_ref(item: ProjectEvidence, quote: str | None = None) -> P2Evidence:
    return P2Evidence(
        document_id=item.document_id,
        page_number=item.page_number,
        quote=quote if quote is not None else item.text,
        note=f"evidence:{item.kind}",
    )


def assess_requirement(
    requirement: RegulatoryRequirement,
    store: ProjectEvidenceStore,
    retrieval_score: float,
) -> NLIResult:
    applicability, applicability_reasons = check_applicability(requirement, store)
    target_types = (
        {requirement.required_document_type} if requirement.required_document_type else None
    )

    # -- applicability gates ------------------------------------------------------
    if applicability == "not_applicable":
        confidence, factors = _confidence("not_applicable")
        return NLIResult(
            label="not_applicable",
            confidence=confidence,
            confidence_factors=factors,
            applicability=applicability,
            applicability_reasons=applicability_reasons,
            rationale="Проект не подпадает под заявленные условия применимости требования.",
        )

    if requirement.obligation_type == "required_document":
        return _assess_required_document(requirement, store, applicability, applicability_reasons)

    if requirement.obligation_type in (
        "mandatory_section",
        "monitoring_requirement",
        "disclosure_requirement",
        "procedural_requirement",
    ):
        return _assess_concept_requirement(
            requirement,
            store,
            applicability,
            applicability_reasons,
            target_types,
            retrieval_score,
        )

    if requirement.obligation_type == "applicability_condition":
        confidence, factors = _confidence("applicability_unknown")
        return NLIResult(
            label="insufficient_evidence",
            confidence=confidence,
            confidence_factors=factors,
            applicability="unknown",
            applicability_reasons=applicability_reasons,
            rationale=(
                "Условие применимости не может быть проверено по куративному"
                " набору данных (нет сведений о категории объекта)."
            ),
            missing_information=["категория объекта / условие применимости"],
            quality_flags=["applicability_not_evaluable"],
        )

    # quantitative_limit, prohibition, permit_requirement, other: the
    # baseline never claims support or conflict from keyword presence.
    confidence, factors = _confidence("insufficient_evidence")
    return NLIResult(
        label="insufficient_evidence",
        confidence=confidence,
        confidence_factors=factors,
        applicability=applicability,
        applicability_reasons=applicability_reasons,
        rationale=(
            "Детерминированная базовая проверка не выполняет численное или"
            " правовое сопоставление для данного типа требования;"
            " требуется экспертная оценка."
        ),
        missing_information=["экспертная проверка выполнения требования"],
        quality_flags=[f"baseline_not_applicable_to:{requirement.obligation_type}"],
    )


def _assess_required_document(
    requirement: RegulatoryRequirement,
    store: ProjectEvidenceStore,
    applicability: str,
    applicability_reasons: list[str],
) -> NLIResult:
    required_type = requirement.required_document_type or ""
    present_ids = store.document_types.get(required_type, [])
    if present_ids:
        items = [
            item
            for item in store.ordered()
            if item.kind == "document_present" and item.document_id in set(present_ids)
        ]
        confidence, factors = _confidence("document_present")
        return NLIResult(
            label="supported_by_evidence",
            confidence=confidence,
            confidence_factors=factors,
            applicability=applicability,
            applicability_reasons=applicability_reasons,
            evidence_ids=[item.evidence_id for item in items],
            evidence_snippets=[_evidence_ref(item) for item in items],
            rationale=(
                f"Документ требуемого типа «{required_type}» присутствует в принятом пакете."
            ),
        )
    confidence, factors = _confidence("document_missing")
    return NLIResult(
        label="potential_conflict",
        confidence=confidence,
        confidence_factors=factors,
        applicability=applicability,
        applicability_reasons=applicability_reasons,
        rationale=(
            f"Документ требуемого типа «{required_type}» отсутствует среди"
            " документов принятого пакета. Возможные причины: документ не"
            " требуется для данного объекта, подан отдельно или не попал в"
            " выборку — требуется экспертная проверка."
        ),
        missing_information=[f"документ типа {required_type}"],
        quality_flags=["package_scope_uncertain"],
    )


def _assess_concept_requirement(
    requirement: RegulatoryRequirement,
    store: ProjectEvidenceStore,
    applicability: str,
    applicability_reasons: list[str],
    target_types: set[str] | None,
    retrieval_score: float,
) -> NLIResult:
    # The target document must exist before its content is judged.
    if target_types and not any(t in store.document_types for t in target_types):
        confidence, factors = _confidence("applicability_unknown")
        return NLIResult(
            label="insufficient_evidence",
            confidence=confidence,
            confidence_factors=factors,
            applicability="unknown",
            applicability_reasons=applicability_reasons,
            rationale=(
                "Целевой документ требования отсутствует в пакете; содержание проверить невозможно."
            ),
            missing_information=[f"документ типа {sorted(target_types)[0]}"],
            quality_flags=["target_document_absent"],
        )

    heading = _match_concepts_in_headings(requirement, store, target_types)
    if heading is not None:
        confidence, factors = _confidence("section_heading_match")
        return NLIResult(
            label="supported_by_evidence",
            confidence=confidence,
            confidence_factors=factors,
            applicability=applicability,
            applicability_reasons=applicability_reasons,
            evidence_ids=[heading.evidence_id],
            evidence_snippets=[_evidence_ref(heading)],
            rationale=(
                "Заголовок раздела целевого документа явно соответствует требуемому содержанию."
            ),
        )

    text_item, snippet = _match_concepts_in_texts(requirement, store, target_types)
    if text_item is not None and snippet is not None:
        negation = _snippet_negated(snippet)
        if negation is not None:
            confidence, factors = _confidence("explicit_negation")
            if retrieval_score < CONFLICT_MIN_RETRIEVAL_SCORE:
                # Weak retrieval evidence can never become a conflict claim.
                weak_confidence, weak_factors = _confidence("insufficient_evidence")
                return NLIResult(
                    label="insufficient_evidence",
                    confidence=weak_confidence,
                    confidence_factors=weak_factors,
                    applicability=applicability,
                    applicability_reasons=applicability_reasons,
                    evidence_ids=[text_item.evidence_id],
                    evidence_snippets=[_evidence_ref(text_item, snippet)],
                    rationale=(
                        "Обнаружено явное отрицание рядом с требуемым понятием,"
                        " но связь требования с проектом лексически слаба —"
                        " вывод о конфликте не делается."
                    ),
                    missing_information=["подтверждение релевантности требования"],
                    quality_flags=["weak_retrieval", f"negation:{negation}"],
                )
            return NLIResult(
                label="potential_conflict",
                confidence=confidence,
                confidence_factors=factors,
                applicability=applicability,
                applicability_reasons=applicability_reasons,
                evidence_ids=[text_item.evidence_id],
                evidence_snippets=[_evidence_ref(text_item, snippet)],
                rationale=(
                    f"В тексте целевого документа найдено явное отрицание"
                    f" («{negation}») рядом с требуемым понятием."
                ),
                quality_flags=[f"negation:{negation}"],
            )
        confidence, factors = _confidence("section_text_match")
        return NLIResult(
            label="supported_by_evidence",
            confidence=confidence,
            confidence_factors=factors,
            applicability=applicability,
            applicability_reasons=applicability_reasons,
            evidence_ids=[text_item.evidence_id],
            evidence_snippets=[_evidence_ref(text_item, snippet)],
            rationale=(
                "Требуемое понятие обнаружено в тексте целевого документа"
                " (совпадение по тексту слабее совпадения по заголовку)."
            ),
            quality_flags=["text_level_match"],
        )

    missing = [
        f"явное подтверждение: {requirement.required_concepts[0]}"
        if requirement.required_concepts
        else "явное подтверждение требуемого содержания"
    ]
    absence_rationale = (
        "Требуемое содержание не найдено ни в заголовках, ни в тексте"
        " целевых документов. Отсутствие лексического совпадения НЕ"
        " доказывает отсутствие содержания (OCR, синонимия) —"
        " требуется экспертная проверка."
    )
    if (
        requirement.obligation_type == "mandatory_section"
        and retrieval_score >= CONFLICT_MIN_RETRIEVAL_SCORE
    ):
        # A structurally mandatory section absent from a PRESENT target
        # document is a review-worthy potential conflict (never for weak
        # retrieval, never for softer requirement types).
        confidence, factors = _confidence("document_missing")
        return NLIResult(
            label="potential_conflict",
            confidence=confidence,
            confidence_factors=factors,
            applicability=applicability,
            applicability_reasons=applicability_reasons,
            rationale=absence_rationale,
            missing_information=missing,
            quality_flags=["no_lexical_evidence"],
        )
    confidence, factors = _confidence("insufficient_evidence")
    return NLIResult(
        label="insufficient_evidence",
        confidence=confidence,
        confidence_factors=factors,
        applicability=applicability,
        applicability_reasons=applicability_reasons,
        rationale=absence_rationale,
        missing_information=missing,
        quality_flags=["no_lexical_evidence"],
    )
