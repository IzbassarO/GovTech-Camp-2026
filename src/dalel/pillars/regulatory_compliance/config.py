"""Versioned deterministic configuration for P2.

Every knob is a module constant captured verbatim into
``config_snapshot.json``; there is no config file. The only environment
dependence is the OPTIONAL external LLM provider, which is never enabled
by default and never used by tests.
"""

from __future__ import annotations

from typing import Any

P2_SCORING_CONFIG_VERSION = "1.0.0"

# Contribution points per finding severity (same scale as P1/P3).
SEVERITY_POINTS: dict[str, int] = {
    "high": 25,
    "medium": 12,
    "low": 5,
    "info": 2,
}
SCORE_CAP = 100

# --- corpus -------------------------------------------------------------------
SUPPORTED_CORPUS_VERSIONS = frozenset({"1.0.0"})
DEMO_CORPUS_WARNING = "Illustrative demo regulatory corpus. Not an authoritative legal source."

# --- retrieval ----------------------------------------------------------------
DEFAULT_TOP_K = 5
# A requirement below this lexical score is not considered retrieved for the
# query at all (weak topical noise must not force a regulation match).
MIN_RETRIEVAL_SCORE = 0.05
# A potential_conflict label additionally requires at least this retrieval
# score — weak retrieval evidence can never become a conflict claim.
CONFLICT_MIN_RETRIEVAL_SCORE = 0.15
# Additive boosts, recorded per retrieval record.
EXACT_TERM_BOOST = 0.05  # per query token found verbatim in the title
EXACT_TERM_BOOST_CAP = 0.15
APPLICABILITY_TAG_BOOST = 0.15  # project document types match applicability
TOPIC_BOOST = 0.10  # requirement topic named in the query
SCORE_DECIMALS = 6  # serialized score rounding (byte-stable artifacts)

# --- deterministic NLI ---------------------------------------------------------
# Rubric confidences per decision path (recorded with factors).
NLI_CONFIDENCE: dict[str, float] = {
    "document_present": 0.9,
    "document_missing": 0.8,
    "section_heading_match": 0.85,
    "section_text_match": 0.7,
    "explicit_negation": 0.7,
    "insufficient_evidence": 0.4,
    "not_applicable": 0.75,
    "applicability_unknown": 0.35,
}
# Evidence text snippet window (characters) around a concept match.
SNIPPET_WINDOW = 160
# Explicit negation markers examined INSIDE the matched snippet only.
NEGATION_MARKERS: tuple[str, ...] = (
    "не предусмотрен",
    "не предусмотрена",
    "не предусмотрено",
    "не проводится",
    "не проводятся",
    "не осуществляется",
    "не выполняется",
    "отсутствует",
    "отсутствуют",
)

# --- severity policy -----------------------------------------------------------
# Baseline (non-demo) severity per finding type; the scoring module applies
# the demo cap and the high-severity gate on top of these.
BASE_SEVERITY: dict[str, str] = {
    "missing_required_document": "medium",
    "missing_required_section": "medium",
    "potential_regulatory_conflict": "medium",
    "insufficient_regulatory_evidence": "info",
    "applicability_uncertain": "info",
    "outdated_or_unknown_regulation_version": "info",
    "non_authoritative_demo_requirement": "info",
    "malformed_regulatory_source": "info",
}
# Findings sourced from a demo-only requirement can never exceed this.
DEMO_SEVERITY_CAP = "low"
# High severity requires ALL of: authoritative requirement, confirmed
# applicability, strong inference confidence and no quality flags.
HIGH_MIN_CONFIDENCE = 0.85

# --- optional LLM provider ------------------------------------------------------
# Environment variable names (AlemLLM-ready provider architecture: an
# OpenAI-compatible endpoint is configured entirely through these).
ENV_LLM_PROVIDER = "LLM_PROVIDER"
ENV_LLM_BASE_URL = "LLM_BASE_URL"
ENV_LLM_API_KEY = "LLM_API_KEY"  # variable NAME, not a secret
ENV_LLM_MODEL = "LLM_MODEL"
LLM_TEMPERATURE = 0.0
LLM_TIMEOUT_SECONDS = 60
LLM_MAX_EVIDENCE_ITEMS = 12  # evidence items passed to the provider


def config_snapshot() -> dict[str, Any]:
    from dalel.pillars.regulatory_compliance import P2_VERSION

    return {
        "p2_version": P2_VERSION,
        "scoring_config_version": P2_SCORING_CONFIG_VERSION,
        "severity_points": dict(SEVERITY_POINTS),
        "score_cap": SCORE_CAP,
        "supported_corpus_versions": sorted(SUPPORTED_CORPUS_VERSIONS),
        "default_top_k": DEFAULT_TOP_K,
        "min_retrieval_score": MIN_RETRIEVAL_SCORE,
        "conflict_min_retrieval_score": CONFLICT_MIN_RETRIEVAL_SCORE,
        "exact_term_boost": EXACT_TERM_BOOST,
        "exact_term_boost_cap": EXACT_TERM_BOOST_CAP,
        "applicability_tag_boost": APPLICABILITY_TAG_BOOST,
        "topic_boost": TOPIC_BOOST,
        "score_decimals": SCORE_DECIMALS,
        "nli_confidence": dict(NLI_CONFIDENCE),
        "snippet_window": SNIPPET_WINDOW,
        "negation_markers": list(NEGATION_MARKERS),
        "base_severity": dict(BASE_SEVERITY),
        "demo_severity_cap": DEMO_SEVERITY_CAP,
        "high_min_confidence": HIGH_MIN_CONFIDENCE,
        "llm_temperature": LLM_TEMPERATURE,
        "demo_corpus_warning": DEMO_CORPUS_WARNING,
    }
