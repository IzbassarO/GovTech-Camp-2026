"""Conservative comparison-candidate construction.

The core risk of P3 is comparing numbers that describe different things.
Candidates are therefore built ONLY inside groups whose semantic key fully
aligns — dimension (kind + time basis), substance, reporting period,
emission source, qualifier profile (planned/actual, gross/one-time,
with/without treatment, limit) and scope (item vs total) — and additional
structural guards apply per relationship:

- mentions of the same TABLE are never directly compared (rows of one table
  are different entities; totals are handled by the aggregation rule);
- item-level table rows across tables also require equal normalized row
  labels (protects source-level rows from substance-level summaries);
- substance-less comparisons are allowed only for totals of the same metric
  group, with an explicit ``scope_breadth: unverified`` penalty that keeps
  the resulting findings out of high severity.

Groups that differ in exactly one aspect are counted as suppressed
comparisons with the differing aspect as the reason (temporal scope,
qualifier profile, source, scope) — a capped sample is serialized so the
report can show WHY comparisons did not happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dalel.pillars.quantitative_consistency.schemas import (
    ComparisonCandidate,
    QuantMention,
    deterministic_id,
)

# Mentions in one group beyond this are suppressed as weakly-contextualized.
MAX_GROUP_SIZE = 10
SUPPRESSED_SAMPLES_PER_REASON = 8


@dataclass
class ComparablePair:
    """In-memory pair handed to the comparison rules."""

    candidate_id: str
    rule: str  # "direct" | "bound"
    a: QuantMention  # for "bound": the bound/range side
    b: QuantMention  # for "bound": the observed scalar side
    compatibility: dict[str, str]
    relationship: str
    confidence: float
    confidence_factors: list[tuple[str, float]]
    # Tri-state semantic compatibility (match / conflict / unknown) and the
    # dimensions that remain unknown — unknown dimensions cap severity.
    dimension_states: dict[str, str] = field(default_factory=dict)
    unknown_dimensions: list[str] = field(default_factory=list)


@dataclass
class CandidateBuildResult:
    candidates: list[ComparisonCandidate] = field(default_factory=list)
    pairs: list[ComparablePair] = field(default_factory=list)
    suppressed_counts: dict[str, int] = field(default_factory=dict)


def _eligible(mention: QuantMention) -> bool:
    if mention.unit_canonical is None or mention.dimension is None:
        return False
    if "multi_number_cell" in mention.flags or "unitless" in mention.flags:
        return False
    if mention.kind == "scalar":
        return mention.value is not None
    return mention.value_low is not None and mention.value_high is not None


def _ambiguous_format(mention: QuantMention) -> bool:
    """Unresolved «1,234»-style tokens never enter comparisons."""
    return "ambiguous_decimal_grouping" in mention.flags


def _is_bound_side(mention: QuantMention) -> bool:
    return mention.modifier in ("upper_bound", "lower_bound") or (
        mention.kind == "range" and "range_inversion" not in mention.flags
    )


def _is_value_side(mention: QuantMention) -> bool:
    return mention.kind == "scalar" and mention.modifier in ("none", "approximate")


# Qualifier semantic axes. Two policies:
# - WILDCARD axes: different STATED tags conflict (planned vs actual must
#   never be compared); an unstated side is uncertainty — the pair survives
#   with a confidence penalty but can never reach high severity.
# - STRICT axes: even explicit-vs-unstated suppresses. An «аварийный»
#   (emergency) value must not be compared with an unstated value as though
#   the unstated one were normal operation, and a permitted-limit value is a
#   norm, not a measurement — comparing it to an unstated actual as a direct
#   contradiction is wrong per se (the bound rule handles limit-vs-actual).
_WILDCARD_AXES: tuple[frozenset[str], ...] = (
    frozenset({"max_onetime", "gross", "annual_mean", "daily_mean"}),
    frozenset({"planned", "actual"}),
    frozenset({"with_treatment", "without_treatment"}),
    frozenset({"accumulated", "generated"}),
)
_STRICT_AXES: tuple[frozenset[str], ...] = (
    frozenset({"emergency", "background"}),
    frozenset({"limit"}),
)


def qualifier_conflict(a: frozenset[str], b: frozenset[str]) -> str | None:
    """Name of the first conflicting axis, or None when compatible."""
    for axis in _WILDCARD_AXES:
        tags_a = a & axis
        tags_b = b & axis
        if tags_a and tags_b and tags_a != tags_b:
            return "|".join(sorted(tags_a | tags_b))
    for axis in _STRICT_AXES:
        tags_a = a & axis
        tags_b = b & axis
        if tags_a != tags_b:  # any one-sided or differing explicit tag
            return "|".join(sorted(tags_a | tags_b))
    return None


# Semantic dimensions used by tri-state compatibility. High severity needs
# every one of them positively MATCHED; any UNKNOWN caps severity at low
# (two absent values never prove sameness); any CONFLICT suppresses.
TRI_STATE_DIMENSIONS = (
    "aggregation_scope",
    "source",
    "sub_entity",
    "metric",
    "substance",
    "period",
    "qualifiers",
)


def assess_pair(a: QuantMention, b: QuantMention) -> tuple[dict[str, str], list[str]]:
    """Tri-state (match / conflict / unknown) per semantic dimension, plus
    the list of ALL suppression reasons (conflicts and unresolvable states).

    Positive-compatibility rules replacing the blanket source-table ban:
    source-level values compare when source AND sub-entity (release point /
    operation) positively align; a shared source number alone is never proof
    that two quantities describe the same real-world sub-entity."""
    states: dict[str, str] = {}
    reasons: list[str] = []
    a_scope, b_scope = a.aggregation_scope, b.aggregation_scope
    a_table = a.location.source_kind == "table_cell"
    b_table = b.location.source_kind == "table_cell"

    # -- aggregation scope --------------------------------------------------------
    if a_scope == "unknown" or b_scope == "unknown":
        states["aggregation_scope"] = "unknown"
        if (a_scope == "unknown" and a_table) or (b_scope == "unknown" and b_table):
            # A table whose facility identity is unknown describes an
            # unidentified slice of reality — never comparable.
            reasons.append("scope_unresolved")
        elif "source" in (a_scope, b_scope):
            reasons.append("scope_unresolved")  # doc claim vs one source
    elif a_scope != b_scope:
        states["aggregation_scope"] = "conflict"
        reasons.append("scope_mismatch")
    else:
        states["aggregation_scope"] = "match"

    # -- source key ---------------------------------------------------------------
    if a.source_key is not None and a.source_key == b.source_key:
        states["source"] = "match"
    elif states.get("aggregation_scope") == "match" and a_scope == "enterprise":
        states["source"] = "match"  # not applicable at enterprise level
    else:
        states["source"] = "unknown"

    # -- sub-entity (release point / operation / equipment) -------------------------
    if a_scope == "source" and b_scope == "source":
        if a.sub_entity is not None and a.sub_entity == b.sub_entity:
            states["sub_entity"] = "match"
        elif a.sub_entity is not None and b.sub_entity is not None:
            states["sub_entity"] = "conflict"
            reasons.append("sub_entity_mismatch")
        else:
            states["sub_entity"] = "unknown"
    elif a_scope == "enterprise" and b_scope == "enterprise":
        states["sub_entity"] = "match"  # not applicable at enterprise level
    else:
        states["sub_entity"] = "unknown"

    # -- metric and substance identity ----------------------------------------------
    # A shared metric must not stand in for an unidentified substance (and vice
    # versa). Direct contradictions require both identities to be established.
    if a.metric_group is not None and b.metric_group is not None:
        if a.metric_group == b.metric_group:
            states["metric"] = "match"
        else:
            states["metric"] = "conflict"
            reasons.append("metric_mismatch")
    else:
        states["metric"] = "unknown"

    if a.substance is not None and b.substance is not None:
        if a.substance == b.substance:
            states["substance"] = "match"
        else:
            states["substance"] = "conflict"
            reasons.append("substance_mismatch")
    else:
        states["substance"] = "unknown"

    # -- period ----------------------------------------------------------------------
    if a.period_key is not None and b.period_key is not None:
        if a.period_key == b.period_key:
            states["period"] = "match"
        else:
            states["period"] = "conflict"
            reasons.append("different_period")
    else:
        states["period"] = "unknown"

    # -- qualifiers --------------------------------------------------------------------
    conflict = qualifier_conflict(frozenset(a.qualifiers), frozenset(b.qualifiers))
    if conflict is not None:
        states["qualifiers"] = "conflict"
        reasons.append(f"qualifier_conflict:{conflict}")
    elif a.qualifiers and set(a.qualifiers) == set(b.qualifiers):
        states["qualifiers"] = "match"
    else:
        # Two empty qualifier sets are UNKNOWN operating conditions, not
        # proof of matching scenarios.
        states["qualifiers"] = "unknown"

    return states, reasons


def _group_key(mention: QuantMention) -> tuple[str, ...]:
    """Semantic grouping. Scope and metric label discriminate only when no
    substance identity exists: a substance-specific claim is the same entity
    whether phrased as a row, a total row of that substance, or narrative —
    the multiplicity guard protects against finer-grained (per-source) rows.
    Periods are checked per pair (stated-vs-stated must be equal; an
    unstated period is a wildcard with a confidence penalty)."""
    has_substance = mention.substance is not None
    return (
        mention.project_id,
        mention.dimension or "",
        mention.substance or "",
        mention.source_key or "",
        "" if has_substance else mention.scope,
        "" if has_substance else (mention.metric_group or ""),
    )


def period_conflict(a: QuantMention, b: QuantMention) -> bool:
    """Two DIFFERENT stated periods must never be compared."""
    return a.period_key is not None and b.period_key is not None and a.period_key != b.period_key


def _relationship(a: QuantMention, b: QuantMention) -> str | None:
    if a.document_id != b.document_id:
        return "cross_document"
    loc_a, loc_b = a.location, b.location
    if loc_a.table_id is not None and loc_a.table_id == loc_b.table_id:
        return None  # same physical table: never a direct comparison
    if (
        loc_a.section_id is not None
        and loc_a.section_id == loc_b.section_id
        # Two numbers in one section stream: compare only when clearly
        # separated (different pages), else it is likely one statement.
        and loc_a.page_number == loc_b.page_number
    ):
        return None
    return "same_document"


def _pair_guards(a: QuantMention, b: QuantMention) -> str | None:
    """Extra structural guards; returns a suppression reason or None."""
    if a.substance is None and a.scope == "item":
        return "no_substance_identity"
    if a.substance is None and a.scope == "total" and (a.metric_group or "") == "":
        return "no_metric_identity"
    return None


def _group_multiplicity_guard(group: list[QuantMention]) -> bool:
    """True when one table holds several DIFFERENT values for this semantic
    key — i.e. the rows are finer-grained entities (per source, per site)
    than the key captures. Cross-comparing such groups is unsafe."""
    values_by_table: dict[str, set[str]] = {}
    for mention in group:
        table_id = mention.location.table_id
        if table_id is not None and mention.canonical_value is not None:
            values_by_table.setdefault(table_id, set()).add(mention.canonical_value)
    return any(len(values) >= 2 for values in values_by_table.values())


def _candidate_confidence(
    a: QuantMention, b: QuantMention, rule: str
) -> tuple[float, list[tuple[str, float]]]:
    factors: list[tuple[str, float]] = []
    confidence = min(a.extraction_confidence, b.extraction_confidence)
    factors.append(("min_extraction_confidence", round(confidence, 2)))
    if a.substance is None:
        confidence -= 0.3
        factors.append(("scope_breadth_unverified", -0.3))
    if a.period_key != b.period_key:
        confidence -= 0.1
        factors.append(("period_incomplete", -0.1))
    elif not a.period_key:
        confidence -= 0.05
        factors.append(("period_unstated", -0.05))
    if a.location.source_kind != b.location.source_kind:
        confidence -= 0.05
        factors.append(("narrative_context_window", -0.05))
    if set(a.qualifiers) != set(b.qualifiers):
        confidence -= 0.1
        factors.append(("qualifier_profile_incomplete", -0.1))
    if a.substance is not None and a.scope != b.scope:
        confidence -= 0.1
        factors.append(("scope_marker_differs", -0.1))
    if a.aggregation_scope == "unknown" or b.aggregation_scope == "unknown":
        confidence -= 0.15
        factors.append(("aggregation_scope_unverified", -0.15))
    confidence = round(max(0.05, min(0.95, confidence)), 2)
    return confidence, factors


def _compatibility(a: QuantMention, b: QuantMention, rule: str) -> dict[str, str]:
    return {
        "dimension": a.dimension or "",
        "substance": a.substance or (b.substance or "(not identified)"),
        "metric_group": a.metric_group or b.metric_group or "(not identified)",
        "period": f"{a.period_key or '(not stated)'} vs {b.period_key or '(not stated)'}",
        "source": f"{a.source_key or '(unknown)'} vs {b.source_key or '(unknown)'}",
        "aggregation_scope": f"{a.aggregation_scope} vs {b.aggregation_scope}",
        "sub_entity": f"{a.sub_entity or '(unknown)'} vs {b.sub_entity or '(unknown)'}",
        "scope": a.scope,
        "qualifiers": (
            f"{'|'.join(a.qualifiers) or '(none)'} vs {'|'.join(b.qualifiers) or '(none)'}"
        ),
        "rule": rule,
        "units": f"{a.unit_canonical} vs {b.unit_canonical}",
    }


def _make_candidate(
    pair_rule: str,
    a: QuantMention,
    b: QuantMention,
    relationship: str,
    status: str,
    suppression_reasons: list[str],
    confidence: float,
    compatibility: dict[str, str],
    dimension_states: dict[str, str] | None = None,
) -> ComparisonCandidate:
    mention_ids = sorted([a.mention_id, b.mention_id])
    return ComparisonCandidate(
        candidate_id=deterministic_id("P3C", pair_rule, *mention_ids),
        rule=pair_rule,
        project_id=a.project_id,
        document_ids=sorted({a.document_id, b.document_id}),
        mention_ids=mention_ids,
        compatibility=compatibility,
        dimension_states=dict(sorted((dimension_states or {}).items())),
        relationship=relationship,  # type: ignore[arg-type]
        confidence=confidence,
        status=status,  # type: ignore[arg-type]
        suppression_reason=suppression_reasons[0] if suppression_reasons else None,
        suppression_reasons=list(suppression_reasons),
    )


def build_candidates(mentions: list[QuantMention]) -> CandidateBuildResult:
    result = CandidateBuildResult()

    def _count(reason: str) -> None:
        result.suppressed_counts[reason] = result.suppressed_counts.get(reason, 0) + 1

    eligible = []
    for mention in mentions:
        if not _eligible(mention):
            continue
        if _ambiguous_format(mention):
            _count("ambiguous_number_format")
            continue
        eligible.append(mention)

    # --- direct-value groups ------------------------------------------------------
    groups: dict[tuple[str, ...], list[QuantMention]] = {}
    for mention in eligible:
        if _is_value_side(mention):
            groups.setdefault(_group_key(mention), []).append(mention)

    near_miss_samples: list[ComparisonCandidate] = []
    samples_per_reason: dict[str, int] = {}

    def _sample_suppressed(
        rule: str,
        a: QuantMention,
        b: QuantMention,
        relationship: str,
        reasons: list[str],
        states: dict[str, str],
    ) -> None:
        # Identity failures are not sampled: every formerly-comparable pair
        # must remain available as an unscored diagnostic with full provenance.
        # Other guard families keep the existing bounded diagnostic sample.
        preserve_all = "identity_not_established" in reasons
        if not preserve_all and not any(
            samples_per_reason.get(r, 0) < SUPPRESSED_SAMPLES_PER_REASON for r in reasons
        ):
            return
        for r in reasons:
            samples_per_reason[r] = samples_per_reason.get(r, 0) + 1
        confidence, _ = _candidate_confidence(a, b, rule)
        near_miss_samples.append(
            _make_candidate(
                rule,
                a,
                b,
                relationship,
                "suppressed",
                reasons,
                confidence,
                _compatibility(a, b, rule),
                states,
            )
        )

    def _sample_guard(rule: str, a: QuantMention, b: QuantMention, reason: str) -> None:
        # Guard rejections fire before a relationship is established; the
        # sample records the pair anyway so every reason family stays
        # auditable with a concrete example, not only a counter.
        states, _ = assess_pair(a, b)
        _sample_suppressed(rule, a, b, _relationship(a, b) or "same_table", [reason], states)

    for key in sorted(groups):
        group = sorted(groups[key], key=lambda m: m.mention_id)
        if len(group) > MAX_GROUP_SIZE:
            _count("group_too_large")
            _sample_guard("direct", group[0], group[1], "group_too_large")
            continue
        if _group_multiplicity_guard(group):
            _count("ambiguous_row_multiplicity")
            _sample_guard("direct", group[0], group[1], "ambiguous_row_multiplicity")
            continue
        distinct_values = {m.canonical_value for m in group if m.canonical_value is not None}
        if len(distinct_values) >= 3:
            # A real duplicate claim is one value stated twice (maybe with one
            # contradiction). Three or more DIFFERENT values for one semantic
            # key mean the key under-resolves the entity (per-source tables,
            # per-site rows) — comparing them would fabricate conflicts.
            _count("ambiguous_entity_resolution")
            _sample_guard("direct", group[0], group[1], "ambiguous_entity_resolution")
            continue
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                relationship = _relationship(a, b)
                if relationship is None:
                    _count("same_physical_location")
                    _sample_guard("direct", a, b, "same_physical_location")
                    continue
                states, reasons = assess_pair(a, b)
                guard = _pair_guards(a, b)
                if guard is not None:
                    reasons = [*reasons, guard]
                unknown_identity = [
                    dimension
                    for dimension in TRI_STATE_DIMENSIONS
                    if states.get(dimension) == "unknown"
                ]
                if unknown_identity:
                    reasons = [
                        *reasons,
                        "identity_not_established",
                        *(f"unknown_{dimension}" for dimension in unknown_identity),
                    ]
                # The same semantic failure can be discovered by more than one
                # guard. Keep a deterministic, complete reason list.
                reasons = list(dict.fromkeys(reasons))
                if reasons:
                    for reason in reasons:
                        _count(reason)
                    _sample_suppressed("direct", a, b, relationship, reasons, states)
                    continue
                confidence, factors = _candidate_confidence(a, b, "direct")
                compatibility = _compatibility(a, b, "direct")
                candidate = _make_candidate(
                    "direct",
                    a,
                    b,
                    relationship,
                    "compared",
                    [],
                    confidence,
                    compatibility,
                    states,
                )
                result.candidates.append(candidate)
                result.pairs.append(
                    ComparablePair(
                        candidate_id=candidate.candidate_id,
                        rule="direct",
                        a=a,
                        b=b,
                        compatibility=compatibility,
                        relationship=relationship,
                        confidence=confidence,
                        confidence_factors=factors,
                        dimension_states=states,
                        unknown_dimensions=sorted(d for d, s in states.items() if s == "unknown"),
                    )
                )

    # --- bound pairs -----------------------------------------------------------------
    bound_groups: dict[tuple[str, ...], list[QuantMention]] = {}
    for mention in eligible:
        key = (
            mention.project_id,
            mention.dimension or "",
            mention.substance or "",
            mention.source_key or "",
        )
        bound_groups.setdefault(key, []).append(mention)

    for key in sorted(bound_groups):
        group = sorted(bound_groups[key], key=lambda m: m.mention_id)
        bounds = [m for m in group if _is_bound_side(m)]
        values = [m for m in group if _is_value_side(m)]
        if not bounds or not values:
            continue
        if len(bounds) * len(values) > MAX_GROUP_SIZE * MAX_GROUP_SIZE:
            _count("group_too_large")
            _sample_guard("bound", bounds[0], values[0], "group_too_large")
            continue
        _, _, substance, _ = key
        for bound in bounds:
            for value in values:
                if not substance and (bound.scope != "total" or value.scope != "total"):
                    _count("bound_without_identity")
                    _sample_guard("bound", bound, value, "bound_without_identity")
                    continue
                relationship = _relationship(bound, value)
                if relationship is None:
                    _count("same_physical_location")
                    _sample_guard("bound", bound, value, "same_physical_location")
                    continue
                # Limit-vs-actual is the point of the rule: assess the pair
                # with the «limit» tag masked out; other axes must align.
                bound_masked = bound.model_copy(
                    update={"qualifiers": [q for q in bound.qualifiers if q != "limit"]}
                )
                value_masked = value.model_copy(
                    update={"qualifiers": [q for q in value.qualifiers if q != "limit"]}
                )
                states, reasons = assess_pair(bound_masked, value_masked)
                if reasons:
                    for reason in reasons:
                        _count(reason)
                    _sample_suppressed("bound", bound, value, relationship, reasons, states)
                    continue
                confidence, factors = _candidate_confidence(bound, value, "bound")
                compatibility = _compatibility(bound, value, "bound")
                candidate = _make_candidate(
                    "bound",
                    bound,
                    value,
                    relationship,
                    "compared",
                    [],
                    confidence,
                    compatibility,
                    states,
                )
                result.candidates.append(candidate)
                result.pairs.append(
                    ComparablePair(
                        candidate_id=candidate.candidate_id,
                        rule="bound",
                        a=bound,
                        b=value,
                        compatibility=compatibility,
                        relationship=relationship,
                        confidence=confidence,
                        confidence_factors=factors,
                        dimension_states=states,
                        unknown_dimensions=sorted(d for d, s in states.items() if s == "unknown"),
                    )
                )

    result.candidates.extend(near_miss_samples)
    result.candidates.sort(key=lambda c: (c.project_id, c.rule, c.candidate_id))
    result.pairs.sort(key=lambda p: p.candidate_id)
    return result
