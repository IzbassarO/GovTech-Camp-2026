"""Deterministic value normalization for P4.

Normalization is the ONLY mechanism by which spelling, spacing, quote-style and
casing differences are collapsed into one identity. It never does fuzzy
similarity: two values are the same iff their normalized forms are byte-equal.
This is what makes «Синтез Урал», «СИНТЕЗ УРАЛ» and "Синтез Урал" one entity
while keeping genuinely different names apart.
"""

from __future__ import annotations

import re
import unicodedata

from dalel.pillars.cross_document_coherence.config import (
    BIN_DIGITS,
    LEGAL_FORMS,
    PERIOD_YEAR_MAX,
    PERIOD_YEAR_MIN,
)

# Every quote / guillemet / apostrophe surface form folds to nothing.
_QUOTES = "«»“”„‟\"'`‘’«»"
_QUOTE_RE = re.compile(f"[{re.escape(_QUOTES)}]")
_WS_RE = re.compile(r"\s+")
# Legal-form prefixes, longest first so "товарищество с ограниченной..." wins
# over "тоо" and "ип кх" wins over "ип".
_LEGAL_FORMS_SORTED = sorted(LEGAL_FORMS.items(), key=lambda kv: -len(kv[0]))


def collapse_whitespace(text: str) -> str:
    """NFC-normalize, collapse every whitespace run to a single space, strip."""
    normalized = unicodedata.normalize("NFC", text)
    return _WS_RE.sub(" ", normalized).strip()


def normalize_text(text: str) -> str:
    """Case-folded, quote-stripped, whitespace-collapsed comparison key."""
    without_quotes = _QUOTE_RE.sub(" ", text)
    return collapse_whitespace(without_quotes).casefold()


def strip_legal_form(name: str) -> tuple[str | None, str]:
    """Split a leading legal-form prefix from an organization name.

    Returns ``(legal_form_abbreviation | None, remainder_casefolded_key)``.
    The legal form is deliberately NOT part of the identity key: «АО "АЗМ"» and
    a bare «АЗМ» share the same normalized name (the legal form is a qualifier,
    not an identifier). Only an explicit BIN merges across genuinely different
    surface names.
    """
    key = normalize_text(name)
    for spelling, abbreviation in _LEGAL_FORMS_SORTED:
        if key == spelling:
            # Name is only a legal form — no usable identity remainder.
            return abbreviation, ""
        prefix = spelling + " "
        if key.startswith(prefix):
            return abbreviation, key[len(prefix) :].strip()
    return None, key


def normalize_org_name(name: str) -> tuple[str, str, str | None]:
    """Return ``(canonical_label, normalized_key, legal_form)`` for an org.

    ``canonical_label`` is the trimmed human-readable surface form (guillemets
    dropped, whitespace collapsed). ``normalized_key`` is the identity key used
    for resolution.
    """
    canonical = _QUOTE_RE.sub(" ", name)
    canonical = collapse_whitespace(canonical)
    legal_form, remainder = strip_legal_form(name)
    key = remainder or normalize_text(name)
    return canonical, key, legal_form


def normalize_bin(raw: str) -> str | None:
    """Return a 12-digit BIN if the string is exactly one, else ``None``."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == BIN_DIGITS:
        return digits
    return None


def normalize_period(start: str, end: str) -> str | None:
    """Return a canonical ``YYYY-YYYY`` period, validating the year window and
    ordering. ``None`` when either year is out of range or inverted."""
    try:
        a = int(start)
        b = int(end)
    except (TypeError, ValueError):
        return None
    if not (PERIOD_YEAR_MIN <= a <= PERIOD_YEAR_MAX and PERIOD_YEAR_MIN <= b <= PERIOD_YEAR_MAX):
        return None
    if b < a:
        return None
    return f"{a}-{b}"


def normalize_region(region: str) -> str:
    """Normalized comparison key for an administrative region / metadata value."""
    return normalize_text(region)


def normalize_address(address: str) -> str:
    """Normalized comparison key for a free-text administrative address."""
    return normalize_text(address)
