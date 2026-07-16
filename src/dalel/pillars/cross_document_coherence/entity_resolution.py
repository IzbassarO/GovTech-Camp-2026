"""Conservative deterministic entity resolution.

Merges are justified ONLY by an explicit shared identifier (BIN), a byte-equal
normalized label, or an identical accepted project-metadata value. Vague
lexical similarity never merges. Unknown identity stays unresolved. Every
decision (merged / separate / unresolved / suppressed) is recorded with a
reason and the signal that justified it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dalel.pillars.cross_document_coherence.config import CONFIDENCE_MAX, CONFIDENCE_MIN
from dalel.pillars.cross_document_coherence.normalization import collapse_whitespace
from dalel.pillars.cross_document_coherence.schemas import (
    Entity,
    EntityClaim,
    ResolutionDecision,
    deterministic_id,
)


@dataclass
class OperatorResolution:
    """Per-project resolution of the singular operator identity — the input to
    Check A. Status drives whether a finding is raised."""

    project_id: str
    status: str  # confirmed_by_identifier | confirmed_by_name | conflicting_identifier
    #             | unresolved_names | absent
    operator_entity_ids: list[str] = field(default_factory=list)
    bins: list[str] = field(default_factory=list)  # distinct, sorted
    bin_claim_ids: dict[str, list[str]] = field(default_factory=dict)  # bin -> claim ids
    name_claim_ids: dict[str, list[str]] = field(default_factory=dict)  # norm name -> claim ids
    document_ids: list[str] = field(default_factory=list)  # sorted, contributing operator docs


@dataclass
class ResolutionResult:
    entities: list[Entity] = field(default_factory=list)
    decisions: list[ResolutionDecision] = field(default_factory=list)
    claim_to_entity: dict[str, str] = field(default_factory=dict)
    operator_by_project: dict[str, OperatorResolution] = field(default_factory=dict)


def _clamp(value: float) -> float:
    return round(min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, value)), 2)


def _mean_conf(claims: list[EntityClaim]) -> float:
    if not claims:
        return CONFIDENCE_MIN
    return _clamp(sum(c.confidence for c in claims) / len(claims))


def _docs(claims: list[EntityClaim]) -> list[str]:
    return sorted({c.provenance.document_id for c in claims if c.provenance.document_id})


def _flags(claims: list[EntityClaim]) -> list[str]:
    flags: set[str] = set()
    for claim in claims:
        flags.update(claim.quality_flags)
    return sorted(flags)


def _role_of(claim: EntityClaim) -> str:
    for qualifier in claim.qualifiers:
        if qualifier.startswith("role:"):
            return qualifier.split(":", 1)[1]
    return "unknown"


def _legal_form_of(claim: EntityClaim) -> str:
    """Explicit legal form recorded on an organization claim (material identity
    attribute). ``none`` when the claim carries no legal-form qualifier."""
    for qualifier in claim.qualifiers:
        if qualifier.startswith("legal_form:"):
            return qualifier.split(":", 1)[1]
    return "none"


def _display(raw: str) -> str:
    """Clean, human-readable form of a claim's exact (span-verbatim) raw value.

    Claim raw values are stored EXACTLY as they appear in the source (Blocker B:
    ``source_text[start:end] == raw_value``), so they may contain repeated
    whitespace or line breaks; entity labels collapse that for display without
    ever changing the stored provenance.
    """
    return collapse_whitespace(raw)


def resolve_entities(
    claims: list[EntityClaim],
    projects_by_id: dict[str, dict[str, Any]],
    documents: list[dict[str, Any]],
) -> ResolutionResult:
    result = ResolutionResult()
    docs_by_project: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        docs_by_project.setdefault(str(document["project_id"]), []).append(document)

    claims_by_project: dict[str, list[EntityClaim]] = {}
    for claim in claims:
        claims_by_project.setdefault(claim.project_id, []).append(claim)

    for project_id in sorted(projects_by_id):
        project_claims = claims_by_project.get(project_id, [])
        # structural nodes
        _add_structural(result, project_id, docs_by_project.get(project_id, []))
        # attribute entities
        _resolve_organizations(
            result, project_id, project_claims, docs_by_project.get(project_id, [])
        )
        _resolve_simple(result, project_id, project_claims, "reporting_period", "reporting_period")
        _resolve_metadata(result, project_id, project_claims, "administrative_location", "region")
        _resolve_simple(result, project_id, project_claims, "administrative_location", "address")
        _resolve_metadata(result, project_id, project_claims, "activity", "industry")
        _resolve_simple(result, project_id, project_claims, "activity", "category")
        _resolve_simple(result, project_id, project_claims, "activity", "object")
        _resolve_simple(result, project_id, project_claims, "emission_source", "source_code")

    result.entities.sort(key=lambda e: (e.project_id, e.entity_type, e.entity_id))
    result.decisions.sort(key=lambda d: (d.project_id, d.entity_type, d.decision_id))
    return result


def _add_structural(
    result: ResolutionResult, project_id: str, documents: list[dict[str, Any]]
) -> None:
    project_entity_id = deterministic_id("P4E", project_id, "project")
    result.entities.append(
        Entity(
            entity_id=project_entity_id,
            project_id=project_id,
            entity_type="project",
            canonical_label=project_id,
            normalized_label=project_id,
            confidence=1.0,
            source_document_ids=sorted(str(d["document_id"]) for d in documents),
            limitations="Структурный узел пакета проекта.",
        )
    )
    for document in sorted(documents, key=lambda d: str(d["document_id"])):
        document_id = str(document["document_id"])
        result.entities.append(
            Entity(
                entity_id=deterministic_id("P4E", project_id, "document", document_id),
                project_id=project_id,
                entity_type="document",
                canonical_label=document_id,
                normalized_label=document_id,
                confidence=1.0,
                source_document_ids=[document_id],
                limitations=f"Документ типа {document['document_type']}.",
            )
        )


def _primary_name(name_claims: list[EntityClaim]) -> tuple[str, str, list[str]]:
    """Pick the canonical label / normalized key / aliases for a set of name
    claims. Deterministic: prefer the most-supported normalized name, then the
    longest CLEANED surface, then lexical order. Aliases = other cleaned
    surfaces (Blocker B: display collapses the span-verbatim raw values)."""
    by_norm: dict[str, list[EntityClaim]] = {}
    for claim in name_claims:
        by_norm.setdefault(claim.normalized_value, []).append(claim)
    ranked = sorted(
        by_norm.items(),
        key=lambda kv: (-len(kv[1]), -max(len(_display(c.raw_value)) for c in kv[1]), kv[0]),
    )
    primary_norm, primary_claims = ranked[0]
    canonical = sorted((_display(c.raw_value) for c in primary_claims), key=lambda s: (-len(s), s))[
        0
    ]
    aliases = sorted(
        {_display(c.raw_value) for c in name_claims if _display(c.raw_value) != canonical}
    )
    return canonical, primary_norm, aliases


def _resolve_organizations(
    result: ResolutionResult,
    project_id: str,
    project_claims: list[EntityClaim],
    documents: list[dict[str, Any]],
) -> None:
    org_claims = [c for c in project_claims if c.candidate_entity_type == "organization"]
    # High-precision veto: a name ever marked as a designer/preparer is NOT the
    # operator, however often a permissive marker («для») catches it elsewhere.
    designer_names = {c.normalized_value for c in org_claims if c.attribute == "designer_name"}
    operator_name_claims = [
        c
        for c in org_claims
        if c.attribute == "operator_name" and c.normalized_value not in designer_names
    ]
    operator_bin_claims = [
        c for c in org_claims if c.attribute == "bin" and _role_of(c) == "operator"
    ]
    # When a single operator identity is established, absorb generic mentions of
    # the SAME normalized name AND legal form (headers/footers marked
    # organization_name) so the operator is one node, not a duplicate. The legal
    # form must match to avoid an unsafe cross-form absorption (Blocker A).
    operator_norms = {c.normalized_value for c in operator_name_claims}
    operator_forms = {_legal_form_of(c) for c in operator_name_claims}
    single_operator = len({c.normalized_value for c in operator_bin_claims}) <= 1
    absorbed_claims: list[EntityClaim] = []
    if single_operator and operator_norms:
        absorbed_claims = [
            c
            for c in org_claims
            if c.attribute == "organization_name"
            and c.normalized_value in operator_norms
            and _legal_form_of(c) in operator_forms
            and c.normalized_value not in designer_names
        ]
    operator_name_claims = operator_name_claims + absorbed_claims
    folded_ids = {c.claim_id for c in operator_name_claims + operator_bin_claims}

    # --- operator (singular per package) ------------------------------------
    operator = OperatorResolution(project_id=project_id, status="absent")
    if operator_name_claims or operator_bin_claims:
        bins_map: dict[str, list[str]] = {}
        for claim in operator_bin_claims:
            bins_map.setdefault(claim.normalized_value, []).append(claim.claim_id)
        names_map: dict[str, list[str]] = {}
        for claim in operator_name_claims:
            names_map.setdefault(claim.normalized_value, []).append(claim.claim_id)
        distinct_bins = sorted(bins_map)
        operator.bins = distinct_bins
        operator.bin_claim_ids = {b: sorted(v) for b, v in bins_map.items()}
        operator.name_claim_ids = {n: sorted(v) for n, v in names_map.items()}
        operator.document_ids = _docs(operator_name_claims + operator_bin_claims)

        if len(distinct_bins) >= 2:
            operator.status = "conflicting_identifier"
            # One candidate entity per distinct explicit BIN (unresolved identity).
            for bin_value in distinct_bins:
                bin_claims = [c for c in operator_bin_claims if c.normalized_value == bin_value]
                entity = _build_operator_entity(
                    project_id,
                    bin_value,
                    operator_name_claims,
                    bin_claims,
                    quality_flags=["conflicting_operator_identifier"],
                )
                result.entities.append(entity)
                operator.operator_entity_ids.append(entity.entity_id)
                _map_claims(result, entity, operator_name_claims + bin_claims)
            _decide(
                result,
                project_id,
                "organization",
                "unresolved",
                operator.operator_entity_ids,
                [c.claim_id for c in operator_bin_claims],
                "shared_identifier",
                f"documents assert {len(distinct_bins)} different explicit operator BINs",
                0.9,
            )
        elif len(distinct_bins) == 1:
            operator.status = "confirmed_by_identifier"
            entity = _build_operator_entity(
                project_id, distinct_bins[0], operator_name_claims, operator_bin_claims
            )
            result.entities.append(entity)
            operator.operator_entity_ids.append(entity.entity_id)
            _map_claims(result, entity, operator_name_claims + operator_bin_claims)
            _decide(
                result,
                project_id,
                "organization",
                "merged",
                [entity.entity_id],
                [c.claim_id for c in operator_name_claims + operator_bin_claims],
                "shared_identifier",
                f"single explicit operator BIN across {len(operator.document_ids)} document(s);"
                " differing name spellings folded to aliases",
                0.9,
            )
        else:
            # No explicit operator BIN: name-only resolution keyed on
            # (normalized name, legal form). Merging across different legal
            # forms without an identifier is UNSAFE (Blocker A), so a single
            # (name, form) group merges (confirmed_by_name); anything else stays
            # unresolved with one candidate entity per (name, form) group.
            name_form_groups: dict[tuple[str, str], list[EntityClaim]] = {}
            for claim in operator_name_claims:
                name_form_groups.setdefault(
                    (claim.normalized_value, _legal_form_of(claim)), []
                ).append(claim)
            if len(name_form_groups) == 1:
                operator.status = "confirmed_by_name"
                group = next(iter(name_form_groups.values()))
                entity = _build_operator_entity(project_id, None, group, [])
                result.entities.append(entity)
                operator.operator_entity_ids.append(entity.entity_id)
                _map_claims(result, entity, group)
                _decide(
                    result,
                    project_id,
                    "organization",
                    "merged",
                    [entity.entity_id],
                    [c.claim_id for c in group],
                    "normalized_name_match",
                    "identical normalized operator name and legal form across documents",
                    0.75,
                )
            else:
                operator.status = "unresolved_names"
                for _key, group in sorted(name_form_groups.items()):
                    entity = _build_operator_entity(project_id, None, group, [])
                    result.entities.append(entity)
                    operator.operator_entity_ids.append(entity.entity_id)
                    _map_claims(result, entity, group)
                distinct_forms = {form for _, form in name_form_groups}
                reason = (
                    "documents name the operator with the same normalized name but"
                    " different explicit legal forms and no shared identifier"
                    if len(names_map) == 1 and len(distinct_forms) >= 2
                    else "documents name different operators and no shared identifier links them"
                )
                _decide(
                    result,
                    project_id,
                    "organization",
                    "unresolved",
                    operator.operator_entity_ids,
                    [c.claim_id for c in operator_name_claims],
                    "normalized_name_match",
                    reason,
                    0.5,
                )
    result.operator_by_project[project_id] = operator

    # --- designer / unknown organizations (graph only) ----------------------
    # Everything not folded into the operator: designers (veto names), excluded
    # operator-marked names, and generic mentions of non-operator companies.
    # Grouped by (role, normalized name, LEGAL FORM): different explicit legal
    # forms are NOT merged without a shared identifier (Blocker A).
    other_claims = [
        c
        for c in org_claims
        if c.attribute in ("operator_name", "designer_name", "organization_name")
        and c.claim_id not in folded_ids
    ]
    by_key: dict[tuple[str, str, str], list[EntityClaim]] = {}
    for claim in other_claims:
        effective_role = "designer" if claim.normalized_value in designer_names else "unknown"
        by_key.setdefault(
            (effective_role, claim.normalized_value, _legal_form_of(claim)), []
        ).append(claim)
    # (role, name) -> [(entity_id, claim_ids)], to record deliberate non-merges
    same_name: dict[tuple[str, str], list[tuple[str, list[str]]]] = {}
    for (role, normalized_name, legal_form), group in sorted(by_key.items()):
        canonical, _, aliases = _primary_name(group)
        entity_id = deterministic_id(
            "P4E", project_id, "organization", role, legal_form, normalized_name
        )
        entity = Entity(
            entity_id=entity_id,
            project_id=project_id,
            entity_type="organization",
            canonical_label=canonical,
            normalized_label=normalized_name,
            aliases=aliases,
            role=role,
            confidence=_mean_conf(group),
            claim_ids=sorted(c.claim_id for c in group),
            source_document_ids=_docs(group),
            quality_flags=_flags(group),
            limitations="Организация вне сферы проверки идентичности оператора (иная роль).",
        )
        result.entities.append(entity)
        _map_claims(result, entity, group)
        same_name.setdefault((role, normalized_name), []).append(
            (entity_id, sorted(c.claim_id for c in group))
        )
    # Record a deterministic "separate" decision wherever one normalized name is
    # kept apart across ≥2 explicit legal forms (no shared identifier merges them).
    for (_role, normalized_name), members in sorted(same_name.items()):
        if len(members) >= 2:
            entity_ids = [entity_id for entity_id, _ in members]
            claim_ids = [cid for _, cids in members for cid in cids]
            _decide(
                result,
                project_id,
                "organization",
                "separate",
                entity_ids,
                claim_ids,
                "legal_form_distinct",
                f"same normalized name «{normalized_name}» appears with"
                f" {len(members)} different explicit legal forms and no shared"
                " identifier links them; kept separate",
                0.6,
            )


def _build_operator_entity(
    project_id: str,
    primary_bin: str | None,
    name_claims: list[EntityClaim],
    bin_claims: list[EntityClaim],
    quality_flags: list[str] | None = None,
) -> Entity:
    all_claims = name_claims + bin_claims
    if name_claims:
        canonical, normalized_key, aliases = _primary_name(name_claims)
    elif primary_bin is not None:
        canonical, normalized_key, aliases = f"БИН {primary_bin}", f"bin:{primary_bin}", []
    else:  # pragma: no cover - defensive
        canonical, normalized_key, aliases = "оператор", "operator", []
    # Identity key: the explicit BIN when present, else (name, legal form) so
    # same-name / different-form operators never collide into one node.
    if primary_bin is not None:
        identity_key = primary_bin
    else:
        forms = "|".join(sorted({_legal_form_of(c) for c in name_claims}))
        identity_key = f"{normalized_key}#{forms}"
    identifiers = sorted({c.normalized_value for c in bin_claims})
    flags = sorted(set(_flags(all_claims)) | set(quality_flags or []))
    return Entity(
        entity_id=deterministic_id("P4E", project_id, "organization", "operator", identity_key),
        project_id=project_id,
        entity_type="organization",
        canonical_label=canonical,
        normalized_label=normalized_key,
        aliases=aliases,
        identifiers=identifiers,
        role="operator",
        confidence=_mean_conf(all_claims),
        claim_ids=sorted(c.claim_id for c in all_claims),
        source_document_ids=_docs(all_claims),
        quality_flags=flags,
        limitations="Оператор пакета; идентичность подтверждается идентификатором/названием.",
    )


def _resolve_simple(
    result: ResolutionResult,
    project_id: str,
    project_claims: list[EntityClaim],
    entity_type: str,
    attribute: str,
) -> None:
    """One entity per distinct normalized value; claims with the same value are
    merged (byte-equal normalized-value merge)."""
    claims = [
        c
        for c in project_claims
        if c.candidate_entity_type == entity_type and c.attribute == attribute
    ]
    by_value: dict[str, list[EntityClaim]] = {}
    for claim in claims:
        by_value.setdefault(claim.normalized_value, []).append(claim)
    for normalized_value, group in sorted(by_value.items()):
        canonical = sorted((_display(c.raw_value) for c in group), key=lambda s: (-len(s), s))[0]
        entity_id = deterministic_id("P4E", project_id, entity_type, attribute, normalized_value)
        entity = Entity(
            entity_id=entity_id,
            project_id=project_id,
            entity_type=entity_type,
            canonical_label=canonical,
            normalized_label=normalized_value,
            aliases=sorted(
                {_display(c.raw_value) for c in group if _display(c.raw_value) != canonical}
            ),
            confidence=_mean_conf(group),
            claim_ids=sorted(c.claim_id for c in group),
            source_document_ids=_docs(group),
            quality_flags=_flags(group),
        )
        result.entities.append(entity)
        _map_claims(result, entity, group)
        if len(group) >= 2:
            _decide(
                result,
                project_id,
                entity_type,
                "merged",
                [entity_id],
                [c.claim_id for c in group],
                "normalized_name_match",
                f"identical normalized {attribute} across {len(_docs(group))} document(s)",
                _mean_conf(group),
            )


def _resolve_metadata(
    result: ResolutionResult,
    project_id: str,
    project_claims: list[EntityClaim],
    entity_type: str,
    attribute: str,
) -> None:
    """Project-metadata attribute (region / industry): a single accepted value,
    grounded in projects.jsonl."""
    claims = [
        c
        for c in project_claims
        if c.candidate_entity_type == entity_type and c.attribute == attribute
    ]
    if not claims:
        return
    claim = claims[0]
    entity_id = deterministic_id("P4E", project_id, entity_type, attribute, claim.normalized_value)
    entity = Entity(
        entity_id=entity_id,
        project_id=project_id,
        entity_type=entity_type,
        canonical_label=_display(claim.raw_value),
        normalized_label=claim.normalized_value,
        confidence=claim.confidence,
        claim_ids=[claim.claim_id],
        quality_flags=claim.quality_flags,
        limitations="Значение из принятых метаданных проекта (projects.jsonl).",
    )
    result.entities.append(entity)
    _map_claims(result, entity, [claim])


def _map_claims(result: ResolutionResult, entity: Entity, claims: list[EntityClaim]) -> None:
    for claim in claims:
        result.claim_to_entity[claim.claim_id] = entity.entity_id


def _decide(
    result: ResolutionResult,
    project_id: str,
    entity_type: str,
    decision: str,
    entity_ids: list[str],
    claim_ids: list[str],
    signal: str,
    reason: str,
    confidence: float,
) -> None:
    decision_id = deterministic_id(
        "P4R", project_id, entity_type, decision, signal, "|".join(sorted(entity_ids))
    )
    result.decisions.append(
        ResolutionDecision(
            decision_id=decision_id,
            project_id=project_id,
            entity_type=entity_type,
            decision=decision,  # type: ignore[arg-type]
            entity_ids=sorted(entity_ids),
            claim_ids=sorted(claim_ids),
            signal=signal,
            reason=reason,
            confidence=round(confidence, 2),
        )
    )
