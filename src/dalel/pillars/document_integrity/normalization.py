"""Deterministic text normalization for heading matching (no LLM)."""

from __future__ import annotations

import re
import unicodedata

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_LEADING_NUM_RE = re.compile(r"^[\d\s.\-–—)(]+")


def normalize_title(text: str) -> str:
    """Unicode NFKC → casefold → ё→е → strip leading numbering → drop
    punctuation → collapse whitespace."""
    value = unicodedata.normalize("NFKC", text)
    value = value.casefold().replace("ё", "е")
    value = _LEADING_NUM_RE.sub(" ", value)
    value = _PUNCT_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def title_tokens(text: str) -> frozenset[str]:
    return frozenset(token for token in normalize_title(text).split(" ") if token)
