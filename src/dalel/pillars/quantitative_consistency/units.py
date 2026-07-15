"""Controlled unit registry: declared aliases only, no fuzzy conversion.

Design rules (mirroring the corpus survey):

- Every alias is DECLARED and normalized through ``normalize_unit_text``
  (superscript folding, casefold, whitespace/dot removal) — no substring
  guessing over arbitrary text.
- A dimension is a ``(kind, time_basis)`` pair: rates with different time
  bases (``г/с`` vs ``т/год``) are NOT interconvertible because inferring
  operating hours is forbidden. ``мг/нм3`` (normal cubic meter) is its own
  kind — converting it to ``мг/м3`` needs temperature/pressure data P3
  does not have.
- Conversion factors are exact ``Decimal`` multipliers to the canonical
  unit of the dimension; every conversion is reproducible from the snapshot
  in ``config_snapshot.json``.
- OCR homoglyphs seen in the corpus (Latin ``c`` in ``г/c``) are folded by
  a declared translation, not by similarity matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from dalel.pillars.quantitative_consistency.normalization import normalize_unit_text

# Latin -> Cyrillic homoglyphs that occur inside unit strings in the corpus.
_HOMOGLYPHS = str.maketrans(
    {
        "c": "с",  # latin c -> cyrillic es («г/c»)
        "m": "м",
        "k": "к",  # only applied to unit lookup keys, never to free text
        "e": "е",
        "x": "х",
        "o": "о",
        "p": "р",
        "a": "а",
        "h": "н",
        "t": "т",
    }
)


@dataclass(frozen=True)
class UnitDef:
    """One canonical unit spelling with its dimension and conversion."""

    canonical: str  # canonical display spelling, e.g. "т/год"
    kind: str  # mass | mass_rate | volume | ...
    time_basis: str | None  # s | h | day | month | year | None
    factor: Decimal  # multiplier to the dimension's canonical unit


# Canonical unit per (kind, time_basis) for reporting conversions.
CANONICAL_UNITS: dict[tuple[str, str | None], str] = {
    ("mass", None): "г",
    ("mass_rate", "s"): "г/с",
    ("mass_rate", "h"): "г/ч",
    ("mass_rate", "day"): "г/сут",
    ("mass_rate", "month"): "г/мес",
    ("mass_rate", "year"): "г/год",
    ("volume", None): "м3",
    ("volume_rate", "s"): "м3/с",
    ("volume_rate", "h"): "м3/ч",
    ("volume_rate", "day"): "м3/сут",
    ("volume_rate", "year"): "м3/год",
    ("concentration", None): "мг/м3",
    ("concentration_normal", None): "мг/нм3",
    ("density", None): "кг/м3",
    ("mass_fraction", None): "мг/кг",
    ("area", None): "м2",
    ("percent", None): "%",
    ("percent_points", None): "п.п.",
    ("power", None): "Вт",
    ("temperature", None): "°C",
    ("velocity", None): "м/с",
    ("length", None): "м",
}


def _u(canonical: str, kind: str, basis: str | None, factor: str) -> UnitDef:
    return UnitDef(canonical=canonical, kind=kind, time_basis=basis, factor=Decimal(factor))


# alias spelling (pre-normalization) -> UnitDef. Aliases are written the way
# they appear in documents; the registry key is their normalized form.
_ALIASES: dict[str, UnitDef] = {}


def _register(unit: UnitDef, *aliases: str) -> None:
    for alias in aliases:
        key = normalize_unit_text(alias)
        existing = _ALIASES.get(key)
        if existing is not None and existing != unit:
            raise ValueError(f"conflicting unit alias {alias!r} ({key!r})")
        _ALIASES[key] = unit


# --- mass ---------------------------------------------------------------------
_register(_u("мг", "mass", None, "0.001"), "мг", "mg")
_register(_u("г", "mass", None, "1"), "г", "гр", "g")
_register(_u("кг", "mass", None, "1000"), "кг", "kg")
_register(
    _u("т", "mass", None, "1000000"),
    "т",
    "тн",
    "тонн",
    "тонна",
    "тонны",
    "t",
    "ton",
    "tons",
    "tonne",
    "tonnes",
)
_register(_u("тыс. т", "mass", None, "1000000000"), "тыс. т", "тыс. тонн", "тыс тонн")

# --- mass rate: per second ----------------------------------------------------
_register(_u("мг/с", "mass_rate", "s", "0.001"), "мг/с", "mg/s")
_register(_u("г/с", "mass_rate", "s", "1"), "г/с", "г/сек", "g/s", "г/c")
_register(_u("кг/с", "mass_rate", "s", "1000"), "кг/с", "kg/s")

# --- mass rate: per hour --------------------------------------------------------
_register(_u("г/ч", "mass_rate", "h", "1"), "г/ч", "г/час", "g/h")
_register(_u("кг/ч", "mass_rate", "h", "1000"), "кг/ч", "кг/час", "kg/h")
_register(_u("т/ч", "mass_rate", "h", "1000000"), "т/ч", "т/час", "t/h")

# --- mass rate: per day ---------------------------------------------------------
_register(
    _u("кг/сут", "mass_rate", "day", "1000"),
    "кг/сут",
    "кг/сутки",
    "кг/тәулік",
    "kg/day",
)
_register(
    _u("т/сут", "mass_rate", "day", "1000000"),
    "т/сут",
    "т/сутки",
    "тонн в сутки",
    "т/тәулік",
    "t/day",
)

# --- mass rate: per month -------------------------------------------------------
_register(_u("т/мес", "mass_rate", "month", "1000000"), "т/мес", "т/месяц", "t/month")

# --- mass rate: per year --------------------------------------------------------
_register(_u("мг/год", "mass_rate", "year", "0.001"), "мг/год")
_register(_u("г/год", "mass_rate", "year", "1"), "г/год", "g/year")
_register(_u("кг/год", "mass_rate", "year", "1000"), "кг/год", "kg/year", "кг/жыл")
_register(
    _u("т/год", "mass_rate", "year", "1000000"),
    "т/год",
    "т/г",
    "т/жыл",
    "тонн/год",
    "тонна/год",
    "тонн в год",
    "t/year",
    "t/yr",
    "tonnes/year",
    "tonnes per year",
)
_register(
    _u("тыс. т/год", "mass_rate", "year", "1000000000"),
    "тыс. т/год",
    "тыс. тонн/год",
    "тыс. тонн в год",
)

# --- volume ---------------------------------------------------------------------
_register(_u("мл", "volume", None, "0.000001"), "мл", "ml")
_register(_u("л", "volume", None, "0.001"), "л", "l", "дм3", "дм³")
_register(_u("м3", "volume", None, "1"), "м3", "м³", "m3", "куб. м", "куб.м", "м куб")
_register(
    _u("тыс. м3", "volume", None, "1000"),
    "тыс. м3",
    "тыс.м3",
    "тыс м3",
    "тыс. м³",
    "тыс,м3",
    "thousand m3",
)
_register(_u("млн м3", "volume", None, "1000000"), "млн м3", "млн. м3", "млн.м3", "million m3")

# --- volume rate ------------------------------------------------------------------
_register(_u("л/с", "volume_rate", "s", "0.001"), "л/с", "l/s")
_register(_u("м3/с", "volume_rate", "s", "1"), "м3/с", "м³/с", "m3/s")
_register(_u("м3/ч", "volume_rate", "h", "1"), "м3/ч", "м3/час", "м³/ч", "m3/h")
_register(_u("м3/сут", "volume_rate", "day", "1"), "м3/сут", "м3/сутки", "м³/сут", "m3/day")
_register(_u("м3/год", "volume_rate", "year", "1"), "м3/год", "м³/год", "m3/year")
_register(
    _u("тыс. м3/год", "volume_rate", "year", "1000"),
    "тыс. м3/год",
    "тыс.м3/год",
    "тыс м3/год",
    "тыс. м³/год",
)

# --- concentration (actual cubic meter) ---------------------------------------------
_register(_u("мкг/м3", "concentration", None, "0.001"), "мкг/м3", "мкг/м³", "µg/m3", "мкг/m3")
_register(_u("мг/м3", "concentration", None, "1"), "мг/м3", "мг/м³", "mg/m3")
_register(_u("г/м3", "concentration", None, "1000"), "г/м3", "г/м³", "g/m3")
# мг/л == мг/дм3 == г/м3 exactly (1 л = 0.001 м3).
_register(_u("мг/л", "concentration", None, "1000"), "мг/л", "mg/l", "мг/дм3", "мг/дм³")
_register(_u("г/л", "concentration", None, "1000000"), "г/л", "g/l")

# --- concentration at normal conditions (NOT convertible to actual m3) ---------------
_register(_u("мг/нм3", "concentration_normal", None, "1"), "мг/нм3", "мг/нм³", "mg/nm3")
_register(_u("г/нм3", "concentration_normal", None, "1000"), "г/нм3")

# --- mass fraction ---------------------------------------------------------------------
_register(_u("мг/кг", "mass_fraction", None, "1"), "мг/кг", "mg/kg")
_register(_u("г/кг", "mass_fraction", None, "1000"), "г/кг", "g/kg")
_register(_u("г/т", "mass_fraction", None, "1"), "г/т", "g/t")
_register(_u("кг/т", "mass_fraction", None, "1000"), "кг/т", "kg/t")

# --- area ------------------------------------------------------------------------------
_register(_u("м2", "area", None, "1"), "м2", "м²", "m2", "кв. м", "кв.м", "кв м")
_register(_u("га", "area", None, "10000"), "га", "ha", "гектар", "гектара", "гектаров")
_register(_u("км2", "area", None, "1000000"), "км2", "км²", "km2", "кв. км", "кв.км")

# --- percent ------------------------------------------------------------------------------
_register(_u("%", "percent", None, "1"), "%", "проц", "процент", "процента", "процентов", "пайыз")
_register(
    _u("п.п.", "percent_points", None, "1"),
    "п.п.",
    "проц. пункт",
    "процентных пункта",
    "percentage point",
    "percentage points",
)

# --- density (NOT convertible to air/liquid concentration by policy) ---------------
_register(_u("кг/м3", "density", None, "1"), "кг/м3", "кг/м³", "kg/m3")
_register(_u("г/см3", "density", None, "1000"), "г/см3", "г/см³", "g/cm3")
_register(_u("т/м3", "density", None, "1000"), "т/м3", "т/м³", "t/m3")

# --- power (present in the corpus: кВт) -------------------------------------------------
_register(_u("Вт", "power", None, "1"), "вт", "w")
_register(_u("кВт", "power", None, "1000"), "квт", "kw")
_register(_u("МВт", "power", None, "1000000"), "мвт", "mw")

# --- temperature (negative values are legitimate) -----------------------------------------
_register(_u("°C", "temperature", None, "1"), "°с", "°c", "град. с", "гр. с")

# --- velocity (wind speeds are frequent; recognized to avoid misparses) --------------------
_register(_u("м/с", "velocity", None, "1"), "м/с", "m/s")

# --- length ---------------------------------------------------------------------------------
_register(_u("мм", "length", None, "0.001"), "мм", "mm")
_register(_u("см", "length", None, "0.01"), "см", "cm")
_register(_u("м", "length", None, "1"), "м", "m", "метров", "метра")
_register(_u("км", "length", None, "1000"), "км", "km")


@dataclass(frozen=True)
class UnitMatch:
    """A unit recognized immediately after a numeric token."""

    raw: str  # raw matched text, verbatim
    unit: UnitDef


# Longest-first matching over the following text. A candidate must be cut at
# a boundary: the character after the match may not be a word character
# (so «га» does not match inside «газ»).
_MAX_ALIAS_LEN = max(len(k) for k in _ALIASES)
_WORDCHAR_RE = re.compile(r"\w", re.UNICODE)


def match_unit_after(text: str, start: int, window: int) -> UnitMatch | None:
    """Match a declared unit alias in ``text`` beginning at ``start``.

    Leading spaces/commas (OCR debris like «,т/год») are skipped. Matching is
    longest-declared-alias-first over the normalized candidate; nothing else
    in the text is interpreted.
    """
    idx = start
    limit = min(len(text), start + window)
    while idx < limit and text[idx] in " \t,":
        idx += 1
    if idx >= limit:
        return None
    best: UnitMatch | None = None
    max_end = min(len(text), idx + _MAX_ALIAS_LEN + 6)  # +6 for removable spaces/dots
    for end in range(idx + 1, max_end + 1):
        candidate = text[idx:end]
        if "\n" in candidate:
            break
        stripped = candidate.strip()
        if len(stripped) == 1 and stripped.isupper():
            # A standalone UPPERCASE letter after a number («К=0,2 Т») is a
            # formula variable in this corpus, not a lowercase unit («т»).
            continue
        unit = lookup_unit(candidate)
        if unit is not None:
            # Boundary: neither a word character NOR a compound continuation.
            # «г/см3» must not prefix-match as «г» — the trailing «/…» marks
            # an UNSUPPORTED compound unit, which must stay unmatched unless
            # a longer declared alias consumes it entirely.
            boundary_ok = end >= len(text) or (
                not _WORDCHAR_RE.match(text[end]) and text[end] not in "/·*×^"
            )
            if boundary_ok:
                best = UnitMatch(raw=text[idx:end], unit=unit)
    return best


def lookup_unit(text: str) -> UnitDef | None:
    """Exact declared-alias lookup for a complete unit string."""
    key = normalize_unit_text(text)
    if not key:
        return None
    unit = _ALIASES.get(key)
    if unit is None:
        unit = _ALIASES.get(key.translate(_HOMOGLYPHS))
    if unit is not None and unit.kind == "percent_points":
        # Alias keys are dot-free, so bare «пп» would collide with «п.п.».
        # Dotless «пп» in this corpus is OCR debris («гру пп ы суммации»)
        # or a row-number header («NI ПП») — require the dotted or the
        # spelled-out form on the RAW text.
        low = text.casefold()
        if "." not in text and "пункт" not in low and "point" not in low:
            return None
    return unit


def dimension_key(unit: UnitDef) -> str:
    """Stable dimension identity: rates carry their time basis."""
    if unit.time_basis is None:
        return unit.kind
    return f"{unit.kind}/{unit.time_basis}"


def canonical_unit_for(unit: UnitDef) -> str:
    return CANONICAL_UNITS[(unit.kind, unit.time_basis)]


def convert_to_canonical(value: Decimal, unit: UnitDef) -> Decimal:
    """Exact conversion to the dimension's canonical unit."""
    return value * unit.factor


def convertible(a: UnitDef, b: UnitDef) -> bool:
    """True when two units live in the same dimension AND time basis."""
    return a.kind == b.kind and a.time_basis == b.time_basis


def registry_snapshot() -> dict[str, object]:
    """Deterministic serializable dump of the declared registry."""
    aliases = {
        key: {
            "canonical": unit.canonical,
            "dimension": dimension_key(unit),
            "factor": str(unit.factor),
        }
        for key, unit in sorted(_ALIASES.items())
    }
    return {
        "alias_count": len(aliases),
        "aliases": aliases,
        "canonical_units": {
            f"{kind}/{basis}" if basis else kind: name
            for (kind, basis), name in sorted(
                CANONICAL_UNITS.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
            )
        },
    }
