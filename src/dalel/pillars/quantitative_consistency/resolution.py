"""Conservative contextual resolution of ambiguous «1,234»-style numerals.

Local structural or mathematical evidence only — never a global plausibility
guess:

- **table-local decimal style**: compatible cells in one table establish a
  decimal-comma convention unless that table positively demonstrates comma
  thousands grouping;
- **aggregation equality**: if reading every ambiguous cell of a column as a
  decimal makes the column's total check EXACTLY consistent, that reading is
  structurally proven;
- **formula equality**: «0,66 * 2000 * 3600 / 1000000 = 4,752» — the
  left-hand chain evaluates exactly to the decimal reading;
- **engineering magnitude**: a length-dimension value with explicit
  construction vocabulary («на высоте», «отметка», «диаметром») where the
  decimal reading is a plausible building dimension and the thousands
  reading is ≥ 1000 m;
- **twin propagation**: once a (document, raw token) pair is resolved by any
  pass, its other occurrences in the same document resolve identically;
- **spatial sequences**: descending «от 5,500 до 5,150 м» roof elevations
  are an engineering sequence, not an inverted numeric range.

Unresolved tokens keep the ambiguity flag, stay excluded from comparisons
and sums, and surface as info review cues.
"""

from __future__ import annotations

import re
from decimal import Decimal

from dalel.pillars.quantitative_consistency.aggregations import _segments_for_column
from dalel.pillars.quantitative_consistency.extractor import (
    ExtractionResult,
    TableSheet,
    _mention_confidence,
)
from dalel.pillars.quantitative_consistency.number_parser import decimal_str
from dalel.pillars.quantitative_consistency.schemas import QuantMention
from dalel.pillars.quantitative_consistency.units import (
    canonical_unit_for,
    convert_to_canonical,
    lookup_unit,
)

_ELEVATION_VOCAB_RE = re.compile(
    r"высот|отметк|диаметр|уклон|глубин|ширин|толщин|пролет|шаг|сечени",
)

# Left-hand arithmetic chain before «= <token>»: numbers joined by · * × /.
_FORMULA_CHAIN_RE = re.compile(r"((?:\d+(?:[.,]\d+)?\s*[·*×/]\s*)+\d+(?:[.,]\d+)?)\s*=\s*$")
_SINGLE_COMMA_RE = re.compile(r"^[+-]?(\d+),(\d+)$")
_COMMA_GROUPING_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?$")


def _decimal_reading(raw: str) -> Decimal | None:
    token = raw.replace(" ", "")
    try:
        return Decimal(token.replace(",", "."))
    except ArithmeticError:
        return None


def _evaluate_chain(expression: str) -> Decimal | None:
    """Evaluate a strict left-to-right multiplication/division chain."""
    tokens = re.split(r"\s*([·*×/])\s*", expression.strip())
    if len(tokens) < 3:
        return None
    try:
        value = Decimal(tokens[0].replace(",", "."))
        for op, operand_raw in zip(tokens[1::2], tokens[2::2], strict=True):
            operand = Decimal(operand_raw.replace(",", "."))
            if op == "/":
                if operand == 0:
                    return None
                value = value / operand
            else:
                value = value * operand
        return value
    except ArithmeticError:
        return None


def _resolve_mention(mention: QuantMention, evidence: str) -> QuantMention:
    """Rebuild the mention with its decimal reading structurally confirmed."""
    flags = sorted(
        {f for f in mention.flags if f != "ambiguous_decimal_grouping"}
        | {"resolved_from_context", f"resolved_by:{evidence}"}
    )
    update: dict[str, object] = {
        "flags": flags,
        "extraction_confidence": _mention_confidence(flags),
    }
    unit = lookup_unit(mention.unit_canonical) if mention.unit_canonical else None
    if unit is not None and mention.value is not None:
        update["canonical_value"] = decimal_str(convert_to_canonical(Decimal(mention.value), unit))
        update["canonical_unit"] = canonical_unit_for(unit)
    return mention.model_copy(update=update)


def _ambiguous(mention: QuantMention) -> bool:
    return "ambiguous_decimal_grouping" in mention.flags


def _dimension_family(dimension: str) -> str:
    """Physical kind without the unit time basis (for local style only)."""
    return dimension.partition("/")[0]


def _try_table_decimal_comma(
    sheet: TableSheet, mentions_by_id: dict[str, QuantMention]
) -> dict[str, str]:
    """Resolve table cells from positive, compatible local style evidence.

    One compatible unambiguous decimal-comma cell in the same table is
    sufficient; same-column evidence is naturally included. A multi-group
    comma numeral in that table is positive thousands evidence and blocks
    this inference entirely.
    """
    table_mentions = [
        mention
        for mention in mentions_by_id.values()
        if mention.location.source_kind == "table_cell"
        and mention.location.table_id == sheet.table_id
    ]
    if any(_COMMA_GROUPING_RE.fullmatch(m.raw_number.replace(" ", "")) for m in table_mentions):
        return {}

    clear_decimal: list[QuantMention] = []
    for mention in table_mentions:
        match = _SINGLE_COMMA_RE.fullmatch(mention.raw_number.replace(" ", ""))
        if (
            match is not None
            and not _ambiguous(mention)
            and mention.kind == "scalar"
            and mention.dimension is not None
            and mention.unit_canonical is not None
            and "grouped_thousands" not in mention.flags
            and "thousands_from_document_style" not in mention.flags
        ):
            clear_decimal.append(mention)

    resolved: dict[str, str] = {}
    for mention in table_mentions:
        if not _ambiguous(mention) or mention.dimension is None or mention.unit_canonical is None:
            continue
        compatible = [
            m
            for m in clear_decimal
            if m.dimension is not None
            and _dimension_family(m.dimension) == _dimension_family(mention.dimension)
        ]
        if compatible:
            resolved[mention.mention_id] = "table_decimal_comma"
    return resolved


def _try_aggregation_equality(sheet: TableSheet) -> dict[str, str]:
    """mention_id -> evidence for cells proven by an exactly-consistent
    column total under the decimal reading."""
    resolved: dict[str, str] = {}
    for col_info in sheet.cols:
        col = col_info.index
        ambiguous_cells = [
            (position, cell)
            for position, cell in sheet.cells.items()
            if position[1] == col and cell.status == "ambiguous"
        ]
        if not ambiguous_cells:
            continue
        # Temporarily trust the decimal readings and replay the segments.
        for _position, cell in ambiguous_cells:
            cell.status = "single"
        try:
            segments = _segments_for_column(sheet, col)
            for segment in segments:
                stated = sheet.cells[(segment.total_row, col)]
                if stated.value is None:
                    continue
                computed = sum(
                    (c.value for c in segment.components if c.value is not None),
                    Decimal(0),
                )
                if computed != stated.value:
                    continue
                involved_rows = {c.row for c in segment.components} | {segment.total_row}
                for (row, _col), cell in ambiguous_cells:
                    if row in involved_rows and cell.mention_id:
                        resolved[cell.mention_id] = "aggregation_equality"
        finally:
            for _position, cell in ambiguous_cells:
                if cell.mention_id not in resolved:
                    cell.status = "ambiguous"
    return resolved


def resolve_ambiguities(extraction: ExtractionResult) -> int:
    """Resolve ambiguous numerals in place; returns the number resolved."""
    resolved_by_id: dict[str, str] = {}
    mentions_by_id = {mention.mention_id: mention for mention in extraction.mentions}

    # --- pass A: table-local decimal-comma convention -----------------------------
    for sheet in extraction.sheets:
        resolved_by_id.update(_try_table_decimal_comma(sheet, mentions_by_id))

    # --- pass B: aggregation equality --------------------------------------------
    for sheet in extraction.sheets:
        for mention_id, aggregation_evidence in _try_aggregation_equality(sheet).items():
            resolved_by_id.setdefault(mention_id, aggregation_evidence)

    # --- pass C: formula equality -------------------------------------------------
    for mention in extraction.mentions:
        if not _ambiguous(mention) or mention.mention_id in resolved_by_id:
            continue
        window = mention.raw_text
        position = window.rfind(mention.raw_number)
        if position <= 0:
            continue
        match = _FORMULA_CHAIN_RE.search(window[:position])
        if match is None:
            continue
        computed = _evaluate_chain(match.group(1))
        decimal_reading = _decimal_reading(mention.raw_number)
        if computed is not None and decimal_reading is not None and computed == decimal_reading:
            resolved_by_id[mention.mention_id] = "formula_equality"

    # --- pass D: engineering magnitude (length dimensions) --------------------------
    for mention in extraction.mentions:
        if not _ambiguous(mention) or mention.mention_id in resolved_by_id:
            continue
        if mention.dimension != "length":
            continue
        if not _ELEVATION_VOCAB_RE.search(mention.raw_text.casefold()):
            continue
        values = [v for v in (mention.value, mention.value_low, mention.value_high) if v]
        readings = [Decimal(v) for v in values]
        if readings and all(Decimal("0.001") <= r <= Decimal(100) for r in readings):
            # The thousands reading would be ≥ 1000 m — not a building
            # dimension; the decimal reading is structurally plausible.
            resolved_by_id[mention.mention_id] = "engineering_magnitude"

    # --- twin propagation -------------------------------------------------------------
    resolved_tokens = {
        (m.document_id, m.raw_number): resolved_by_id[m.mention_id]
        for m in extraction.mentions
        if m.mention_id in resolved_by_id
    }
    for mention in extraction.mentions:
        if not _ambiguous(mention) or mention.mention_id in resolved_by_id:
            continue
        evidence = resolved_tokens.get((mention.document_id, mention.raw_number))
        if evidence is not None:
            resolved_by_id[mention.mention_id] = f"twin:{evidence}"

    # --- apply ---------------------------------------------------------------------------
    if resolved_by_id:
        extraction.mentions = [
            (
                _resolve_mention(m, resolved_by_id[m.mention_id])
                if m.mention_id in resolved_by_id
                else m
            )
            for m in extraction.mentions
        ]
        for sheet in extraction.sheets:
            for cell in sheet.cells.values():
                if cell.status == "ambiguous" and cell.mention_id in resolved_by_id:
                    cell.status = "single"

    # --- spatial sequences: descending elevations are not numeric ranges -------------------
    updated: list[QuantMention] = []
    for mention in extraction.mentions:
        if (
            mention.kind == "range"
            and "range_inversion" in mention.flags
            and mention.dimension == "length"
            and _ELEVATION_VOCAB_RE.search(mention.raw_text.casefold())
        ):
            flags = sorted({*mention.flags, "spatial_sequence"})
            mention = mention.model_copy(update={"flags": flags})
        updated.append(mention)
    extraction.mentions = updated
    return len(resolved_by_id)
