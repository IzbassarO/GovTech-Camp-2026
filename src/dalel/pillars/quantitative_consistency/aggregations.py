"""Table-structure checks: totals (rule C), percent columns (rule D),
and same-row limit-vs-actual bounds (rule F, structural variant).

Aggregation relationships are identified ONLY from explicit structure:
a total row («Итого:», «Всего по …») closes the segment of component rows
above it (or, for «Всего: X, в том числе: …» layouts, below it — recorded
with a direction flag and a confidence penalty). Subset rows («в том
числе», «из них») and divider rows (merged full-width spans) never enter a
sum. Columns whose header marks them as codes/classes/concentrations are
never summed. Segments containing unparseable or multi-number cells are
reported as incomplete evidence (suppressed diagnostics), not as
contradictions.

Merged duplicated columns (identical header + identical values) produce one
finding: duplicates are collapsed by a (stated, computed, count) signature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from dalel.pillars.quantitative_consistency.config import (
    AGGREGATE_MIN_COMPONENTS,
    AGGREGATE_REL_TOLERANCE,
    PERCENT_ABS_TOLERANCE_PP,
    PERCENT_TOTAL_100_WINDOW,
)
from dalel.pillars.quantitative_consistency.extractor import CellParse, ColInfo, TableSheet
from dalel.pillars.quantitative_consistency.normalization import normalize_label
from dalel.pillars.quantitative_consistency.number_parser import decimal_str
from dalel.pillars.quantitative_consistency.schemas import (
    AggregationComponent,
    AggregationDetail,
    ComparisonDetail,
    ConversionDetail,
    P3AggregationCheck,
    P3Evidence,
    P3FindingRecord,
    QuantMention,
    deterministic_id,
)
from dalel.pillars.quantitative_consistency.scoring import (
    cap_severity,
    finding_confidence,
    points_for,
    severity_for_conflict,
)
from dalel.pillars.quantitative_consistency.semantic_context import extract_qualifiers
from dalel.pillars.quantitative_consistency.units import (
    UnitDef,
    canonical_unit_for,
    convert_to_canonical,
    dimension_key,
)

_REVIEW_NOTE = (
    "Это ПОТЕНЦИАЛЬНОЕ несоответствие, требующее проверки экспертом;"
    " вывод о нарушении или недостоверности документа не делается."
)

_MAX_PERCENT_FINDINGS_PER_TABLE = 5


@dataclass
class _ComponentDecision:
    """One examined row with its explicit inclusion/exclusion decision."""

    row: int
    label: str | None
    included: bool
    reason: str
    value: Decimal | None = None
    quantum: Decimal | None = None
    mention_id: str | None = None
    overlaps_row: int | None = None


@dataclass
class _Segment:
    total_row: int
    decisions: list[_ComponentDecision]
    direction: str  # "above" | "below" | "subtotals"
    incomplete: bool
    overlap_resolved: bool = False

    @property
    def components(self) -> list[_ComponentDecision]:
        return [d for d in self.decisions if d.included]


@dataclass
class AggregationOutcome:
    findings: list[P3FindingRecord]
    checks: list[P3AggregationCheck] = field(default_factory=list)
    checks_total: int = 0
    checks_consistent: int = 0
    suppressed_counts: dict[str, int] | None = None


def _examine_above(
    sheet: TableSheet, col: int, row_indices: range, consumed: set[int]
) -> tuple[list[_ComponentDecision], bool]:
    """Detail rows ABOVE a total. Hierarchy comes ONLY from structural or
    textual evidence:

    - subset rows («в том числе …») after a component row open a nested
      enumeration attached to that component — excluded from this level;
    - category headers (label without values) structure the table and end
      nested spans;
    - rows already consumed as another total's children are excluded;
    - numerical equality between rows is NEVER hierarchy evidence
      (coincidental A = B + C keeps all rows as components).
    """
    decisions: list[_ComponentDecision] = []
    incomplete = False
    in_nested_span = False
    for r in row_indices:
        info = sheet.rows[r]
        if r in consumed:
            decisions.append(_ComponentDecision(r, info.label, False, "child_of_subtotal"))
            continue
        if info.is_divider:
            in_nested_span = False
            continue
        if info.is_total:
            in_nested_span = False
            continue
        if info.is_category:
            in_nested_span = False
            decisions.append(_ComponentDecision(r, info.label, False, "category_header"))
            continue
        cell = sheet.cells.get((r, col))
        has_value = cell is not None and cell.status not in ("empty",)
        if info.is_subset:
            if has_value:
                # «в том числе: опасные — 2» with its own value annotates the
                # PRECEDING component; it excludes only itself.
                decisions.append(
                    _ComponentDecision(
                        r,
                        info.label,
                        False,
                        "subset_enumeration",
                        value=cell.value if cell else None,
                    )
                )
                continue
            in_nested_span = True  # marker row opens an enumeration span
        if in_nested_span:
            if has_value:
                decisions.append(
                    _ComponentDecision(
                        r,
                        info.label,
                        False,
                        "subset_enumeration",
                        value=cell.value if cell else None,
                    )
                )
            continue
        if cell is None or cell.status == "empty":
            continue
        if cell.status in ("multi", "text", "ambiguous"):
            incomplete = True
            decisions.append(_ComponentDecision(r, info.label, False, "unparseable"))
            continue
        if info.label is None:
            # Valued rows WITHOUT an entity label are breakdown/continuation
            # artifacts (height gradations, OCR-merged rows).
            incomplete = True
            decisions.append(_ComponentDecision(r, info.label, False, "unlabeled"))
            continue
        decisions.append(
            _ComponentDecision(
                r,
                info.label,
                True,
                "component",
                value=cell.value,
                quantum=cell.quantum,
                mention_id=cell.mention_id,
            )
        )
    return decisions, incomplete


def _collect_below(
    sheet: TableSheet, col: int, total_row: int
) -> tuple[list[_ComponentDecision], bool, bool, list[int]]:
    """Children BELOW a total: «Всего: X» followed by its breakdown.

    Rows introduced by «в том числе»/«из них» DIRECTLY under the total are
    the total's own children (components); a subset marker appearing after
    a plain child opens a NESTED enumeration of that child (excluded).
    Returns (decisions, incomplete, saw_subset_marker, consumed_rows)."""
    decisions: list[_ComponentDecision] = []
    incomplete = False
    saw_marker = False
    consumed: list[int] = []
    in_nested_span = False
    plain_children = 0
    for r in range(total_row + 1, len(sheet.rows)):
        info = sheet.rows[r]
        if info.is_divider or info.is_total or info.is_category:
            break
        cell = sheet.cells.get((r, col))
        has_value = cell is not None and cell.status not in ("empty",)
        if info.is_subset:
            if plain_children and not saw_marker:
                if has_value:
                    # self-contained annotation of the previous plain child
                    consumed.append(r)
                    decisions.append(
                        _ComponentDecision(
                            r,
                            info.label,
                            False,
                            "subset_enumeration",
                            value=cell.value if cell else None,
                        )
                    )
                    continue
                in_nested_span = True  # marker row: nested enumeration
            else:
                saw_marker = True
                in_nested_span = False
            if not has_value:
                consumed.append(r)
                continue
        if in_nested_span:
            consumed.append(r)
            if has_value:
                decisions.append(
                    _ComponentDecision(
                        r,
                        info.label,
                        False,
                        "subset_enumeration",
                        value=cell.value if cell else None,
                    )
                )
            continue
        if cell is None or cell.status == "empty":
            consumed.append(r)
            continue
        if cell.status in ("multi", "text", "ambiguous"):
            incomplete = True
            consumed.append(r)
            decisions.append(_ComponentDecision(r, info.label, False, "unparseable"))
            continue
        if info.label is None:
            incomplete = True
            consumed.append(r)
            decisions.append(_ComponentDecision(r, info.label, False, "unlabeled"))
            continue
        plain_children += 1
        consumed.append(r)
        decisions.append(
            _ComponentDecision(
                r,
                info.label,
                True,
                "component",
                value=cell.value,
                quantum=cell.quantum,
                mention_id=cell.mention_id,
            )
        )
    return decisions, incomplete, saw_marker, consumed


def _segments_for_column(sheet: TableSheet, col: int) -> list[_Segment]:
    """Explicit aggregation segments for one column, built from STRUCTURAL
    hierarchy evidence only (labels, «в том числе», category rows, position
    relative to totals). Numerical equality never creates hierarchy."""
    segments: list[_Segment] = []
    boundary = sheet.header_rows  # start of the current segment
    total_rows_seen: list[int] = []
    consumed_children: set[int] = set()
    established_totals: set[int] = set()
    independents: list[int] = []  # component rows since divider, not consumed
    body_rows = [r for r in sheet.rows if r.index >= sheet.header_rows]

    for row_info in body_rows:
        row_idx = row_info.index
        if row_info.is_divider:
            boundary = row_idx + 1
            total_rows_seen = []  # subtotal chains never cross divider blocks
            independents = []
            continue
        if not row_info.is_total:
            if row_idx not in consumed_children:
                cell = sheet.cells.get((row_idx, col))
                if (
                    cell is not None
                    and cell.status == "single"
                    and row_info.label is not None
                    and not row_info.is_subset
                    and not row_info.is_category
                ):
                    independents.append(row_idx)
            continue
        cell = sheet.cells.get((row_idx, col))
        if cell is None or cell.status != "single":
            boundary = row_idx + 1
            total_rows_seen.append(row_idx)
            continue
        decisions, incomplete = _examine_above(
            sheet, col, range(boundary, row_idx), consumed_children
        )
        segment = _Segment(row_idx, decisions, "above", incomplete)
        if len(segment.components) >= AGGREGATE_MIN_COMPONENTS:
            segments.append(segment)
            consumed_children.update(c.row for c in segment.components)
            independents = [r for r in independents if r not in consumed_children]
            established_totals.add(row_idx)
        else:
            below_decisions, incomplete_below, saw_marker, consumed = _collect_below(
                sheet, col, row_idx
            )
            below = _Segment(
                row_idx,
                below_decisions,
                "including" if saw_marker else "below",
                incomplete_below,
            )
            if len(below.components) >= AGGREGATE_MIN_COMPONENTS or (
                len(below.components) >= 1 and saw_marker
            ):
                if incomplete_below and len(below.components) < AGGREGATE_MIN_COMPONENTS:
                    pass  # incomplete child group: diagnostic only (caller)
                segments.append(below)
                consumed_children.update(consumed)
                established_totals.add(row_idx)
            else:
                # Chains of stated subtotals. Hierarchy safety rules:
                # - a MIXED chain (independents + subtotals) is valid only
                #   when every participating subtotal has an ESTABLISHED
                #   children set (its own segment ran) — an unestablished
                #   subtotal may silently cover the "independent" rows and
                #   the chain would double count;
                # - a same-level subtotal chain requires IDENTICAL full
                #   normalized labels: «Всего по загрязняющему веществу» and
                #   «Всего по объекту» share a first word but are different
                #   hierarchy levels.
                subtotal_rows = [
                    r
                    for r in total_rows_seen
                    if (c := sheet.cells.get((r, col))) is not None and c.status == "single"
                ]
                available = [r for r in independents if r not in consumed_children]
                chain: list[_ComponentDecision] = []
                direction = None
                if (
                    available
                    and subtotal_rows
                    and all(r in established_totals for r in subtotal_rows)
                ):
                    direction = "mixed_chain"
                    chain_rows = sorted([*available, *subtotal_rows])
                    for r in chain_rows:
                        chain_cell = _cell(sheet, r, col)
                        chain.append(
                            _ComponentDecision(
                                r,
                                sheet.rows[r].label,
                                True,
                                "stated_subtotal" if sheet.rows[r].is_total else "component",
                                value=chain_cell.value,
                                quantum=chain_cell.quantum,
                                mention_id=chain_cell.mention_id,
                            )
                        )
                elif len(subtotal_rows) >= AGGREGATE_MIN_COMPONENTS and not available:
                    subtotal_labels = {
                        normalize_label(sheet.rows[r].label or "") for r in subtotal_rows
                    }
                    if len(subtotal_labels) == 1:
                        direction = "subtotals"
                        for r in subtotal_rows:
                            chain_cell = _cell(sheet, r, col)
                            chain.append(
                                _ComponentDecision(
                                    r,
                                    sheet.rows[r].label,
                                    True,
                                    "stated_subtotal",
                                    value=chain_cell.value,
                                    quantum=chain_cell.quantum,
                                    mention_id=chain_cell.mention_id,
                                )
                            )
                if direction is not None and len(chain) >= AGGREGATE_MIN_COMPONENTS:
                    segments.append(_Segment(row_idx, chain, direction, False))
        boundary = row_idx + 1
        total_rows_seen.append(row_idx)
    return segments


def _cell(sheet: TableSheet, row: int, col: int) -> CellParse:
    return sheet.cells[(row, col)]


def _component_conversion(mention: QuantMention, unit: UnitDef | None) -> ConversionDetail:
    """Complete, reproducible conversion evidence for one participating
    value. When the column is unitless no conversion happens and the factor
    is the explicit identity."""
    return ConversionDetail(
        mention_id=mention.mention_id,
        raw=mention.raw_number,
        parsed_value=mention.value or "",
        unit=unit.canonical if unit is not None else mention.unit_canonical,
        conversion_factor=(
            decimal_str(unit.factor) if unit is not None else (mention.conversion_factor or "1")
        ),
        canonical_value=(
            decimal_str(convert_to_canonical(Decimal(mention.value), unit))
            if unit is not None and mention.value is not None
            else (mention.canonical_value or mention.value)
        ),
        canonical_unit=(canonical_unit_for(unit) if unit is not None else mention.canonical_unit),
    )


def _component_records(segment: _Segment, unit: UnitDef | None) -> list[AggregationComponent]:
    return [
        AggregationComponent(
            row=decision.row,
            label=(decision.label or "")[:80] or None,
            included=decision.included,
            reason=decision.reason,
            value=(decimal_str(decision.value) if decision.value is not None else None),
            canonical_value=(
                decimal_str(convert_to_canonical(decision.value, unit))
                if decision.value is not None and unit is not None
                else (decimal_str(decision.value) if decision.value is not None else None)
            ),
            conversion_factor=(decimal_str(unit.factor) if unit is not None else "1"),
            overlaps_row=decision.overlaps_row,
        )
        for decision in segment.decisions
    ]


def _check_record(
    sheet: TableSheet,
    col_info: ColInfo,
    segment: _Segment,
    stated_cell: CellParse,
    computed: Decimal,
    abs_diff: Decimal,
    rel: Decimal | None,
    rounding_tol: Decimal,
    decision: str,
    identical_copies: list[str],
) -> P3AggregationCheck:
    unit = col_info.unit
    return P3AggregationCheck(
        check_id=deterministic_id(
            "P3A",
            sheet.project_id,
            sheet.document_id,
            sheet.table_id,
            str(col_info.index),
            str(segment.total_row),
            segment.direction,
            ",".join(str(c.row) for c in segment.components),
        ),
        project_id=sheet.project_id,
        document_id=sheet.document_id,
        table_id=sheet.table_id,
        page_number=sheet.page_number,
        column=col_info.index,
        column_header=col_info.header[:120],
        unit=unit.canonical if unit else None,
        conversion_factor=decimal_str(unit.factor) if unit else "1",
        canonical_unit=canonical_unit_for(unit) if unit else None,
        total_row=segment.total_row,
        total_label=(sheet.rows[segment.total_row].label or "")[:80] or None,
        direction=segment.direction,
        doc_decimal_style=sheet.doc_style,
        grouping_styles=list(sheet.grouping_styles),
        components=_component_records(segment, unit),
        expected_total=decimal_str(computed),
        observed_total=decimal_str(stated_cell.value or Decimal(0)),
        abs_diff=decimal_str(abs_diff),
        rel_diff=(decimal_str(rel.quantize(Decimal("0.000001"))) if rel is not None else None),
        rounding_tolerance=decimal_str(rounding_tol),
        rel_tolerance=decimal_str(AGGREGATE_REL_TOLERANCE),
        decision=decision,  # type: ignore[arg-type]
        table_fingerprint=sheet.fingerprint,
        identical_copies=sorted(identical_copies),
    )


def check_aggregations(
    sheets: list[TableSheet], mentions_by_id: dict[str, QuantMention]
) -> AggregationOutcome:
    findings: list[P3FindingRecord] = []
    checks: list[P3AggregationCheck] = []
    suppressed: dict[str, int] = {}
    checks_total = 0
    checks_consistent = 0

    # Structural copies: the same table serialized in several documents (or
    # twice in one) is ONE representation. Only the first sheet (in the
    # deterministic extraction order) runs total checks; copies are recorded.
    copies_by_fingerprint: dict[tuple[str, str], list[str]] = {}
    for sheet in sheets:
        copies_by_fingerprint.setdefault((sheet.project_id, sheet.fingerprint), []).append(
            sheet.table_id
        )
    fingerprint_primary = {key: table_ids[0] for key, table_ids in copies_by_fingerprint.items()}

    for sheet in sheets:
        fingerprint_key = (sheet.project_id, sheet.fingerprint)
        identical_copies = [
            table_id
            for table_id in copies_by_fingerprint[fingerprint_key]
            if table_id != sheet.table_id
        ]
        if fingerprint_primary[fingerprint_key] != sheet.table_id:
            # A structural copy of an already-checked table: one
            # representation, zero additional findings of ANY kind.
            suppressed["aggregation_duplicate_table_copy"] = (
                suppressed.get("aggregation_duplicate_table_copy", 0) + 1
            )
            continue
        if sheet.header_index_only:
            # Page-continuation fragment: its totals reference component rows
            # on previous pages — any segment sum here would be fabricated.
            # Same-row checks (bounds) remain valid on fragments.
            suppressed["aggregation_table_fragment"] = (
                suppressed.get("aggregation_table_fragment", 0) + 1
            )
            findings.extend(_row_bound_findings(sheet, mentions_by_id))
            continue
        seen_signatures: set[tuple[str, str, int, str]] = set()
        for col_info in sheet.cols:
            col = col_info.index
            if not col_info.summable:
                continue
            if col_info.unit is not None and col_info.unit.kind in ("percent",):
                continue  # percent columns are checked by the percent rule
            for segment in _segments_for_column(sheet, col):
                if segment.incomplete:
                    suppressed["aggregation_incomplete_components"] = (
                        suppressed.get("aggregation_incomplete_components", 0) + 1
                    )
                    continue
                stated_cell = _cell(sheet, segment.total_row, col)
                assert stated_cell.value is not None and stated_cell.quantum is not None
                components = segment.components
                if len(components) < AGGREGATE_MIN_COMPONENTS:
                    continue
                if all(c.value == stated_cell.value for c in components):
                    # Every "component" equals the stated total: a merged /
                    # repeated-value layout, not an aggregation relationship.
                    suppressed["aggregation_duplicate_components"] = (
                        suppressed.get("aggregation_duplicate_components", 0) + 1
                    )
                    continue
                component_periods = {
                    sheet.rows[c.row].period_key
                    for c in components
                    if sheet.rows[c.row].period_key is not None
                }
                if len(component_periods) > 1:
                    # Components stated for DIFFERENT periods must not be
                    # summed against one total.
                    suppressed["aggregation_mixed_periods"] = (
                        suppressed.get("aggregation_mixed_periods", 0) + 1
                    )
                    continue
                computed = sum((c.value for c in components if c.value is not None), Decimal(0))
                stated = stated_cell.value
                # Rounding tolerance: half of the STATED total's display
                # quantum. Per-operand tolerances are deliberately not used:
                # they grow with the component count and were audited to
                # excuse real integer mismatches (5+2+3+4=14 vs «Итого 15»
                # must be a mismatch).
                rounding_tol = stated_cell.quantum * Decimal("0.5")
                abs_diff = abs(computed - stated)
                denominator = max(abs(computed), abs(stated))
                rel = abs_diff / denominator if denominator != 0 else None
                checks_total += 1
                mismatch = abs_diff > rounding_tol and (
                    rel is None or rel > AGGREGATE_REL_TOLERANCE
                )
                signature = (
                    decimal_str(stated),
                    decimal_str(computed),
                    len(components),
                    segment.direction,
                )
                duplicate_column = signature in seen_signatures
                seen_signatures.add(signature)
                check_record = _check_record(
                    sheet,
                    col_info,
                    segment,
                    stated_cell,
                    computed,
                    abs_diff,
                    rel,
                    rounding_tol,
                    "consistent" if not mismatch else "mismatch",
                    identical_copies,
                )
                if not duplicate_column:
                    checks.append(check_record)
                if not mismatch:
                    checks_consistent += 1
                    continue
                if duplicate_column:
                    continue  # merged duplicated column group
                finding = _aggregate_finding(
                    sheet,
                    col_info,
                    segment,
                    stated_cell,
                    computed,
                    abs_diff,
                    rel,
                    rounding_tol,
                    mentions_by_id,
                    identical_copies,
                )
                check_record.finding_id = finding.finding_id
                findings.append(finding)

        findings.extend(_percent_column_findings(sheet, mentions_by_id))
        findings.extend(_row_bound_findings(sheet, mentions_by_id))

    findings.sort(key=lambda f: f.finding_id)
    checks.sort(key=lambda c: c.check_id)
    return AggregationOutcome(
        findings=findings,
        checks=checks,
        checks_total=checks_total,
        checks_consistent=checks_consistent,
        suppressed_counts=suppressed,
    )


def _aggregate_finding(
    sheet: TableSheet,
    col_info: ColInfo,
    segment: _Segment,
    stated_cell: CellParse,
    computed: Decimal,
    abs_diff: Decimal,
    rel: Decimal | None,
    rounding_tol: Decimal,
    mentions_by_id: dict[str, QuantMention],
    identical_copies: list[str],
) -> P3FindingRecord:
    components = segment.components
    mention_ids = sorted(
        [c.mention_id for c in components if c.mention_id]
        + ([stated_cell.mention_id] if stated_cell.mention_id else [])
    )
    participating = [mentions_by_id[m] for m in mention_ids if m in mentions_by_id]
    extra: list[tuple[str, float]] = []
    if segment.direction in ("below", "including"):
        extra.append(("aggregation_direction_after", -0.1))
    if segment.direction in ("subtotals", "mixed_chain"):
        extra.append(("aggregation_from_subtotals", -0.1))
    confidence, factors = finding_confidence("aggregate_total_mismatch", participating, extra)
    unit = col_info.unit
    kind = unit.kind if unit else "unknown"
    max_abs = max(abs(computed), abs(Decimal(stated_cell.value or 0)))
    canonical_max = convert_to_canonical(max_abs, unit) if unit is not None else max_abs
    severity = severity_for_conflict(rel, canonical_max, kind, confidence)
    high_allowed = segment.direction in ("above", "including") and not any(
        "ocr_source" in m.flags for m in participating
    )
    severity = cap_severity(severity, "high" if high_allowed else "medium")

    total_label = sheet.rows[segment.total_row].label or "Итого"
    unit_text = f" {unit.canonical}" if unit else ""
    direction_text = {
        "above": "строки над итоговой строкой",
        "below": "строки под итоговой строкой",
        "including": "строки «в том числе» под итоговой строкой",
        "subtotals": "заявленные промежуточные итоги",
        "mixed_chain": "независимые строки и заявленные промежуточные итоги",
    }[segment.direction]
    title = (
        f"Сумма компонентов не сходится с итогом «{total_label}»:"
        f" заявлено {decimal_str(Decimal(stated_cell.value or 0))}{unit_text},"
        f" расчёт {decimal_str(computed)}{unit_text}"
    )
    copies_note = (
        f" Идентичные копии таблицы: {', '.join(identical_copies)}"
        " (учтены как одно представление, не как независимое подтверждение)."
        if identical_copies
        else ""
    )
    explanation = (
        f"В таблице {sheet.table_id} (столбец {col_info.index},"
        f" заголовок «{col_info.header[:80]}») итоговая строка"
        f" {segment.total_row} заявляет {decimal_str(Decimal(stated_cell.value or 0))}"
        f"{unit_text}, однако сумма {len(components)} компонентов"
        f" ({direction_text}) даёт {decimal_str(computed)}{unit_text}."
        f" Расхождение {decimal_str(abs_diff)}"
        + (f" ({decimal_str((rel * 100).quantize(Decimal('0.1')))}%)" if rel is not None else "")
        + f" при допуске округления {decimal_str(rounding_tol)} и относительном"
        f" допуске {decimal_str(AGGREGATE_REL_TOLERANCE)}.{copies_note} {_REVIEW_NOTE}"
    )
    component_rows_text = ",".join(str(c.row) for c in components)
    return P3FindingRecord(
        finding_id=deterministic_id(
            "P3",
            sheet.project_id,
            sheet.document_id,
            "aggregate_total_mismatch",
            "P3-AGG-TOTAL",
            sheet.table_id,
            str(col_info.index),
            str(segment.total_row),
            component_rows_text,
        ),
        project_id=sheet.project_id,
        document_id=sheet.document_id,
        finding_type="aggregate_total_mismatch",
        severity=severity,
        priority_score=points_for(severity),
        confidence=confidence,
        confidence_factors=factors,
        rule_id="P3-AGG-TOTAL",
        title=title,
        explanation=explanation,
        evidence=[
            P3Evidence(
                document_id=sheet.document_id,
                page_number=sheet.page_number,
                quote=f"{total_label}: {stated_cell.value}",
                note=(
                    f"таблица {sheet.table_id}, итоговая строка {segment.total_row},"
                    f" компоненты: строки {component_rows_text}, столбец {col_info.index}"
                ),
            )
        ],
        page_references=[sheet.page_number] if sheet.page_number else [],
        mention_ids=mention_ids,
        candidate_id=None,
        comparison=ComparisonDetail(
            formula="stated_total ≈ sum(components); tol = 0.5*Σquanta + rel 2%",
            expected_value=decimal_str(computed),
            observed_value=decimal_str(Decimal(stated_cell.value or 0)),
            abs_diff=decimal_str(abs_diff),
            rel_diff=(decimal_str(rel.quantize(Decimal("0.000001"))) if rel is not None else None),
            tolerance_abs=decimal_str(stated_cell.quantum or Decimal(1)),
            tolerance_rel=decimal_str(AGGREGATE_REL_TOLERANCE),
            rounding_tolerance=decimal_str(rounding_tol),
            canonical_unit=canonical_unit_for(unit) if unit else None,
            conversions=[
                _component_conversion(mentions_by_id[m], unit)
                for m in mention_ids
                if m in mentions_by_id
            ],
            aggregation=AggregationDetail(
                table_id=sheet.table_id,
                column=col_info.index,
                total_row=segment.total_row,
                direction=segment.direction,
                table_fingerprint=sheet.fingerprint,
                identical_copies=sorted(identical_copies),
                components=[
                    AggregationComponent(
                        row=decision.row,
                        label=(decision.label or "")[:80] or None,
                        included=decision.included,
                        reason=decision.reason,
                        value=(decimal_str(decision.value) if decision.value is not None else None),
                        canonical_value=(
                            decimal_str(convert_to_canonical(decision.value, unit))
                            if decision.value is not None and unit is not None
                            else (
                                decimal_str(decision.value) if decision.value is not None else None
                            )
                        ),
                        conversion_factor=(decimal_str(unit.factor) if unit is not None else "1"),
                        overlaps_row=decision.overlaps_row,
                    )
                    for decision in segment.decisions
                ],
            ),
        ),
        semantic_rationale=(
            "Агрегационная связь установлена из явной структуры таблицы:"
            f" итоговая строка «{total_label}» и {direction_text};"
            " строки «в том числе»/«из них» и их продолжения исключены из"
            " суммы; вложенные промежуточные итоги не считаются дважды."
        ),
        observed_value=f"{stated_cell.value}{unit_text}",
        expected_value=f"{decimal_str(computed)}{unit_text}",
        quality_flags=sorted({flag for m in participating for flag in m.flags}),
        limitations=(
            "Структура таблицы восстановлена эвристически из сетки ячеек;"
            " объединённые ячейки и переносы строк могли исказить сегмент."
            " Эксперт должен сверить состав компонентов с оригиналом."
        ),
    )


def _percent_column_findings(
    sheet: TableSheet, mentions_by_id: dict[str, QuantMention]
) -> list[P3FindingRecord]:
    """Rule D over tables: share column vs quantity column with a total row."""
    findings: list[P3FindingRecord] = []
    share_cols = [
        c for c in sheet.cols if c.is_share_col or (c.unit is not None and c.unit.kind == "percent")
    ]
    if not share_cols:
        return findings
    for share_col in share_cols:
        segments = _segments_for_column(sheet, share_col.index)
        for segment in segments:
            stated_total = _cell(sheet, segment.total_row, share_col.index)
            if stated_total.value is None:
                continue
            if abs(stated_total.value - Decimal(100)) > PERCENT_TOTAL_100_WINDOW:
                continue  # not a 100%-share column
            qty_col = _paired_quantity_column(sheet, share_col.index, segment)
            if qty_col is None:
                continue
            qty_total_cell = _cell(sheet, segment.total_row, qty_col)
            if qty_total_cell.status != "single" or not qty_total_cell.value:
                continue
            emitted = 0
            for row in (c.row for c in segment.components):
                if emitted >= _MAX_PERCENT_FINDINGS_PER_TABLE:
                    break
                pct_cell = _cell(sheet, row, share_col.index)
                qty_cell = _cell(sheet, row, qty_col)
                if pct_cell.status != "single" or qty_cell.status != "single":
                    continue
                assert pct_cell.value is not None and qty_cell.value is not None
                expected = (qty_cell.value / qty_total_cell.value * 100).quantize(
                    Decimal("0.000001")
                )
                tolerance = PERCENT_ABS_TOLERANCE_PP + (
                    (pct_cell.quantum or Decimal(1)) * Decimal("0.5")
                )
                diff = abs(expected - pct_cell.value)
                if diff <= tolerance:
                    continue
                emitted += 1
                mention_ids = sorted(
                    m
                    for m in (
                        pct_cell.mention_id,
                        qty_cell.mention_id,
                        qty_total_cell.mention_id,
                    )
                    if m
                )
                participating = [mentions_by_id[m] for m in mention_ids if m in mentions_by_id]
                confidence, factors = finding_confidence("percentage_mismatch", participating, [])
                severity = "low" if diff <= Decimal(5) else "medium"
                if confidence < 0.5:
                    severity = "low"
                row_label = sheet.rows[row].label or f"строка {row}"
                findings.append(
                    P3FindingRecord(
                        finding_id=deterministic_id(
                            "P3",
                            sheet.project_id,
                            sheet.document_id,
                            "percentage_mismatch",
                            "P3-PCT-COLUMN",
                            sheet.table_id,
                            str(share_col.index),
                            str(row),
                        ),
                        project_id=sheet.project_id,
                        document_id=sheet.document_id,
                        finding_type="percentage_mismatch",
                        severity=severity,
                        priority_score=points_for(severity),
                        confidence=confidence,
                        confidence_factors=factors,
                        rule_id="P3-PCT-COLUMN",
                        title=(
                            f"Доля в таблице не совпадает с расчётом:"
                            f" «{row_label[:60]}» — заявлено {pct_cell.value}%,"
                            f" расчёт {decimal_str(expected.quantize(Decimal('0.01')))}%"
                        ),
                        explanation=(
                            f"В таблице {sheet.table_id} столбец долей"
                            f" {share_col.index} связан со столбцом количества"
                            f" {qty_col} (итог по долям ≈ 100%). Для строки {row}"
                            f" («{row_label[:60]}»): {decimal_str(qty_cell.value)}"
                            f" / {decimal_str(qty_total_cell.value)} × 100 ="
                            f" {decimal_str(expected.quantize(Decimal('0.01')))}%,"
                            f" заявлено {pct_cell.value}%. Расхождение"
                            f" {decimal_str(diff.quantize(Decimal('0.01')))} п.п."
                            f" при допуске {decimal_str(tolerance)} п.п. {_REVIEW_NOTE}"
                        ),
                        evidence=[
                            P3Evidence(
                                document_id=sheet.document_id,
                                page_number=sheet.page_number,
                                quote=f"{row_label}: {qty_cell.value} → {pct_cell.value}%",
                                note=(
                                    f"таблица {sheet.table_id}, строка {row},"
                                    f" столбцы {qty_col}/{share_col.index}"
                                ),
                            )
                        ],
                        page_references=[sheet.page_number] if sheet.page_number else [],
                        mention_ids=mention_ids,
                        candidate_id=None,
                        comparison=ComparisonDetail(
                            formula="percentage ≈ quantity / total × 100",
                            expected_value=decimal_str(expected.quantize(Decimal("0.01"))),
                            observed_value=decimal_str(pct_cell.value),
                            abs_diff=decimal_str(diff.quantize(Decimal("0.01"))),
                            rel_diff=None,
                            tolerance_abs=decimal_str(tolerance),
                            tolerance_rel=None,
                            rounding_tolerance=decimal_str(
                                (pct_cell.quantum or Decimal(1)) * Decimal("0.5")
                            ),
                            canonical_unit="%",
                            conversions=[],
                        ),
                        semantic_rationale=(
                            "Связь «количество — доля» установлена по структуре"
                            " таблицы: столбец долей суммируется к ~100% в той же"
                            " итоговой строке, что и столбец количества."
                        ),
                        observed_value=f"{pct_cell.value} %",
                        expected_value=(f"{decimal_str(expected.quantize(Decimal('0.01')))} %"),
                        quality_flags=sorted({flag for m in participating for flag in m.flags}),
                        limitations=(
                            "Пара столбцов определена эвристически (ближайший"
                            " суммируемый столбец с итогом); эксперт должен"
                            " подтвердить связь количества и доли."
                        ),
                    )
                )
    return findings


def _paired_quantity_column(sheet: TableSheet, share_col: int, segment: _Segment) -> int | None:
    """Nearest summable non-percent column with a parseable total and
    parseable components in the same segment (left preferred)."""
    candidates = [c for c in sheet.cols if c.index != share_col and c.summable]
    candidates.sort(key=lambda c: (abs(c.index - share_col), c.index > share_col, c.index))
    for candidate in candidates:
        if candidate.unit is not None and candidate.unit.kind == "percent":
            continue
        total_cell = sheet.cells.get((segment.total_row, candidate.index))
        if total_cell is None or total_cell.status != "single" or not total_cell.value:
            continue
        parseable = sum(
            1
            for row in (c.row for c in segment.components)
            if (c := sheet.cells.get((row, candidate.index))) is not None and c.status == "single"
        )
        if parseable >= AGGREGATE_MIN_COMPONENTS:
            return candidate.index
    return None


def _row_bound_findings(
    sheet: TableSheet, mentions_by_id: dict[str, QuantMention]
) -> list[P3FindingRecord]:
    """Rule F, structural variant: «норматив» column vs «факт» column."""
    findings: list[P3FindingRecord] = []
    limit_cols = []
    actual_cols = []
    for col in sheet.cols:
        qualifiers = extract_qualifiers(col.header)
        if col.unit is None:
            continue
        if "limit" in qualifiers:
            limit_cols.append(col)
        elif "actual" in qualifiers:
            actual_cols.append(col)
    if not limit_cols or not actual_cols:
        return findings
    for limit_col in limit_cols:
        for actual_col in actual_cols:
            assert limit_col.unit is not None and actual_col.unit is not None
            if dimension_key(limit_col.unit) != dimension_key(actual_col.unit):
                continue
            for row_info in sheet.rows:
                if row_info.index < sheet.header_rows or row_info.is_total or row_info.is_divider:
                    continue
                limit_cell = sheet.cells.get((row_info.index, limit_col.index))
                actual_cell = sheet.cells.get((row_info.index, actual_col.index))
                if (
                    limit_cell is None
                    or actual_cell is None
                    or limit_cell.status != "single"
                    or actual_cell.status != "single"
                ):
                    continue
                assert limit_cell.value is not None and actual_cell.value is not None
                limit_canonical = convert_to_canonical(limit_cell.value, limit_col.unit)
                actual_canonical = convert_to_canonical(actual_cell.value, actual_col.unit)
                rounding_tol = (
                    convert_to_canonical(limit_cell.quantum or Decimal(1), limit_col.unit)
                    + convert_to_canonical(actual_cell.quantum or Decimal(1), actual_col.unit)
                ) * Decimal("0.5")
                excess = actual_canonical - limit_canonical
                if excess <= rounding_tol:
                    continue
                rel = excess / abs(limit_canonical) if limit_canonical != 0 else None
                if rel is not None and rel <= AGGREGATE_REL_TOLERANCE:
                    continue
                mention_ids = sorted(
                    m for m in (limit_cell.mention_id, actual_cell.mention_id) if m
                )
                participating = [mentions_by_id[m] for m in mention_ids if m in mentions_by_id]
                confidence, factors = finding_confidence("bound_violation", participating, [])
                severity = severity_for_conflict(
                    rel,
                    max(abs(actual_canonical), abs(limit_canonical)),
                    limit_col.unit.kind,
                    confidence,
                )
                severity = cap_severity(severity, "medium")
                row_label = row_info.label or f"строка {row_info.index}"
                findings.append(
                    P3FindingRecord(
                        finding_id=deterministic_id(
                            "P3",
                            sheet.project_id,
                            sheet.document_id,
                            "bound_violation",
                            "P3-BOUND-ROW",
                            sheet.table_id,
                            str(row_info.index),
                            str(limit_col.index),
                            str(actual_col.index),
                        ),
                        project_id=sheet.project_id,
                        document_id=sheet.document_id,
                        finding_type="bound_violation",
                        severity=severity,
                        priority_score=points_for(severity),
                        confidence=confidence,
                        confidence_factors=factors,
                        rule_id="P3-BOUND-ROW",
                        title=(
                            f"Фактическое значение выше норматива в одной строке:"
                            f" «{row_label[:60]}» ({decimal_str(actual_cell.value)}"
                            f" {actual_col.unit.canonical} >"
                            f" {decimal_str(limit_cell.value)}"
                            f" {limit_col.unit.canonical})"
                        ),
                        explanation=(
                            f"В таблице {sheet.table_id}, строка {row_info.index}"
                            f" («{row_label[:60]}»): столбец-норматив"
                            f" {limit_col.index} («{limit_col.header[:60]}»)"
                            f" заявляет {decimal_str(limit_cell.value)}"
                            f" {limit_col.unit.canonical}, столбец фактического"
                            f" значения {actual_col.index}"
                            f" («{actual_col.header[:60]}») —"
                            f" {decimal_str(actual_cell.value)}"
                            f" {actual_col.unit.canonical}. В канонических единицах"
                            f" превышение {decimal_str(excess)}"
                            + (
                                f" ({decimal_str((rel * 100).quantize(Decimal('0.1')))}%)."
                                if rel is not None
                                else "."
                            )
                            + f" {_REVIEW_NOTE}"
                        ),
                        evidence=[
                            P3Evidence(
                                document_id=sheet.document_id,
                                page_number=sheet.page_number,
                                quote=(
                                    f"{row_label}: норматив {limit_cell.value},"
                                    f" факт {actual_cell.value}"
                                ),
                                note=(
                                    f"таблица {sheet.table_id}, строка"
                                    f" {row_info.index}, столбцы"
                                    f" {limit_col.index}/{actual_col.index}"
                                ),
                            )
                        ],
                        page_references=([sheet.page_number] if sheet.page_number else []),
                        mention_ids=mention_ids,
                        candidate_id=None,
                        comparison=ComparisonDetail(
                            formula=(
                                "violation <=> actual > limit + rounding_tol"
                                " AND (actual-limit)/limit > rel_tol"
                            ),
                            expected_value=decimal_str(limit_canonical),
                            observed_value=decimal_str(actual_canonical),
                            abs_diff=decimal_str(excess),
                            rel_diff=(
                                decimal_str(rel.quantize(Decimal("0.000001")))
                                if rel is not None
                                else None
                            ),
                            tolerance_abs=None,
                            tolerance_rel=decimal_str(AGGREGATE_REL_TOLERANCE),
                            rounding_tolerance=decimal_str(rounding_tol),
                            canonical_unit=(
                                mentions_by_id[mention_ids[0]].canonical_unit
                                if mention_ids and mention_ids[0] in mentions_by_id
                                else None
                            ),
                            conversions=[
                                ConversionDetail(
                                    mention_id=m,
                                    raw=mentions_by_id[m].raw_number,
                                    parsed_value=mentions_by_id[m].value or "",
                                    unit=mentions_by_id[m].unit_canonical,
                                    conversion_factor=mentions_by_id[m].conversion_factor,
                                    canonical_value=mentions_by_id[m].canonical_value,
                                    canonical_unit=mentions_by_id[m].canonical_unit,
                                )
                                for m in mention_ids
                                if m in mentions_by_id
                            ],
                        ),
                        semantic_rationale=(
                            "Норматив и фактическое значение взяты из ОДНОЙ строки"
                            " таблицы (одно вещество/объект); связь установлена по"
                            " квалификаторам заголовков столбцов"
                            " («норматив/ПДВ» vs «факт»)."
                        ),
                        observed_value=(
                            f"{decimal_str(actual_cell.value)} {actual_col.unit.canonical}"
                        ),
                        expected_value=(
                            f"<= {decimal_str(limit_cell.value)} {limit_col.unit.canonical}"
                        ),
                        quality_flags=sorted({flag for m in participating for flag in m.flags}),
                        limitations=(
                            "Роли столбцов определены по словам в заголовках;"
                            " превышение норматива в проектной документации может"
                            " быть объяснено (разные режимы) — требуется эксперт."
                        ),
                    )
                )
    return findings
