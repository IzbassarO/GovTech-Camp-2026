"""Deterministic section matching (no LLM, no embeddings).

Four separately reported methods, cheapest first:

1. ``exact_equality`` — normalized heading == normalized alias;
2. ``normalized_substring`` — normalized alias is a substring of the heading
   (never labelled "exact": the independent verifier requires the split);
3. ``token_overlap`` — alias tokens are a subset of heading tokens, or Jaccard
   overlap reaches the threshold;
4. ``fuzzy`` — SequenceMatcher ratio over the whole normalized strings, but
   ONLY together with discriminative token evidence: at least one shared
   non-generic token (exactly, or with per-token similarity >= 0.85). A match
   supported solely by a generic token («воздействие», «раздел», …) is
   rejected and recorded as a rejected candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from dalel.pillars.document_integrity.config import (
    FUZZY_RATIO_THRESHOLD,
    FUZZY_TOKEN_RATIO_THRESHOLD,
    GENERIC_TOKENS,
    TOKEN_OVERLAP_THRESHOLD,
)
from dalel.pillars.document_integrity.normalization import normalize_title, title_tokens
from dalel.pillars.document_integrity.taxonomy import SectionRule


@dataclass
class HeadingCandidate:
    """An observed heading with its page (when known)."""

    title: str
    page_number: int | None = None


@dataclass
class RejectedFuzzyCandidate:
    observed_heading: str
    matched_alias: str
    ratio: float
    reason: str


@dataclass
class SectionMatch:
    rule: SectionRule
    matched: bool
    method: str  # exact_equality | normalized_substring | token_overlap | fuzzy | none
    matched_title: str | None = None
    matched_alias: str | None = None
    normalized_heading: str | None = None
    page_number: int | None = None
    score: float | None = None
    discriminative_tokens: list[str] = field(default_factory=list)
    rejected_fuzzy: list[RejectedFuzzyCandidate] = field(default_factory=list)


def _iter_aliases(rule: SectionRule) -> list[str]:
    return [*rule.aliases_ru, *rule.aliases_kk, rule.canonical_section]


def discriminative_token_evidence(alias: str, title: str) -> list[str]:
    """Shared non-generic tokens (exact, or fuzzy at per-token threshold)."""
    alias_tokens = {t for t in title_tokens(alias) if t not in GENERIC_TOKENS}
    heading_tokens = {t for t in title_tokens(title) if t not in GENERIC_TOKENS}
    evidence = sorted(alias_tokens & heading_tokens)
    if evidence:
        return evidence
    for alias_token in sorted(alias_tokens):
        for heading_token in sorted(heading_tokens):
            ratio = SequenceMatcher(None, alias_token, heading_token).ratio()
            if ratio >= FUZZY_TOKEN_RATIO_THRESHOLD:
                evidence.append(f"{alias_token}~{heading_token}")
    return evidence


def match_rule(rule: SectionRule, headings: list[HeadingCandidate]) -> SectionMatch:
    normalized = [
        (candidate, normalize_title(candidate.title)) for candidate in headings if candidate.title
    ]
    aliases = [(alias, normalize_title(alias)) for alias in _iter_aliases(rule)]

    # 1. exact_equality
    for candidate, heading_norm in normalized:
        for alias, alias_norm in aliases:
            if heading_norm and heading_norm == alias_norm:
                return SectionMatch(
                    rule,
                    True,
                    "exact_equality",
                    candidate.title,
                    alias,
                    heading_norm,
                    candidate.page_number,
                    1.0,
                    discriminative_tokens=sorted(
                        t for t in title_tokens(alias) if t not in GENERIC_TOKENS
                    ),
                )

    # 2. normalized_substring (alias inside heading; alias long enough to be
    # meaningful — never reported as exact).
    for candidate, heading_norm in normalized:
        for alias, alias_norm in aliases:
            if alias_norm and len(alias_norm) >= 6 and alias_norm in heading_norm:
                return SectionMatch(
                    rule,
                    True,
                    "normalized_substring",
                    candidate.title,
                    alias,
                    heading_norm,
                    candidate.page_number,
                    1.0,
                    discriminative_tokens=sorted(
                        t for t in title_tokens(alias) if t not in GENERIC_TOKENS
                    ),
                )

    # 3. token_overlap
    for candidate, heading_norm in normalized:
        tokens = title_tokens(candidate.title)
        if not tokens:
            continue
        for alias, _alias_norm in aliases:
            alias_tokens = title_tokens(alias)
            if not alias_tokens:
                continue
            if alias_tokens <= tokens:
                return SectionMatch(
                    rule,
                    True,
                    "token_overlap",
                    candidate.title,
                    alias,
                    heading_norm,
                    candidate.page_number,
                    1.0,
                    discriminative_tokens=sorted((alias_tokens & tokens) - GENERIC_TOKENS),
                )
            overlap = len(tokens & alias_tokens) / len(tokens | alias_tokens)
            if overlap >= TOKEN_OVERLAP_THRESHOLD:
                return SectionMatch(
                    rule,
                    True,
                    "token_overlap",
                    candidate.title,
                    alias,
                    heading_norm,
                    candidate.page_number,
                    round(overlap, 3),
                    discriminative_tokens=sorted((alias_tokens & tokens) - GENERIC_TOKENS),
                )

    # 4. fuzzy with discriminative evidence
    rejected: list[RejectedFuzzyCandidate] = []
    best: SectionMatch | None = None
    best_ratio = 0.0
    for candidate, heading_norm in normalized:
        for alias, alias_norm in aliases:
            if not alias_norm or not heading_norm:
                continue
            ratio = SequenceMatcher(None, heading_norm, alias_norm).ratio()
            if ratio < FUZZY_RATIO_THRESHOLD:
                if ratio > best_ratio:
                    best_ratio = ratio
                continue
            evidence = discriminative_token_evidence(alias, candidate.title)
            if not evidence:
                rejected.append(
                    RejectedFuzzyCandidate(
                        observed_heading=candidate.title,
                        matched_alias=alias,
                        ratio=round(ratio, 3),
                        reason=("no shared discriminative token; overlap is generic-only"),
                    )
                )
                continue
            if best is None or ratio > (best.score or 0.0):
                best = SectionMatch(
                    rule,
                    True,
                    "fuzzy",
                    candidate.title,
                    alias,
                    heading_norm,
                    candidate.page_number,
                    round(ratio, 3),
                    discriminative_tokens=evidence,
                )
    if best is not None:
        best.rejected_fuzzy = rejected
        return best

    no_match = SectionMatch(rule, False, "none", None, None, None, None, round(best_ratio, 3))
    no_match.rejected_fuzzy = rejected
    return no_match


def match_document_sections(
    rules: list[SectionRule], headings: list[HeadingCandidate]
) -> list[SectionMatch]:
    return [match_rule(rule, headings) for rule in rules]
