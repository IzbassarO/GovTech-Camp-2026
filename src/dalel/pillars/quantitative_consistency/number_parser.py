"""Deterministic numeric scanning for RU/KK/EN environmental documents.

False-positive avoidance beats recall: identifier-like numbers (years, dates,
phone/BIN numbers, clause and page references, zero-padded substance codes,
source codes like ``6001-001``, coordinates, ``N · 10`` with a lost
superscript exponent) are SUPPRESSED with an explicit reason instead of being
parsed into quantities. Ambiguous formats (``1,234``) are parsed with the
document's dominant decimal style but keep an ambiguity flag; they never
participate in high-confidence comparisons.

All parsing uses ``Decimal``; binary floats never touch a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from dalel.pillars.quantitative_consistency.config import (
    MARKER_WINDOW_CHARS,
    MAX_QUANTITY_DIGITS,
    UNIT_WINDOW_CHARS,
    YEAR_MAX,
    YEAR_MIN,
)
from dalel.pillars.quantitative_consistency.normalization import normalize_for_scan
from dalel.pillars.quantitative_consistency.units import UnitDef, match_unit_after


def decimal_str(value: Decimal) -> str:
    """Canonical fixed-notation string: no exponent, no trailing zeros."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", "", "-"):
        return "0"
    return text


@dataclass(frozen=True)
class QuantitySpan:
    """One parsed quantity (scalar or range) located in normalized text."""

    start: int
    end: int
    raw: str  # verbatim numeric construct (range includes both ends)
    kind: str  # "scalar" | "range"
    modifier: str  # "none" | "approximate" | "upper_bound" | "lower_bound"
    bound_inclusive: bool | None
    value: Decimal | None  # scalar value (None for ranges)
    low: Decimal | None  # range ends
    high: Decimal | None
    display_quantum: Decimal  # 10^-decimals of the displayed value
    unit_raw: str | None
    unit: UnitDef | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class SuppressedNumber:
    start: int
    raw: str
    reason: str


@dataclass
class ScanResult:
    """Scan output; offsets refer to ``text`` (the normalized input)."""

    text: str
    spans: list[QuantitySpan] = field(default_factory=list)
    suppressed: list[SuppressedNumber] = field(default_factory=list)


# --- token grammar -------------------------------------------------------------
_TOKEN_RE = re.compile(
    r"""
    (?<![\w.,])
    (?:
        \d{1,3}(?:\.\d{3}){2,}(?:,\d+)?      # dot-grouped thousands: 1.234.567[,89]
      | \d{1,3}(?:,\d{3}){2,}(?:\.\d+)?      # comma-grouped thousands: 1,234,567[.89]
      | \d{1,3}(?:\ \d{3})+(?:[.,]\d+)?      # space-grouped thousands: 35 680[,5]
      | \d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?     # plain / decimal / E-notation
      | [.,]\d+                              # leading-separator decimals: .5  ,5
    )
    (?![\d])
    """,
    re.VERBOSE,
)

# N · 10^k with an explicit exponent (recoverable scientific notation),
# and bare powers «10^k» (folded from Unicode «10⁵» / «10⁻⁵»). The mantissa
# group is optional: a bare power is one numeric expression, never the two
# separate quantities 10 and k.
_SCI_POWER_RE = re.compile(r"(?<![\w.,])(?:(\d+(?:[.,]\d+)?)\s*[·*×]\s*)?10\^(-?\d+)(?![\d])")

# Damaged scientific notation: a coefficient (numeric, or a 1-3 letter
# variable placeholder like «N», «G», «КПД») multiplied by ten whose
# exponent was lost by extraction. The zone consumes the WHOLE expression
# so «10» can never be rescanned as a standalone quantity.
_LOST_POWER_RE = re.compile(
    r"(?:(?<![\w.,])\d+(?:[.,]\d+)?|(?<![\w])[A-Za-zА-Яа-яЁё]{1,3})"
    r"\s*[·*×]\s*10(?![\d^])"
)

_DATE_RE = re.compile(r"(?<!\d)\d{1,2}\.\d{1,2}\.\d{2,4}(?!\d)")
_MULTIDOT_RE = re.compile(r"(?<![\d.,])\d+(?:\.\d+){2,}(?![\d.])")
_ID_SEQUENCE_RE = re.compile(r"(?<![\w])\+?\d[\d ()\-]{9,}\d(?![\d])")
_COORD_RE = re.compile(r"\d{1,3}\s*°\s*\d{1,2}\s*[\'′](?:\s*\d{1,2}(?:[.,]\d+)?\s*(?:\"|″|\'\'))?")
_COORD_CONTEXT_RE = re.compile(r"\d+[.,]?\d*\s*°?\s*(?:с\.?ш\.?|в\.?д\.?|сш|вд)\b", re.IGNORECASE)

_MONTHS = (
    "январ|феврал|март|апрел|ма[яйе]|июн|июл|август|сентябр|октябр|ноябр|декабр"
    "|қаңтар|ақпан|наурыз|сәуір|мамыр|маусым|шілде|тамыз|қыркүйек|қазан|қараша|желтоқсан"
    "|january|february|march|april|may|june|july|august|september|october|november|december"
)
_DAY_MONTH_RE = re.compile(rf"(?<!\d)(\d{{1,2}})\s+(?:{_MONTHS})", re.IGNORECASE)

# Clause/page/document references. Word boundaries protect against suffixes
# («вес.» must not trigger «с.»).
# NB: NFKC folds «№» into «No», so the normalized text carries «no 123».
_REF_PREFIX_RE = re.compile(
    r"(?<![\w])(?:№|no|n°|стр\.|с\.|лист[аеы]?|раздел[аеу]?|глав[аеы]|пункт[аеу]?[мв]?|п\.|пп\."
    r"|ст\.|статья|статьи|статье|приложени[еяию][мх]?|табл\.|таблиц[аыеу]|рис\.|рисун[оке][кв]?"
    r"|гост|снип|санпин|ст\s+рк|бин|иин|тел\.?|телефон|факс)"
    r"\s*№?\s*(?=[\d])",
    re.IGNORECASE,
)
_REF_NUMBER_RE = re.compile(r"[\d.\-/]+")

# «К=0,2», «V = 600» — a 1-2 letter variable assigned in a calculation
# formula is not a document claim; comparing such numbers is noise.
_FORMULA_VAR_RE = re.compile(r"(?<![\w])[A-Za-zА-Яа-я]{1,2}\s*=\s*(?=[-+]?[\d.,])")

# Equipment/material model ratios: an ALL-CAPS designation followed by a
# small digits/digits pair («УОНИ 13/55», «АНО 4/6») names a product model,
# not two quantities and not a range.
_MODEL_RATIO_RE = re.compile(r"(?<![\w])[A-ZА-ЯЁ]{2,}[\w\-]*[\s\-]?(\d{1,4}\s?/\s?\d{1,4})(?![\d])")

_YEAR_WORD_AFTER_RE = re.compile(r"^\s*(?:год[уаы]?[вх]?|гг\.?|г\.|жыл[ыда]?[нң]?|years?)(?![\w])")
_YEAR_WORD_BEFORE_RE = re.compile(r"(?:в|с|по|на|до|за)\s+$", re.IGNORECASE)

_RANGE_FROM_RE = re.compile(r"(?:от|from)\s*$", re.IGNORECASE)
_RANGE_TO_BETWEEN_RE = re.compile(r"^\s*(?:до|to)\s*$", re.IGNORECASE)
# A dash is a RANGE separator only when its spacing is symmetric: attached
# on both sides («10-12») or spaced on both sides («10 - 12»). Asymmetric
# spacing («МР -3 -2,0», «топлива -0,14») is the key-value/bullet idiom.
_DASH_BETWEEN_RE = re.compile(r"^(?:[-–—]|\s+[-–—]\s+)$")

# Bound markers scanned in the window BEFORE a number (nearest match wins).
_BOUND_MARKERS_BEFORE: tuple[tuple[str, str, bool], ...] = (
    ("не более чем", "upper_bound", True),
    ("не более", "upper_bound", True),
    ("не выше", "upper_bound", True),
    ("не превышает", "upper_bound", True),
    ("не должен превышать", "upper_bound", True),
    ("не менее чем", "lower_bound", True),
    ("не менее", "lower_bound", True),
    ("не ниже", "lower_bound", True),
    ("кемінде", "lower_bound", True),
    ("at most", "upper_bound", True),
    ("at least", "lower_bound", True),
    ("менее", "upper_bound", False),
    ("более", "lower_bound", False),
    ("свыше", "lower_bound", False),
    ("выше", "lower_bound", False),
    ("до", "upper_bound", True),
    ("<=", "upper_bound", True),
    (">=", "lower_bound", True),
    ("≤", "upper_bound", True),
    ("≥", "lower_bound", True),
    ("<", "upper_bound", False),
    (">", "lower_bound", False),
)
# Kazakh verb-final upper bounds follow the unit: «10 т аспайды».
_BOUND_AFTER_RE = re.compile(r"(?<![\w])(?:аспайды|аспауы\s+тиіс)(?![\w])")

_APPROX_MARKERS = (
    "около",
    "примерно",
    "приблизительно",
    "порядка",
    "шамамен",
    "about",
    "approximately",
    "roughly",
    "~",
    "≈",
)

_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


@dataclass(frozen=True)
class _RawToken:
    start: int
    end: int
    raw: str


def _build_zones(text: str) -> list[tuple[int, int, str]]:
    zones: list[tuple[int, int, str]] = []
    for match in _DATE_RE.finditer(text):
        zones.append((match.start(), match.end(), "date"))
    for match in _MULTIDOT_RE.finditer(text):
        groups = match.group(0).split(".")
        if not all(len(g) == 3 for g in groups[1:]):
            zones.append((match.start(), match.end(), "structural_numbering"))
    for match in _ID_SEQUENCE_RE.finditer(text):
        if sum(ch.isdigit() for ch in match.group(0)) >= 10:
            zones.append((match.start(), match.end(), "identifier_sequence"))
    for match in _COORD_RE.finditer(text):
        zones.append((match.start(), match.end(), "coordinate"))
    for match in _COORD_CONTEXT_RE.finditer(text):
        zones.append((match.start(), match.end(), "coordinate"))
    for match in _DAY_MONTH_RE.finditer(text):
        zones.append((match.start(1), match.end(1), "date"))
    for match in _REF_PREFIX_RE.finditer(text):
        number = _REF_NUMBER_RE.match(text, match.end())
        if number:
            zones.append((number.start(), number.end(), "reference_identifier"))
    for match in _FORMULA_VAR_RE.finditer(text):
        number = _TOKEN_RE.match(text, match.end())
        if number:
            zones.append((number.start(), number.end(), "formula_variable"))
    for match in _MODEL_RATIO_RE.finditer(text):
        zones.append((match.start(1), match.end(1), "equipment_identifier"))
    for match in _LOST_POWER_RE.finditer(text):
        zones.append((match.start(), match.end(), "missing_scientific_exponent"))
    return zones


def _in_zone(zones: list[tuple[int, int, str]], start: int, end: int) -> str | None:
    for zone_start, zone_end, reason in zones:
        if start < zone_end and end > zone_start:
            return reason
    return None


def _parse_numeral(
    raw: str,
    doc_style: str | None,
    grouping_styles: frozenset[str] = frozenset(),
) -> tuple[Decimal, Decimal, list[str]]:
    """Parse one numeric token -> (value, display_quantum, flags)."""
    flags: list[str] = []
    token = raw
    exponent = 0
    exp_match = re.search(r"[eE]([-+]?\d+)$", token)
    if exp_match:
        exponent = int(exp_match.group(1))
        token = token[: exp_match.start()]

    if re.fullmatch(r"\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?", token):
        int_part, _, frac = token.partition(",")
        int_part = int_part.replace(".", "")
        flags.append("grouped_thousands")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?", token):
        int_part, _, frac = token.partition(".")
        int_part = int_part.replace(",", "")
        flags.append("grouped_thousands")
    elif " " in token:
        compact = token.replace(" ", "")
        sep = "," if "," in compact else ("." if "." in compact else "")
        if sep:
            int_part, _, frac = compact.partition(sep)
        else:
            int_part, frac = compact, ""
        flags.append("grouped_thousands")
    else:
        seps = [ch for ch in token if ch in ",."]
        if not seps:
            int_part, frac = token, ""
        else:
            sep = seps[0]
            int_part, _, frac = token.partition(sep)
            if not int_part:
                int_part = "0"
                flags.append("leading_separator")
            if sep == ",":
                flags.append("decimal_comma")
            # «1,234» / «1.234»: one separator + exactly three fractional
            # digits is ambiguous between decimal and thousands grouping.
            # Context resolution: the separator matching the document's
            # decimal style reads as a decimal; a thousands reading requires
            # POSITIVE grouping evidence (the document demonstrably groups
            # thousands with this separator, e.g. «1,234,567») — style alone
            # is not enough because this corpus mixes decimal conventions
            # WITHIN documents. Anything else stays ambiguous and is excluded
            # from strong comparisons downstream.
            if len(frac) == 3 and int_part != "0" and exponent == 0:
                style = "comma" if sep == "," else "dot"
                if doc_style == style:
                    pass  # separator matches the document's decimal style
                elif doc_style is not None and style in grouping_styles:
                    # Opposite decimal style AND proven grouping usage:
                    # the separator is a thousands mark.
                    int_part, frac = int_part + frac, ""
                    flags.append("thousands_from_document_style")
                else:
                    flags.append("ambiguous_decimal_grouping")

    value = Decimal(f"{int_part}.{frac}" if frac else int_part)
    if exponent:
        value = value.scaleb(exponent)
    quantum = Decimal(1).scaleb(exponent - len(frac))
    return value, quantum, flags


def _find_modifier(text: str, start: int) -> tuple[str, bool | None, bool]:
    """(modifier, bound_inclusive, is_approx) from the window before ``start``."""
    window = text[max(0, start - MARKER_WINDOW_CHARS) : start].casefold()
    stripped = window.rstrip()
    for marker in _APPROX_MARKERS:
        if stripped.endswith(marker):
            return "approximate", None, True
    for marker, modifier, inclusive in _BOUND_MARKERS_BEFORE:
        if stripped.endswith(marker):
            if marker == "до" and _RANGE_FROM_RE.search(stripped[: -len(marker)].rstrip()):
                # «от X до Y» is handled by range pairing, not as a bound.
                return "none", None, False
            return modifier, inclusive, False
    return "none", None, False


# Characters that positively open a signed value («температура: -7,2»,
# «= -0,3», «(-5»). Anything else before a dash — letters, digits, closing
# parentheses, line starts — reads as a key-value separator, bullet, range
# or identifier dash in this corpus, never as a minus sign.
_SIGN_OPENERS = "(=<>≤≥:"


def _is_negative(text: str, start: int) -> bool:
    if start == 0 or text[start - 1] != "-":
        return False
    before = text[: start - 1].rstrip()
    if not before:
        return False  # document/line-leading dash: bullet, not a sign
    if before.endswith("\n"):
        return False
    return before[-1] in _SIGN_OPENERS


def _year_like(value: Decimal, quantum: Decimal) -> bool:
    # abs(): a leading dash before a year is enumeration/range debris,
    # never a negative-year quantity.
    return (
        quantum == 1
        and value == value.to_integral_value()
        and YEAR_MIN <= abs(int(value)) <= YEAR_MAX
    )


def scan_text(
    raw_text: str,
    doc_style: str | None = None,
    grouping_styles: frozenset[str] = frozenset(),
) -> ScanResult:
    """Scan a text block; returns quantity spans + suppression diagnostics.

    ``doc_style`` is the document's dominant decimal separator ("comma" /
    "dot" / None) used only to resolve «1,234»-style ambiguity flags.
    """
    text = normalize_for_scan(raw_text)
    result = ScanResult(text=text)
    zones = _build_zones(text)
    consumed: set[int] = set()  # token start offsets already used

    sci_spans: list[tuple[int, int, Decimal, Decimal, str]] = []
    for match in _SCI_POWER_RE.finditer(text):
        if _in_zone(zones, match.start(), match.end()):
            continue
        mantissa_raw = (match.group(1) or "1").replace(",", ".")
        exponent = int(match.group(2))
        frac_len = len(mantissa_raw.partition(".")[2])
        value = Decimal(mantissa_raw).scaleb(exponent)
        quantum = Decimal(1).scaleb(exponent - frac_len)
        sci_spans.append((match.start(), match.end(), value, quantum, match.group(0)))

    tokens = [
        _RawToken(m.start(), m.end(), m.group(0))
        for m in _TOKEN_RE.finditer(text)
        if not any(s <= m.start() < e for s, e, *_ in sci_spans)
    ]

    def _suppress(token: _RawToken, reason: str) -> None:
        result.suppressed.append(SuppressedNumber(start=token.start, raw=token.raw, reason=reason))

    def _emit(
        start: int,
        end: int,
        raw: str,
        kind: str,
        modifier: str,
        inclusive: bool | None,
        value: Decimal | None,
        low: Decimal | None,
        high: Decimal | None,
        quantum: Decimal,
        flags: list[str],
    ) -> None:
        unit_match = match_unit_after(text, end, UNIT_WINDOW_CHARS)
        unit = unit_match.unit if unit_match else None
        unit_raw = unit_match.raw if unit_match else None

        scalar = value if kind == "scalar" else None
        if scalar is not None and _year_like(scalar, quantum) and modifier == "none":
            after = text[end : end + 12]
            before = text[max(0, start - 8) : start]
            if unit is None:
                reason = (
                    "year_word"
                    if _YEAR_WORD_AFTER_RE.match(after) or _YEAR_WORD_BEFORE_RE.search(before)
                    else "bare_year_like"
                )
                _suppress(_RawToken(start, end, raw), reason)
                return
            if unit.canonical == "г":
                # «2025 г.» — the Russian year abbreviation collides with
                # grams; a year-like integer with «г» is always a year here.
                _suppress(_RawToken(start, end, raw), "year_abbreviation_gram_collision")
                return

        result.spans.append(
            QuantitySpan(
                start=start,
                end=end,
                raw=raw,
                kind=kind,
                modifier=modifier,
                bound_inclusive=inclusive,
                value=value if kind == "scalar" else None,
                low=low,
                high=high,
                display_quantum=quantum,
                unit_raw=unit_raw,
                unit=unit,
                flags=tuple(flags),
            )
        )

    for start, end, value, quantum, raw in sci_spans:
        modifier, inclusive, approx = _find_modifier(text, start)
        flags = ["power_notation"]
        if approx:
            flags.append("approximate")
        _emit(start, end, raw, "scalar", modifier, inclusive, value, None, None, quantum, flags)

    for index, token in enumerate(tokens):
        if token.start in consumed:
            continue
        zone_reason = _in_zone(zones, token.start, token.end)
        if zone_reason:
            _suppress(token, zone_reason)
            continue
        # Digit count alone marks identifiers only for INTEGER-shaped tokens
        # (BIN/IIN, account numbers). A long decimal with a separator is a
        # high-precision quantity («23,929263576 т/год») and must keep its
        # exact value; stronger identifier evidence (zones) already ran.
        integer_shaped = "," not in token.raw and "." not in token.raw
        if integer_shaped and sum(ch.isdigit() for ch in token.raw) > MAX_QUANTITY_DIGITS:
            _suppress(token, "identifier_sequence")
            continue
        if re.fullmatch(r"0\d+", token.raw):
            _suppress(token, "zero_padded_code")
            continue
        if token.start >= 1 and text[token.start - 1] == "-" and token.start >= 2:
            prev = text[token.start - 2]
            if _LETTER_RE.match(prev):
                _suppress(token, "model_identifier")
                continue

        # ---- range pairing with the next token -------------------------------
        partner: _RawToken | None = None
        range_style: str | None = None
        if index + 1 < len(tokens):
            nxt = tokens[index + 1]
            between = text[token.end : nxt.start]
            if _RANGE_TO_BETWEEN_RE.match(between) and _RANGE_FROM_RE.search(
                text[max(0, token.start - MARKER_WINDOW_CHARS) : token.start]
            ):
                partner, range_style = nxt, "from_to"
            elif _DASH_BETWEEN_RE.match(between):
                partner, range_style = nxt, "dash"

        modifier, inclusive, approx = _find_modifier(text, token.start)

        if partner is not None and _in_zone(zones, partner.start, partner.end) is None:
            low_value, low_quantum, low_flags = _parse_numeral(
                token.raw, doc_style, grouping_styles
            )
            if re.fullmatch(r"0\d+", partner.raw):
                # «6001-001»-style source codes: suppress the whole construct.
                _suppress(
                    _RawToken(token.start, partner.end, f"{token.raw}-{partner.raw}"),
                    "source_code_pair",
                )
                consumed.add(partner.start)
                continue
            high_value, high_quantum, high_flags = _parse_numeral(
                partner.raw, doc_style, grouping_styles
            )
            both_year_like = _year_like(low_value, low_quantum) and _year_like(
                high_value, high_quantum
            )
            raw_construct = text[token.start : partner.end]
            if both_year_like:
                _suppress(_RawToken(token.start, partner.end, raw_construct), "year_range")
                consumed.add(partner.start)
                continue
            dash_char = (
                "-" in text[token.end : partner.start]
                and "–" not in text[token.end : partner.start]
                and "—" not in text[token.end : partner.start]
            )
            has_decimals = low_quantum < 1 or high_quantum < 1
            unit_probe = match_unit_after(text, partner.end, UNIT_WINDOW_CHARS)
            if range_style == "dash" and dash_char and not (has_decimals or unit_probe):
                # Bare «A-B» integers without units or decimals: source codes
                # («6701-703») more often than ranges in this corpus, and even
                # genuine ranges are useless without a unit. Suppress whole.
                _suppress(
                    _RawToken(token.start, partner.end, raw_construct),
                    "unitless_dash_pair",
                )
                consumed.add(partner.start)
                continue
            if low_value > high_value:
                if range_style == "dash" and dash_char and not has_decimals:
                    _suppress(
                        _RawToken(token.start, partner.end, raw_construct), "suspected_code_pair"
                    )
                    consumed.add(partner.start)
                    continue
                flags = sorted({*low_flags, *high_flags, "range_inversion"})
                consumed.add(partner.start)
                quantum = min(low_quantum, high_quantum)
                _emit(
                    token.start,
                    partner.end,
                    raw_construct,
                    "range",
                    modifier,
                    inclusive,
                    None,
                    low_value,
                    high_value,
                    quantum,
                    list(flags),
                )
                continue
            else:
                flags = sorted({*low_flags, *high_flags})
                if approx:
                    flags = sorted({*flags, "approximate"})
                consumed.add(partner.start)
                quantum = min(low_quantum, high_quantum)
                _emit(
                    token.start,
                    partner.end,
                    raw_construct,
                    "range",
                    "none",
                    None,
                    None,
                    low_value,
                    high_value,
                    quantum,
                    list(flags),
                )
                continue

        # ---- scalar ------------------------------------------------------------
        value, quantum, flags = _parse_numeral(token.raw, doc_style, grouping_styles)
        negative = _is_negative(text, token.start)
        start = token.start - 1 if negative else token.start
        raw = ("-" + token.raw) if negative else token.raw
        if negative:
            value = -value
        if approx:
            flags = sorted({*flags, "approximate"})
        if modifier == "none" and _BOUND_AFTER_RE.search(
            text[token.end : token.end + MARKER_WINDOW_CHARS].casefold()
        ):
            modifier, inclusive = "upper_bound", True
        _emit(
            start,
            token.end,
            raw,
            "scalar",
            modifier,
            inclusive,
            value,
            None,
            None,
            quantum,
            list(flags),
        )

    result.spans.sort(key=lambda span: span.start)
    result.suppressed.sort(key=lambda item: item.start)
    return result


def thousands_grouping_styles(raw_text: str) -> frozenset[str]:
    """Separators the document PROVABLY uses for thousands grouping
    (multi-group tokens like «1,234,567» / «1.234.567»)."""
    text = normalize_for_scan(raw_text)
    styles = set()
    if re.search(r"(?<![\d.,])\d{1,3}(?:,\d{3}){2,}(?![\d,])", text):
        styles.add("comma")
    if re.search(r"(?<![\d.,])\d{1,3}(?:\.\d{3}){2,}(?![\d.])", text):
        styles.add("dot")
    return frozenset(styles)


def unambiguous_decimal_style(raw_text: str) -> str | None:
    """Dominant decimal separator from UNAMBIGUOUS tokens only.

    Used per document to resolve «1,234»-style tokens; ties -> None.
    """
    text = normalize_for_scan(raw_text)
    comma = 0
    dot = 0
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0)
        if re.search(r"[eE][-+]?\d+$", token):
            token = token[: re.search(r"[eE][-+]?\d+$", token).start()]  # type: ignore[union-attr]
        seps = [ch for ch in token if ch in ",."]
        if len(seps) != 1:
            continue
        int_part, _, frac = token.partition(seps[0])
        if len(frac) == 3 and int_part not in ("", "0"):
            continue  # ambiguous — never votes
        if seps[0] == ",":
            comma += 1
        else:
            dot += 1
    if comma > dot:
        return "comma"
    if dot > comma:
        return "dot"
    return None
