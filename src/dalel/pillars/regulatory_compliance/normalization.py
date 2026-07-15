"""Deterministic text normalization and tokenization for P2 retrieval/NLI.

Russian / Kazakh / English: NFKC folding, casefold, ё→е, controlled
tokenization and a small declared stopword list. No stemming libraries and
no language detection — normalization is the same for every input.
"""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[0-9a-zа-яёәғқңөұүһі]+")

# Declared stopwords (RU/KK/EN function words that carry no retrieval
# signal). Deliberately small: over-aggressive lists hurt legal text.
STOPWORDS = frozenset(
    {
        # ru
        "и",
        "в",
        "во",
        "на",
        "не",
        "с",
        "со",
        "по",
        "для",
        "от",
        "до",
        "из",
        "к",
        "о",
        "об",
        "при",
        "за",
        "или",
        "а",
        "но",
        "что",
        "как",
        "это",
        "быть",
        "должен",
        "должна",
        "должно",
        "должны",
        "также",
        "их",
        "его",
        "ее",
        "её",
        "все",
        "том",
        "числе",
        # kk
        "және",
        "мен",
        "бен",
        "пен",
        "үшін",
        "бойынша",
        "туралы",
        "болуы",
        "тиіс",
        "керек",
        "немесе",
        # en
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "for",
        "to",
        "and",
        "or",
        "is",
        "are",
        "be",
        "by",
        "with",
        "shall",
        "must",
        "should",
    }
)

# Very short tokens are almost always noise in this corpus (initials,
# list markers); numbers are kept (article/limit references).
_MIN_TOKEN_LEN = 2


def normalize_text(text: str) -> str:
    """NFKC + casefold + ё→е + whitespace collapse."""
    value = unicodedata.normalize("NFKC", text)
    value = value.casefold().replace("ё", "е")
    return " ".join(value.split())


def tokenize(text: str) -> list[str]:
    """Ordered content tokens of normalized text (stopwords removed)."""
    normalized = normalize_text(text)
    return [
        token
        for token in _TOKEN_RE.findall(normalized)
        if len(token) >= _MIN_TOKEN_LEN and token not in STOPWORDS
    ]


def token_set(text: str) -> frozenset[str]:
    return frozenset(tokenize(text))


def token_matches(a: str, b: str) -> bool:
    """Conservative inflection-tolerant token equality for RU/KK: tokens
    match when they share a long common prefix (≥ 5 chars, ≥ 75% of the
    shorter token, and within 3 chars of the shorter token's full length).
    «слушания»/«слушаний» match; «контроль»/«контракт» do not."""
    if a == b:
        return True
    shorter_len = min(len(a), len(b))
    if shorter_len >= 4 and len(a) == len(b) and a[:-1] == b[:-1]:
        return True  # single final-char inflection («зона»/«зоны»)
    if shorter_len < 5:
        return False
    common = 0
    for char_a, char_b in zip(a, b, strict=False):
        if char_a != char_b:
            break
        common += 1
    required = max(5, -(-3 * shorter_len // 4))  # ceil(0.75 * n)
    return common >= required and common >= shorter_len - 3


def concept_in_text(concept: str, text: str) -> bool:
    """Conservative concept presence: normalized substring, or every concept
    token matched by some text token (inflection-tolerant, word-boundary
    safe). Never a single-token fuzzy leap for short tokens."""
    concept_norm = normalize_text(concept)
    if not concept_norm:
        return False
    text_norm = normalize_text(text)
    if concept_norm in text_norm:
        return True
    concept_tokens = tokenize(concept)
    if not concept_tokens:
        return False
    text_tokens = token_set(text)
    return all(
        any(token_matches(concept_token, text_token) for text_token in text_tokens)
        for concept_token in concept_tokens
    )


def find_snippet(concept: str, text: str, window: int) -> str | None:
    """Bounded evidence snippet around the first concept occurrence.

    Substring match wins; otherwise the window is anchored at the first
    text token that matches any concept token. Returns None when nothing
    matches."""
    text_norm = normalize_text(text)
    concept_norm = normalize_text(concept)
    anchor = text_norm.find(concept_norm) if concept_norm else -1
    anchor_len = len(concept_norm)
    if anchor < 0:
        concept_tokens = tokenize(concept)
        for match in _TOKEN_RE.finditer(text_norm):
            token = match.group(0)
            if any(token_matches(concept_token, token) for concept_token in concept_tokens):
                anchor = match.start()
                anchor_len = len(token)
                break
    if anchor < 0:
        return None
    start = max(0, anchor - window // 2)
    end = min(len(text_norm), anchor + anchor_len + window // 2)
    return text_norm[start:end]
