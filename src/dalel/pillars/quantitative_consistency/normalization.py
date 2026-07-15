"""Deterministic text normalization for P3 (no locale, no LLM).

Superscripts are translated BEFORE NFKC: NFKC alone would fold ``10⁵`` into
``105`` and silently corrupt scientific notation. Unit spellings (``м³`` vs
``м3``) still normalize consistently because superscript digits after a
letter are digit-folded, while superscripts after ``10``/``^`` become an
explicit exponent marker first.
"""

from __future__ import annotations

import re
import unicodedata

# Unicode spaces that appear as thousands separators in the corpus.
NBSP_CHARS = "    "

_SUPERSCRIPT_MAP = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁻": "-",
    "⁺": "+",
}
_SUPERSCRIPT_RE = re.compile("[" + "".join(_SUPERSCRIPT_MAP) + "]+")
# ``10⁵`` / ``10^5``-style powers: the superscript run directly after ``10``.
_POWER_RE = re.compile(r"(?<=10)([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)")

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s%]", re.UNICODE)


_DEGREE_RE = re.compile(r"(?<=\d)⁰(?!\d)")


def fold_superscripts(text: str) -> str:
    """``10⁵`` → ``10^5``; ``47⁰`` → ``47°`` (degree, corpus coordinates);
    remaining superscripts digit-fold (``м³`` → ``м3``)."""

    def _power(match: re.Match[str]) -> str:
        return "^" + "".join(_SUPERSCRIPT_MAP[ch] for ch in match.group(1))

    text = _POWER_RE.sub(_power, text)
    text = _DEGREE_RE.sub("°", text)

    def _plain(match: re.Match[str]) -> str:
        return "".join(_SUPERSCRIPT_MAP[ch] for ch in match.group(0))

    return _SUPERSCRIPT_RE.sub(_plain, text)


def normalize_for_scan(text: str) -> str:
    """Prepare raw block text for numeric scanning WITHOUT changing offsets
    semantics: superscript folding may change length, so scanning always runs
    on the normalized string and evidence quotes are taken from it too."""
    value = fold_superscripts(text)
    value = unicodedata.normalize("NFKC", value)
    # Unify unicode minus/dashes used in ranges and negative numbers.
    value = value.replace("−", "-")
    # Thousands NBSP variants become plain spaces (still separators).
    for char in NBSP_CHARS:
        value = value.replace(char, " ")
    return value


def normalize_label(text: str) -> str:
    """Casefolded, punctuation-free, whitespace-collapsed label text for
    lexicon matching (row labels, column headers, sentence windows)."""
    value = unicodedata.normalize("NFKC", fold_superscripts(text))
    value = value.casefold().replace("ё", "е")
    value = _PUNCT_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def label_tokens(text: str) -> frozenset[str]:
    return frozenset(token for token in normalize_label(text).split(" ") if token)


def normalize_unit_text(text: str) -> str:
    """Canonical key for the declared unit-alias registry lookup.

    Deterministic and alias-oriented: superscripts folded, casefold, ё→е,
    all whitespace removed, trailing dots kept OUT of the key (``тыс.`` and
    ``тыс`` map identically). No fuzzy matching happens on top of this.
    """
    value = unicodedata.normalize("NFKC", fold_superscripts(text))
    value = value.casefold().replace("ё", "е")
    for char in NBSP_CHARS:
        value = value.replace(char, "")
    value = value.replace(" ", "")
    value = value.replace(".", "")
    return value
