"""Versioned deterministic configuration for P4.

Every knob is a module constant captured verbatim into
``config_snapshot.json``; there is no config file and no environment
dependence. The engine is intentionally conservative: a cross-document
conflict is only raised from an explicit incompatible IDENTIFIER, never from
lexical similarity.
"""

from __future__ import annotations

from typing import Any

P4_SCORING_CONFIG_VERSION = "1.0.0"

# Contribution points per finding severity. High severity is NEVER emitted in
# this MVP (see scoring.MAX_SEVERITY); the entry exists only so the score
# formula and validator share one table with the sibling pillars.
SEVERITY_POINTS: dict[str, int] = {
    "high": 25,
    "medium": 12,
    "low": 5,
    "info": 2,
}

SCORE_CAP = 100

# --- entity types (grounded in accepted evidence only) -----------------------
ENTITY_TYPES: tuple[str, ...] = (
    "project",
    "document",
    "organization",
    "administrative_location",
    "reporting_period",
    "activity",
    "facility",
    "emission_source",
)

# --- organization roles ------------------------------------------------------
# Positively-marked role of an organization inside a document. Only ``operator``
# organizations participate in the project-identity check; ``designer`` and
# ``unknown`` roles are extracted for the graph but never compared for the
# project's principal identity (a scope guard).
ORG_ROLES: tuple[str, ...] = ("operator", "designer", "unknown")

# Legal-form prefixes recognized for organization extraction (deterministic
# lexicon). The long spellings are folded to their abbreviations for the
# ``legal_form`` qualifier; the abbreviation is NOT part of the normalized name.
LEGAL_FORMS: dict[str, str] = {
    "товарищество с ограниченной ответственностью": "ТОО",
    "акционерное общество": "АО",
    "индивидуальный предприниматель": "ИП",
    "тоо": "ТОО",
    "ао": "АО",
    "оао": "ОАО",
    "зао": "ЗАО",
    "ип кх": "ИП КХ",
    "ип": "ИП",
    "гкп": "ГКП",
}

# Context markers (searched in a window before/around an organization mention)
# that positively establish the operator role. The organization the permit
# documentation is prepared FOR.
OPERATOR_MARKERS: tuple[str, ...] = (
    "для предприятия",
    "наименование предприятия",
    "полное наименование предприятия",
    "сведения об операторе",
    "об операторе",
    "заказчик",
    "оператор",
    "для",
)
# Context markers that positively establish the designer/preparer role. These
# organizations prepared the documentation and are a DIFFERENT scope from the
# operator (comparisons between the two are suppressed, never conflicts).
# Deliberately excludes «директор» / «утверждаю»: a signatory director may sign
# for EITHER the operator or the designer, so it is not a reliable role marker.
DESIGNER_MARKERS: tuple[str, ...] = (
    "разработ",
    "исполнитель",
    "проектная организация",
    "проектную документацию",
)

# --- extraction windows ------------------------------------------------------
# How many leading sections of a document are scanned for package-identity
# claims (operator, period, location, object). Identity statements live in the
# cover / annotation / operator sections, never deep in appendices.
IDENTITY_SECTION_WINDOW = 16
# Character window before an organization mention in which a role marker is
# sought.
ROLE_MARKER_WINDOW_CHARS = 40
# Evidence quote is trimmed to this many characters.
EVIDENCE_QUOTE_CHARS = 200

# --- identifiers -------------------------------------------------------------
# Kazakhstan BIN/IIN is exactly 12 digits. Only an explicit, correctly-shaped
# identifier is treated as an identity signal.
BIN_DIGITS = 12

# --- cross-document check scope ----------------------------------------------
# Document types that describe the SAME reporting instance (one permit package).
# The reporting-period check compares periods only within this set; periods from
# design/construction documents (roos, explanatory notes) are a different
# purpose and are suppressed, never flagged.
REPORTING_INSTANCE_DOC_TYPES: frozenset[str] = frozenset(
    {"ndv", "pek", "puo", "action_plan", "nontechnical_summary"}
)

# Cyrillic administrative-region (oblast) tokens used ONLY by the location check
# to decide whether two document addresses name DIFFERENT recognized oblasts.
# English project-metadata regions are intentionally NOT cross-compared with
# Cyrillic addresses (a representation mismatch is suppressed, never flagged),
# and unrecognized / city-only addresses stay unknown.
LOCATION_REGION_TOKENS: dict[str, str] = {
    "актюбин": "aktobe",
    "кызылорд": "kyzylorda",
    "западно-казахстан": "west_kazakhstan",
    "зко": "west_kazakhstan",
    "абай": "abai",
    "карагандин": "karaganda",
    "алматин": "almaty",
    "павлодар": "pavlodar",
    "костанай": "kostanay",
    "туркестан": "turkestan",
    "мангистау": "mangystau",
    "атырау": "atyrau",
}

# --- activity / category classification --------------------------------------
# A structured activity/category claim is extracted ONLY from an explicit
# classification LABEL (e.g. «категория объекта: II», «вид деятельности (ОКЭД):
# 10.41»), never from free-flowing text. Inline references such as bare
# «II категории» are NOT structured claims — they are ambiguous regulatory
# references and would fabricate false conflicts, so they are deliberately not
# extracted. The accepted corpus contains no such explicit label, so production
# yields zero structured category claims (and zero activity conflicts).
ACTIVITY_CATEGORY_MARKERS: tuple[str, ...] = (
    "категория объекта",
    "категория предприятия",
    "категория производства",
    "вид деятельности (окэд)",
    "код окэд",
    "класс опасности объекта",
)

# Controlled vocabulary: surface value (normalized) -> canonical category.
# Equivalent aliases fold to one canonical (never a conflict); only DISTINCT
# canonicals are mutually exclusive. Keeps transliteration/synonym variants safe.
ACTIVITY_CATEGORY_ALIASES: dict[str, str] = {
    # object hazard categories (roman)
    "i": "object_category_i",
    "ii": "object_category_ii",
    "iii": "object_category_iii",
    "iv": "object_category_iv",
    "1": "object_category_i",
    "2": "object_category_ii",
    "3": "object_category_iii",
    "4": "object_category_iv",
    # industry categories (also the accepted project-metadata industry values)
    "food_production": "food_production",
    "пищевое производство": "food_production",
    "metal_manufacturing": "metal_manufacturing",
    "металлообработка": "metal_manufacturing",
    "construction_materials": "construction_materials",
    "стройматериалы": "construction_materials",
    "chemical_manufacturing": "chemical_manufacturing",
    "химическое производство": "chemical_manufacturing",
    "mining": "mining",
    "добыча": "mining",
    "горнодобыча": "mining",
}

# --- reporting period --------------------------------------------------------
# Reporting periods are extracted only when introduced by an explicit period
# marker (на / период / срок действия) followed by YYYY–YYYY. Bare year ranges
# without such a marker are NOT reporting periods.
PERIOD_YEAR_MIN = 2000
PERIOD_YEAR_MAX = 2100

# --- confidence rubric (deterministic, explainable) --------------------------
# Base confidence per extraction method / claim attribute.
CLAIM_CONFIDENCE: dict[str, float] = {
    "identifier": 0.95,  # explicit BIN
    "operator_name": 0.8,
    "reporting_period": 0.8,
    "administrative_region": 0.9,  # from accepted project metadata
    "administrative_address": 0.6,
    "activity_industry": 0.9,  # from accepted project metadata
    "activity_object": 0.65,
    "facility_object": 0.65,
    "emission_source": 0.85,  # structured «Источник №NNNN.» heading
    "designer_name": 0.7,
    "organization_name": 0.6,
}

# Finding-type base confidence.
FINDING_CONFIDENCE: dict[str, float] = {
    "conflicting_project_identity": 0.85,
    "conflicting_facility_identity": 0.8,
    "conflicting_location": 0.75,
    "conflicting_activity_or_category": 0.7,
    "conflicting_reporting_period": 0.8,
    "conflicting_operator": 0.85,
    "unresolved_entity_identity": 0.4,
    "insufficient_cross_document_context": 0.35,
    "orphan_document_reference": 0.5,
}
CONFIDENCE_MIN = 0.05
CONFIDENCE_MAX = 0.95

# Confidence penalties applied when any participating claim carries the flag.
CONFIDENCE_PENALTIES: dict[str, float] = {
    "ocr_source": 0.15,
    "address_partial": 0.1,
    "single_document": 0.1,
}

# --- resolution --------------------------------------------------------------
# Deterministic resolution signals, in priority order. Identity merges require
# one of these; vague lexical similarity is NEVER a merge signal.
RESOLUTION_SIGNALS: tuple[str, ...] = (
    "shared_identifier",  # same explicit BIN
    "normalized_name_match",  # identical normalized label
    "same_metadata_value",  # identical accepted project-metadata value
)


def config_snapshot() -> dict[str, Any]:
    """Serializable snapshot of every deterministic knob used by a run."""
    from dalel.pillars.cross_document_coherence import P4_VERSION

    return {
        "p4_version": P4_VERSION,
        "scoring_config_version": P4_SCORING_CONFIG_VERSION,
        "severity_points": dict(SEVERITY_POINTS),
        "score_cap": SCORE_CAP,
        "entity_types": list(ENTITY_TYPES),
        "org_roles": list(ORG_ROLES),
        "legal_forms": dict(sorted(LEGAL_FORMS.items())),
        "operator_markers": list(OPERATOR_MARKERS),
        "designer_markers": list(DESIGNER_MARKERS),
        "identity_section_window": IDENTITY_SECTION_WINDOW,
        "role_marker_window_chars": ROLE_MARKER_WINDOW_CHARS,
        "evidence_quote_chars": EVIDENCE_QUOTE_CHARS,
        "bin_digits": BIN_DIGITS,
        "reporting_instance_doc_types": sorted(REPORTING_INSTANCE_DOC_TYPES),
        "location_region_tokens": dict(sorted(LOCATION_REGION_TOKENS.items())),
        "activity_category_markers": list(ACTIVITY_CATEGORY_MARKERS),
        "activity_category_aliases": dict(sorted(ACTIVITY_CATEGORY_ALIASES.items())),
        "period_year_range": [PERIOD_YEAR_MIN, PERIOD_YEAR_MAX],
        "claim_confidence": dict(sorted(CLAIM_CONFIDENCE.items())),
        "finding_confidence": dict(sorted(FINDING_CONFIDENCE.items())),
        "confidence_penalties": dict(sorted(CONFIDENCE_PENALTIES.items())),
        "confidence_bounds": [CONFIDENCE_MIN, CONFIDENCE_MAX],
        "resolution_signals": list(RESOLUTION_SIGNALS),
        "conflict_rule": (
            "a cross-document conflict is raised ONLY from an explicit"
            " incompatible identifier or explicit incompatible value across"
            " positively-matched entities and scope; differing spellings,"
            " quote styles and transliterations are aliases, never conflicts"
        ),
        "llm_used": False,
        "embeddings_used": False,
        "ocr_used_by_p4": False,
        "geospatial_analysis": False,
    }
