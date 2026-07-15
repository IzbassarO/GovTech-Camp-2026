"""Assessment orchestration: deterministic NLI first, optional LLM second.

Safety contract:

- the deterministic baseline ALWAYS runs and its label is always recorded;
- a valid LLM response may CONFIRM the deterministic label or DOWNGRADE it
  toward caution (→ insufficient_evidence); it can never introduce a
  supported/conflict label the baseline did not establish — no finding is
  ever based only on an LLM statement;
- every LLM response is validated: strict JSON schema, known evidence ids,
  quotes that are EXACT substrings of supplied evidence, label vocabulary,
  confidence bounds. Anything invalid falls back to the deterministic
  result with an explicit quality flag;
- LLM confidence never overrides missing applicability evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from dalel.pillars.regulatory_compliance.config import LLM_MAX_EVIDENCE_ITEMS
from dalel.pillars.regulatory_compliance.evidence import ProjectEvidenceStore
from dalel.pillars.regulatory_compliance.nli import NLIResult, assess_requirement
from dalel.pillars.regulatory_compliance.prompts import build_prompt, prompt_hash
from dalel.pillars.regulatory_compliance.providers import (
    LLMProvider,
    ProviderError,
    ResponseCache,
    response_hash,
)
from dalel.pillars.regulatory_compliance.schemas import (
    ConfidenceFactor,
    LLMAssessmentResponse,
    P2Assessment,
    ProjectEvidence,
    RegulatoryRequirement,
    RetrievalRecord,
    deterministic_id,
)

_CAUTIOUS_DOWNGRADES = {"insufficient_evidence"}


@dataclass
class LLMOutcome:
    used: bool = False
    valid: bool = False
    response: LLMAssessmentResponse | None = None
    prompt_hash: str | None = None
    response_hash: str | None = None
    flags: list[str] = field(default_factory=list)


def _select_llm_evidence(
    store: ProjectEvidenceStore,
    nli: NLIResult,
    requirement: RegulatoryRequirement,
) -> list[ProjectEvidence]:
    """Deterministic bounded evidence bundle: NLI-cited items first, then
    target-document presence and headings."""
    selected: dict[str, ProjectEvidence] = {}
    for evidence_id in nli.evidence_ids:
        item = store.evidence.get(evidence_id)
        if item is not None:
            selected[item.evidence_id] = item
    target_type = requirement.required_document_type
    for item in store.ordered():
        if len(selected) >= LLM_MAX_EVIDENCE_ITEMS:
            break
        if item.kind in ("document_present", "section_heading") and (
            target_type is None or item.document_type == target_type
        ):
            selected.setdefault(item.evidence_id, item)
    return [selected[key] for key in sorted(selected)][:LLM_MAX_EVIDENCE_ITEMS]


def validate_llm_response(
    raw_text: str,
    supplied: list[ProjectEvidence],
) -> tuple[LLMAssessmentResponse | None, list[str]]:
    """Strict validation; returns (response, flags). ``None`` => invalid."""
    flags: list[str] = []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None, ["llm_response_invalid:malformed_json"]
    if not isinstance(payload, dict):
        return None, ["llm_response_invalid:not_an_object"]
    try:
        response = LLMAssessmentResponse.model_validate(payload)
    except ValidationError:
        return None, ["llm_response_invalid:schema"]
    supplied_by_id = {item.evidence_id: item for item in supplied}
    for evidence_id in response.evidence_ids:
        if evidence_id not in supplied_by_id:
            return None, [f"llm_response_invalid:unknown_evidence_id:{evidence_id}"]
    supplied_texts = [item.text for item in supplied]
    for quote in response.evidence_quotes:
        if not any(quote in text for text in supplied_texts):
            return None, ["llm_response_invalid:hallucinated_quote"]
    return response, flags


def run_llm_assessment(
    provider: LLMProvider,
    cache: ResponseCache,
    requirement: RegulatoryRequirement,
    store: ProjectEvidenceStore,
    nli: NLIResult,
) -> LLMOutcome:
    outcome = LLMOutcome(used=True)
    evidence_items = _select_llm_evidence(store, nli, requirement)
    prompt = build_prompt(requirement, evidence_items, nli.applicability, nli.applicability_reasons)
    outcome.prompt_hash = prompt_hash(provider.name, provider.model, prompt)

    cached = cache.get(outcome.prompt_hash)
    if cached is not None:
        raw_text = cached
        outcome.flags.append("llm_cache_hit")
    else:
        try:
            raw_text = provider.generate_structured(prompt)
        except ProviderError as exc:
            outcome.flags.append(f"llm_provider_error:{type(exc).__name__}")
            return outcome

    response, flags = validate_llm_response(raw_text, evidence_items)
    outcome.flags.extend(flags)
    if response is None:
        return outcome
    outcome.valid = True
    outcome.response = response
    outcome.response_hash = response_hash(raw_text)
    if "llm_cache_hit" not in outcome.flags:
        cache.put(outcome.prompt_hash, raw_text)  # only validated responses
    return outcome


def _merge_labels(nli: NLIResult, llm: LLMOutcome) -> tuple[str, list[str], list[ConfidenceFactor]]:
    """Deterministic label + safe LLM refinement (confirm or downgrade)."""
    flags: list[str] = []
    factors: list[ConfidenceFactor] = []
    label = nli.label
    if not llm.valid or llm.response is None:
        return label, flags, factors
    proposed = llm.response.label
    if proposed == nli.label:
        factors.append(ConfidenceFactor(factor="llm_confirms_baseline", delta=0.05))
        return label, flags, factors
    if proposed in _CAUTIOUS_DOWNGRADES:
        flags.append("llm_downgraded_to_caution")
        factors.append(ConfidenceFactor(factor="llm_downgrade", delta=-0.05))
        return proposed, flags, factors
    # Upgrades (introducing supported/conflict/not_applicable) are refused:
    # no finding may rest only on an LLM statement, and LLM confidence
    # never overrides missing applicability evidence.
    flags.append(f"llm_upgrade_rejected:{proposed}")
    return label, flags, factors


def assess_pair(
    requirement: RegulatoryRequirement,
    store: ProjectEvidenceStore,
    retrieval: RetrievalRecord,
    provider: LLMProvider | None,
    cache: ResponseCache,
) -> P2Assessment:
    nli = assess_requirement(requirement, store, retrieval.score)

    llm = LLMOutcome()
    if provider is not None:
        llm = run_llm_assessment(provider, cache, requirement, store, nli)

    label, merge_flags, merge_factors = _merge_labels(nli, llm)
    confidence = nli.confidence
    factors = [*nli.confidence_factors, *merge_factors]
    for factor in merge_factors:
        confidence = min(0.95, max(0.05, confidence + factor.delta))
    confidence = round(confidence, 2)

    engine = "deterministic"
    if llm.used:
        engine = "hybrid"

    rationale = nli.rationale
    missing = list(nli.missing_information)
    if llm.valid and llm.response is not None:
        if llm.response.rationale:
            rationale = f"{rationale} LLM: {llm.response.rationale}"
        missing.extend(m for m in llm.response.missing_information if m not in missing)

    quality_flags = sorted({*nli.quality_flags, *llm.flags, *merge_flags})
    return P2Assessment(
        assessment_id=deterministic_id(
            "P2A",
            store.project_id,
            requirement.requirement_id,
            requirement.corpus_id,
            requirement.corpus_version,
        ),
        project_id=store.project_id,
        requirement_id=requirement.requirement_id,
        corpus_id=requirement.corpus_id,
        corpus_version=requirement.corpus_version,
        requirement_is_authoritative=requirement.is_authoritative,
        requirement_demo_only=requirement.demo_only,
        retrieval_id=retrieval.retrieval_id,
        retrieval_score=retrieval.score,
        retrieval_rank=retrieval.rank,
        applicability=nli.applicability,  # type: ignore[arg-type]
        applicability_reasons=nli.applicability_reasons,
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        confidence_factors=factors,
        inference_engine=engine,  # type: ignore[arg-type]
        provider_name=provider.name if (llm.used and provider is not None) else None,
        model_name=provider.model if (llm.used and provider is not None) else None,
        prompt_hash=llm.prompt_hash,
        cached_response_hash=llm.response_hash,
        deterministic_label=nli.label,
        evidence_ids=nli.evidence_ids,
        evidence_snippets=nli.evidence_snippets,
        rationale=rationale,
        missing_information=missing,
        quality_flags=quality_flags,
        limitations=(
            "Экспертная поддержка, не юридический вывод. Метка отражает"
            " наличие/отсутствие лексических свидетельств в куративном"
            " наборе; применимость нормы подтверждает только эксперт."
            + (
                " Требование из синтетического демонстрационного корпуса —"
                " не является правовой нормой."
                if requirement.demo_only
                else ""
            )
        ),
    )
