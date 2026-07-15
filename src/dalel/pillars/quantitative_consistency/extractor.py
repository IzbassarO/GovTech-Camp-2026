"""Quantitative mention extraction from curated sections and tables.

Narrative mentions come from ``sections.jsonl`` ONLY (pages duplicate the
same text; using both would double-extract). Table mentions come from
``tables.jsonl``. Section text may contain flattened table debris (verified
in the corpus), so narrative numbers are kept only when a unit is attached
or they participate in an explicit percent triple — bare number runs are
counted as ``narrative_unitless`` diagnostics instead of becoming facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from dalel.pillars.quantitative_consistency.config import (
    MENTION_CONFIDENCE_MIN,
    MENTION_CONFIDENCE_PENALTIES,
)
from dalel.pillars.quantitative_consistency.normalization import (
    normalize_for_scan,
    normalize_label,
)
from dalel.pillars.quantitative_consistency.number_parser import (
    QuantitySpan,
    ScanResult,
    decimal_str,
    scan_text,
    thousands_grouping_styles,
    unambiguous_decimal_style,
)
from dalel.pillars.quantitative_consistency.schemas import (
    MentionLocation,
    P3SuppressedSample,
    QuantMention,
    deterministic_id,
)
from dalel.pillars.quantitative_consistency.semantic_context import (
    classify_metric,
    extract_period,
    extract_qualifiers,
    extract_source_key,
    extract_sub_entity,
    extract_substance,
    is_subset_label,
    is_total_label,
    substance_from_code,
)
from dalel.pillars.quantitative_consistency.units import (
    UnitDef,
    canonical_unit_for,
    convert_to_canonical,
    dimension_key,
    lookup_unit,
)

_EVIDENCE_BEFORE = 60
_EVIDENCE_AFTER = 40
_CONTEXT_BEFORE = 140
_CONTEXT_AFTER = 60
_SUPPRESSED_EXAMPLE_CAP = 5
_SAMPLES_PER_REASON = 10
_SAMPLES_PER_REASON_DOC = 2

# «5 из 20 (25 %)» — the only narrative percent linkage treated as explicit.
_PERCENT_TRIPLE_RE = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s+из\s+(\d+(?:[.,]\d+)?)\s*\(\s*(\d+(?:[.,]\d+)?)\s*%\s*\)"
)

# Column headers that must never be summed or cross-compared as quantities.
# Word-bounded time-period words: «Год достижения НДВ» marks an identifier
# column, while «т/год» in a unit expression must NOT trigger (guarded by
# the unit check at the call sites).
_NON_QUANTITY_HEADER_RE = re.compile(
    r"код|класс|№|номер|дата|широт|долгот|коэффициент|категор|кратност|степень"
    r"|\bгод\b|\bжыл\b|\byear\b|квартал|месяц|\bп\s*/?\s*п\b|инв|шифр",
)

# «№ п.п.» / «№ п/п» is the row-number header («по порядку»); its dotted
# spelling collides with the percentage-points unit «п.п.» in the registry,
# so a percent_points unit found in such a header must be discarded.
_ITEM_NUMBER_HEADER_RE = re.compile(r"\b(?:no|n|№)\s*п\s*п\b")

# Section titles that positively mark whole-enterprise inventory content.
_ENTERPRISE_TITLE_RE = re.compile(
    r"перечень загрязняющ|нормативы? выбросов|всего по предприятию"
    r"|итого по предприятию|в целом по предприятию|сводн|по объекту в целом",
)
_CODE_HEADER_RE = re.compile(r"\bкод\b")
_SOURCE_HEADER_RE = re.compile(r"источник|ист\s|№\s*ист")
_TOTAL_HEADER_RE = re.compile(r"итого|всего|суммарн|барлығы|жиыны|total")
_SHARE_LABEL_RE = re.compile(r"доля|удельный вес|share|пайыз|үлес")
_SOURCE_CODE_CELL_RE = re.compile(r"^\d{2,4}(?:-\d{2,4})?$")
_SENTENCE_BOUNDARY_RE = re.compile(r"[.;!?]\s|\n")

# Substance identity is only meaningful for dimensions that measure the
# substance itself; a substance name near an area/height/power figure is
# adjacent context, not identity.
_SUBSTANCE_DIMENSION_KINDS = frozenset(
    {"mass", "mass_rate", "concentration", "concentration_normal", "mass_fraction"}
)


def _sentence_window(text: str, start: int, end: int, after: int = 40) -> str:
    """Window bounded by the previous sentence boundary (substances and
    qualifiers must come from the SAME sentence as the number)."""
    lower = max(0, start - _CONTEXT_BEFORE)
    prefix = text[lower:start]
    boundaries = list(_SENTENCE_BOUNDARY_RE.finditer(prefix))
    if boundaries:
        lower += boundaries[-1].end()
    return text[lower : min(len(text), end + after)]


@dataclass
class PercentTriple:
    """Explicitly linked numerator / denominator / percentage in one sentence."""

    project_id: str
    document_id: str
    section_id: str
    page_number: int | None
    numerator: Decimal
    denominator: Decimal
    percent: Decimal
    percent_quantum: Decimal
    quote: str
    mention_ids: tuple[str, str, str]  # numerator, denominator, percent
    ocr_source: bool


@dataclass
class CellParse:
    """Parse status of one table body cell."""

    status: str  # empty | single | multi | text | suppressed
    value: Decimal | None = None
    quantum: Decimal | None = None
    mention_id: str | None = None
    negative_possible: bool = False


@dataclass
class RowInfo:
    index: int
    label: str | None
    is_total: bool
    is_subset: bool
    is_divider: bool
    substance: str | None
    source_key: str | None
    # Label-only row with no values («Опасные отходы»): structures the table
    # into categories and terminates «в том числе» enumeration spans.
    is_category: bool = False
    # Reporting period stated in the row label («А за 2024 год»).
    period_key: str | None = None


@dataclass
class ColInfo:
    index: int
    header: str
    unit: UnitDef | None
    summable: bool
    is_total_col: bool
    is_share_col: bool
    period_key: str | None
    is_identifier: bool = False


@dataclass
class TableSheet:
    """In-memory table structure shared by extraction and aggregation."""

    table_id: str
    project_id: str
    document_id: str
    page_number: int | None
    caption: str | None
    header_rows: int
    rows: list[RowInfo]
    cols: list[ColInfo]
    cells: dict[tuple[int, int], CellParse]
    ocr_source: bool
    # True when the header is ONLY a column-index row («1 2 3 …») or absent:
    # in this corpus that marks a page-continuation fragment whose totals
    # reference component rows on previous pages.
    header_index_only: bool = False
    # Structural fingerprint over normalized cells: identical copies of one
    # table in several documents are ONE representation, not independent
    # evidence.
    fingerprint: str = ""
    # Parser state used for this document (needed to replay cell parsing).
    doc_style: str | None = None
    grouping_styles: tuple[str, ...] = ()


@dataclass
class ExtractionResult:
    mentions: list[QuantMention] = field(default_factory=list)
    sheets: list[TableSheet] = field(default_factory=list)
    percent_triples: list[PercentTriple] = field(default_factory=list)
    suppressed_counts: dict[str, int] = field(default_factory=dict)
    suppressed_examples: dict[str, list[str]] = field(default_factory=dict)
    suppressed_samples: list[P3SuppressedSample] = field(default_factory=list)
    sample_counts: dict[str, int] = field(default_factory=dict)
    sample_counts_by_doc: dict[tuple[str, str], int] = field(default_factory=dict)
    doc_styles: dict[str, str | None] = field(default_factory=dict)


def _mention_confidence(flags: list[str]) -> float:
    confidence = 1.0
    for flag in flags:
        confidence -= MENTION_CONFIDENCE_PENALTIES.get(flag, 0.0)
    return round(max(MENTION_CONFIDENCE_MIN, confidence), 2)


def find_unit_in_label(text: str) -> UnitDef | None:
    """Unit declared inside a column header / label, e.g. «Выброс, т/год (M)».

    Deterministic segment probing: comma/paren/slash-free segments and
    adjacent-token pairs are looked up in the declared registry; the LAST
    match wins (units come after the metric words in this corpus).
    """
    normalized = normalize_for_scan(text)
    found: UnitDef | None = None
    for segment in re.split(r"[,;()]", normalized):
        segment = segment.strip()
        if not segment:
            continue
        unit = lookup_unit(segment)
        if unit is not None:
            found = unit
            continue
        tokens = segment.split()
        for size in (3, 2, 1):
            for idx in range(len(tokens) - size + 1):
                candidate = " ".join(tokens[idx : idx + size])
                unit = lookup_unit(candidate)
                if unit is not None:
                    found = unit
    return found


class _DocumentExtractor:
    def __init__(
        self,
        document: dict[str, Any],
        sections: list[dict[str, Any]],
        tables: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        result: ExtractionResult,
    ) -> None:
        self.document = document
        self.project_id = str(document["project_id"])
        self.document_id = str(document["document_id"])
        self.sections = sections
        self.tables = tables
        self.result = result
        self.ocr_pages = {int(p["page_number"]) for p in pages if bool(p.get("ocr_applied"))}
        ocr_meta = document.get("ocr") or {}
        self.ocr_pages.update(int(n) for n in ocr_meta.get("ocr_pages") or [])
        corpus = "\n".join(
            [s.get("text") or "" for s in sections]
            + [cell for t in tables for row in t["cells"] for cell in row]
        )
        self.doc_style = unambiguous_decimal_style(corpus)
        self.grouping_styles = thousands_grouping_styles(corpus)
        result.doc_styles[self.document_id] = self.doc_style
        self._previous_table_attribution: dict[str, Any] | None = None

        # --- source BLOCKS from heading sequence -------------------------------
        # A source heading («Склад … - источник №6023») opens a block that
        # runs until the next source heading or an enterprise-inventory
        # section. Only pages STRICTLY INSIDE a block are attributed: on a
        # boundary page the heading may sit above or below a table and the
        # dataset has no within-page ordering, so attribution stays unknown.
        # This is deliberately conservative — a source key is propagated only
        # when the relationship is positively established, and the NEXT
        # heading is never assigned retrospectively to a preceding table.
        boundaries: list[tuple[int, int, str | None]] = []  # (page, order, source)
        sub_boundaries: list[tuple[int, int, str | None]] = []  # (page, order, sub)
        for order, section in enumerate(sections):
            title = section.get("title") or ""
            if not title:
                continue
            page_start = int(section.get("page_start") or 0)
            source = extract_source_key(title)
            sub_entity = extract_sub_entity(title)
            if source is not None:
                boundaries.append((page_start, order, source))
                sub_boundaries.append((page_start, order, None))
            elif _ENTERPRISE_TITLE_RE.search(normalize_label(title)):
                boundaries.append((page_start, order, None))  # block terminator
                sub_boundaries.append((page_start, order, None))
            elif sub_entity is not None:
                # A release point / operation opens a SUB-block inside the
                # current source block; the same strict-interior rule applies.
                sub_boundaries.append((page_start, order, sub_entity))
        boundaries.sort(key=lambda item: (item[0], item[1]))
        self._source_blocks: list[tuple[str | None, int, int | None]] = []
        for index, (page, _order, source) in enumerate(boundaries):
            next_page = boundaries[index + 1][0] if index + 1 < len(boundaries) else None
            self._source_blocks.append((source, page, next_page))
        sub_boundaries.sort(key=lambda item: (item[0], item[1]))
        self._sub_blocks: list[tuple[str | None, int, int | None]] = []
        for index, (page, _order, sub_entity) in enumerate(sub_boundaries):
            next_page = sub_boundaries[index + 1][0] if index + 1 < len(sub_boundaries) else None
            self._sub_blocks.append((sub_entity, page, next_page))

        # Pages positively covered by enterprise-inventory sections.
        self.enterprise_pages: set[int] = set()
        for section in sections:
            title = section.get("title") or ""
            if title and _ENTERPRISE_TITLE_RE.search(normalize_label(title)):
                start = int(section.get("page_start") or 0)
                end = int(section.get("page_end") or start)
                self.enterprise_pages.update(range(start, end + 1))

    def block_source(self, page: int | None) -> str | None:
        """Source of the block whose interior strictly contains ``page``."""
        if page is None:
            return None
        for source, start, next_page in self._source_blocks:
            if source is None:
                continue
            if start < page and (next_page is None or page < next_page):
                return source
        return None

    def block_sub_entity(self, page: int | None) -> str | None:
        """Release point / operation whose sub-block strictly contains
        ``page``; boundary pages stay unknown (no within-page ordering)."""
        if page is None:
            return None
        for sub_entity, start, next_page in self._sub_blocks:
            if sub_entity is None:
                continue
            if start < page and (next_page is None or page < next_page):
                return sub_entity
        return None

    def resolve_facility(
        self, page: int | None, explicit_source: str | None
    ) -> tuple[str, str | None]:
        """(aggregation_scope, source_key) — positively established or
        unknown. An explicit source (row/caption/sentence) always wins."""
        if explicit_source is not None:
            return "source", explicit_source
        block = self.block_source(page)
        enterprise = page is not None and page in self.enterprise_pages
        if block is not None and not enterprise:
            return "source", block
        if enterprise and block is None:
            return "enterprise", None
        return "unknown", None  # conflicting or absent signals

    # --- shared helpers ---------------------------------------------------------

    def _scan(self, text: str) -> ScanResult:
        return scan_text(text, self.doc_style, self.grouping_styles)

    def _suppress(
        self,
        reason: str,
        raw: str,
        *,
        source_kind: str | None = None,
        section_id: str | None = None,
        table_id: str | None = None,
        page: int | None = None,
        row: int | None = None,
        col: int | None = None,
        char_start: int | None = None,
        context: str = "",
        detected_unit: str | None = None,
        secondary_reasons: list[str] | None = None,
    ) -> None:
        counts = self.result.suppressed_counts
        counts[reason] = counts.get(reason, 0) + 1
        examples = self.result.suppressed_examples.setdefault(reason, [])
        if len(examples) < _SUPPRESSED_EXAMPLE_CAP and raw not in examples:
            examples.append(raw)
        # Deterministic stratified provenance samples: capped per
        # (reason, document) and per reason overall; iteration order is
        # deterministic (documents sorted, records in file order).
        if source_kind is None:
            return
        doc_key = (reason, self.document_id)
        reason_total = self.result.sample_counts.get(reason, 0)
        doc_total = self.result.sample_counts_by_doc.get(doc_key, 0)
        if reason_total >= _SAMPLES_PER_REASON or doc_total >= _SAMPLES_PER_REASON_DOC:
            return
        self.result.sample_counts[reason] = reason_total + 1
        self.result.sample_counts_by_doc[doc_key] = doc_total + 1
        sample_id = deterministic_id(
            "P3S",
            reason,
            self.document_id,
            table_id or section_id or "",
            str(row if row is not None else ""),
            str(col if col is not None else ""),
            str(char_start if char_start is not None else ""),
            raw,
        )
        self.result.suppressed_samples.append(
            P3SuppressedSample(
                sample_id=sample_id,
                reason=reason,
                project_id=self.project_id,
                document_id=self.document_id,
                source_kind=source_kind,  # type: ignore[arg-type]
                section_id=section_id,
                table_id=table_id,
                page_number=page,
                row=row,
                col=col,
                char_start=char_start,
                raw=raw[:80],
                context=context[:160],
                detected_unit=detected_unit,
                parser_state=(
                    f"style={self.doc_style or 'unknown'};"
                    f"grouping={','.join(sorted(self.grouping_styles)) or 'none'}"
                ),
                secondary_reasons=list(secondary_reasons or []),
                extraction_mode=("table" if source_kind == "table_cell" else "narrative"),
            )
        )

    def _build_mention(
        self,
        span: QuantitySpan,
        location: MentionLocation,
        raw_text: str,
        unit: UnitDef | None,
        unit_source: str,
        metric_group: str | None,
        metric_label: str | None,
        substance: str | None,
        source_key: str | None,
        period_key: str | None,
        qualifiers: frozenset[str],
        scope: str,
        extra_flags: list[str],
        aggregation_scope: str = "unknown",
        sub_entity: str | None = None,
    ) -> QuantMention:
        flags = sorted({*span.flags, *extra_flags})
        if unit is not None and unit.kind not in _SUBSTANCE_DIMENSION_KINDS:
            substance = None  # substance identity is meaningless for this dimension
        container = location.table_id or location.section_id or ""
        mention_id = deterministic_id(
            "P3Q",
            self.document_id,
            location.source_kind,
            container,
            str(location.row if location.row is not None else ""),
            str(location.col if location.col is not None else ""),
            str(location.char_start if location.char_start is not None else ""),
            span.raw,
        )
        dimension = dimension_key(unit) if unit else None
        factor = unit.factor if unit else None
        canonical_unit = canonical_unit_for(unit) if unit else None

        def _canon(value: Decimal | None) -> str | None:
            if value is None or unit is None:
                return None
            return decimal_str(convert_to_canonical(value, unit))

        return QuantMention(
            mention_id=mention_id,
            project_id=self.project_id,
            document_id=self.document_id,
            location=location,
            raw_text=raw_text,
            raw_number=span.raw,
            kind=span.kind,  # type: ignore[arg-type]
            modifier=span.modifier,  # type: ignore[arg-type]
            bound_inclusive=span.bound_inclusive,
            value=decimal_str(span.value) if span.value is not None else None,
            value_low=decimal_str(span.low) if span.low is not None else None,
            value_high=decimal_str(span.high) if span.high is not None else None,
            unit_raw=span.unit_raw if unit_source == "inline" else None,
            unit_canonical=unit.canonical if unit else None,
            unit_source=unit_source,  # type: ignore[arg-type]
            dimension=dimension,
            canonical_unit=canonical_unit,
            canonical_value=_canon(span.value),
            canonical_low=_canon(span.low),
            canonical_high=_canon(span.high),
            conversion_factor=decimal_str(factor) if factor is not None else None,
            display_quantum=decimal_str(span.display_quantum),
            canonical_quantum=(
                decimal_str(span.display_quantum * factor) if factor is not None else None
            ),
            metric_group=metric_group,
            metric_label=metric_label,
            substance=substance,
            source_key=source_key,
            period_key=period_key,
            qualifiers=sorted(qualifiers),
            scope=scope,  # type: ignore[arg-type]
            aggregation_scope=aggregation_scope,  # type: ignore[arg-type]
            sub_entity=sub_entity,
            extraction_confidence=_mention_confidence(flags),
            flags=flags,
        )

    # --- sections ---------------------------------------------------------------

    def extract_sections(self) -> None:
        for section in self.sections:
            text = section.get("text") or ""
            if not text.strip():
                continue
            section_id = str(section["section_id"])
            title = section.get("title")
            page_start = section.get("page_start")
            page_end = section.get("page_end")
            ocr_source = any(
                page in self.ocr_pages
                for page in range(int(page_start or 0), int(page_end or 0) + 1)
            ) or bool(section.get("provenance", {}).get("ocr_used"))

            scan = self._scan(text)
            for item in scan.suppressed:
                self._suppress(
                    item.reason,
                    item.raw,
                    source_kind="section_text",
                    section_id=section_id,
                    page=int(page_start) if page_start else None,
                    char_start=item.start,
                    context=scan.text[max(0, item.start - 40) : item.start + 60],
                )

            triple_spans = self._collect_percent_triples(
                scan.text, section_id, page_start, ocr_source, title
            )

            for span in scan.spans:
                if any(s <= span.start < e for s, e in triple_spans):
                    continue  # serialized through the triple pathway
                if span.unit is None:
                    self._suppress(
                        "narrative_unitless",
                        span.raw,
                        source_kind="section_text",
                        section_id=section_id,
                        page=int(page_start) if page_start else None,
                        char_start=span.start,
                        context=scan.text[max(0, span.start - 40) : span.end + 40],
                    )
                    continue
                window = scan.text[max(0, span.start - _CONTEXT_BEFORE) : span.end + _CONTEXT_AFTER]
                sentence = _sentence_window(scan.text, span.start, span.end)
                raw_text = scan.text[
                    max(0, span.start - _EVIDENCE_BEFORE) : span.end + _EVIDENCE_AFTER
                ].strip()
                flags: list[str] = []
                if ocr_source:
                    flags.append("ocr_source")
                metric_group = classify_metric(window)
                if metric_group is None and title:
                    metric_group = classify_metric(title)
                    if metric_group is not None:
                        flags.append("context_from_section_title")
                substance = extract_substance(sentence)
                if substance is None and title:
                    substance = extract_substance(title)
                    if substance is not None and "context_from_section_title" not in flags:
                        flags.append("context_from_section_title")
                qualifiers = extract_qualifiers(sentence)
                period_key = extract_period(sentence) or (extract_period(title) if title else None)
                source_key = extract_source_key(sentence)
                if source_key is None and title:
                    source_key = extract_source_key(title)
                page_int = int(page_start) if page_start else None
                aggregation_scope, resolved_source = self.resolve_facility(page_int, source_key)
                if (
                    title
                    and aggregation_scope == "unknown"
                    and _ENTERPRISE_TITLE_RE.search(normalize_label(title))
                ):
                    aggregation_scope = "enterprise"
                source_key = resolved_source
                sub_entity = extract_sub_entity(title) if title else None
                if sub_entity is None and aggregation_scope == "source":
                    sub_entity = self.block_sub_entity(page_int)
                location = MentionLocation(
                    source_kind="section_text",
                    section_id=section_id,
                    section_title=title,
                    page_number=int(page_start) if page_start else None,
                    char_start=span.start,
                    char_end=span.end,
                )
                # Narrative scope: substance identity dominates — a claim about
                # one substance is enterprise-level regardless of «итого»
                # phrasing. Total markers matter only for substance-less sums.
                near = normalize_label(window[-80:])
                scope = (
                    "total"
                    if substance is None
                    and any(
                        token in near
                        for token in ("итого", "всего", "суммарн", "в целом", "барлығы")
                    )
                    else "item"
                )
                mention = self._build_mention(
                    span,
                    location,
                    raw_text,
                    span.unit,
                    "inline",
                    metric_group,
                    normalize_label(sentence[-100:]) or None,
                    substance,
                    source_key,
                    period_key,
                    qualifiers,
                    scope,
                    flags,
                    aggregation_scope=aggregation_scope,
                    sub_entity=sub_entity,
                )
                self.result.mentions.append(mention)

    def _collect_percent_triples(
        self,
        normalized_text: str,
        section_id: str,
        page_start: int | None,
        ocr_source: bool,
        title: str | None,
    ) -> list[tuple[int, int]]:
        """Emit mentions + a PercentTriple for every explicit «N из M (P%)»."""
        spans: list[tuple[int, int]] = []
        for match in _PERCENT_TRIPLE_RE.finditer(normalized_text):
            spans.append((match.start(), match.end()))
            values: list[Decimal] = []
            quanta: list[Decimal] = []
            parseable = True
            for group in (1, 2, 3):
                raw = match.group(group).replace(" ", "")
                try:
                    value = Decimal(raw.replace(",", "."))
                except ArithmeticError:
                    parseable = False
                    break
                frac = re.search(r"[.,](\d+)$", raw)
                values.append(value)
                quanta.append(Decimal(1).scaleb(-len(frac.group(1))) if frac else Decimal(1))
            if not parseable or values[1] == 0:
                continue
            quote = normalized_text[max(0, match.start() - 40) : match.end() + 20].strip()
            mention_ids: list[str] = []
            for group in range(1, 4):
                flags = ["percent_triple"]
                if ocr_source:
                    flags.append("ocr_source")
                if group < 3:
                    flags.append("unitless")
                span = QuantitySpan(
                    start=match.start(group),
                    end=match.end(group),
                    raw=match.group(group),
                    kind="scalar",
                    modifier="none",
                    bound_inclusive=None,
                    value=values[group - 1],
                    low=None,
                    high=None,
                    display_quantum=quanta[group - 1],
                    unit_raw="%" if group == 3 else None,
                    unit=lookup_unit("%") if group == 3 else None,
                    flags=tuple(flags),
                )
                location = MentionLocation(
                    source_kind="section_text",
                    section_id=section_id,
                    section_title=title,
                    page_number=int(page_start) if page_start else None,
                    char_start=span.start,
                    char_end=span.end,
                )
                mention = self._build_mention(
                    span,
                    location,
                    quote,
                    span.unit,
                    "inline" if group == 3 else "none",
                    None,
                    None,
                    None,
                    None,
                    None,
                    frozenset(),
                    "item",
                    [],
                )
                mention_ids.append(mention.mention_id)
                self.result.mentions.append(mention)
            self.result.percent_triples.append(
                PercentTriple(
                    project_id=self.project_id,
                    document_id=self.document_id,
                    section_id=section_id,
                    page_number=int(page_start) if page_start else None,
                    numerator=values[0],
                    denominator=values[1],
                    percent=values[2],
                    percent_quantum=quanta[2],
                    quote=quote,
                    mention_ids=(mention_ids[0], mention_ids[1], mention_ids[2]),
                    ocr_source=ocr_source,
                )
            )
        return spans

    # --- tables ------------------------------------------------------------------

    def extract_tables(self) -> None:
        for table in self.tables:
            self._extract_table(table)

    def _header_rows(self, cells: list[list[str]]) -> tuple[int, bool]:
        """(header row count, header is only a column-index row / absent)."""
        from dalel.pillars.quantitative_consistency.config import MAX_HEADER_ROWS

        header_end = 0
        descriptive_rows = 0
        for row_idx in range(min(MAX_HEADER_ROWS, len(cells))):
            row = cells[row_idx]
            numeric_cells = 0
            integer_values: list[int] = []
            non_empty = 0
            for cell in row:
                stripped = cell.strip()
                if not stripped:
                    continue
                non_empty += 1
                scan = self._scan(stripped)
                if len(scan.spans) == 1 and scan.spans[0].kind == "scalar":
                    span = scan.spans[0]
                    if span.raw.strip() == stripped:
                        numeric_cells += 1
                        if span.value is not None and span.value == span.value.to_integral_value():
                            integer_values.append(int(span.value))
            if non_empty == 0 or numeric_cells == 0:
                header_end = row_idx + 1
                if non_empty:
                    descriptive_rows += 1
                continue
            if (
                numeric_cells == non_empty
                and len(integer_values) >= 3
                and integer_values
                == list(range(integer_values[0], integer_values[0] + len(integer_values)))
            ):
                header_end = row_idx + 1  # column-index row «1 2 3 4 …»
                continue
            break
        return header_end, descriptive_rows == 0

    def _extract_table(self, table: dict[str, Any]) -> None:
        cells: list[list[str]] = table["cells"]
        table_id = str(table["table_id"])
        page_number = table.get("page_number")
        caption = table.get("caption")
        ocr_source = bool(table.get("provenance", {}).get("ocr_used")) or (
            page_number is not None and int(page_number) in self.ocr_pages
        )
        num_cols = max((len(row) for row in cells), default=0)
        header_end, header_index_only = self._header_rows(cells)

        cols: list[ColInfo] = []
        for col in range(num_cols):
            header_parts: list[str] = []
            for row_idx in range(header_end):
                if col < len(cells[row_idx]):
                    cell = cells[row_idx][col].strip()
                    if cell and cell not in header_parts:
                        header_parts.append(cell)
            header = " ".join(header_parts)
            header_norm = normalize_label(header)
            unit = find_unit_in_label(header) if header else None
            if (
                unit is not None
                and unit.kind == "percent_points"
                and _ITEM_NUMBER_HEADER_RE.search(header_norm)
            ):
                unit = None  # «№ п.п.» names row numbers, not percentage points
            # A column whose header names an identifier role (code, class,
            # «Год достижения НДВ», row numbers …) holds identifiers, not
            # quantities — UNLESS a unit is declared in the header («т/год»
            # contains the word «год» but is a quantity column).
            is_identifier = unit is None and bool(_NON_QUANTITY_HEADER_RE.search(header_norm))
            summable = bool(header) and not is_identifier
            if unit is not None and unit.kind in ("concentration", "concentration_normal"):
                summable = False
            cols.append(
                ColInfo(
                    index=col,
                    header=header,
                    unit=unit,
                    summable=summable,
                    is_total_col=bool(_TOTAL_HEADER_RE.search(header_norm)),
                    is_share_col=bool(_SHARE_LABEL_RE.search(header_norm)),
                    period_key=extract_period(header),
                    is_identifier=is_identifier,
                )
            )

        code_cols = [c.index for c in cols if _CODE_HEADER_RE.search(normalize_label(c.header))]
        source_cols = [c.index for c in cols if _SOURCE_HEADER_RE.search(normalize_label(c.header))]

        # Per-source detail tables carry their source in the caption, in an
        # enclosing source BLOCK (strictly interior pages only), or continue
        # the previous table across a page break.
        caption_source = extract_source_key(caption) if caption else None
        table_scope, table_source = self.resolve_facility(
            int(page_number) if page_number is not None else None, caption_source
        )
        table_sub_entity = extract_sub_entity(caption) if caption else None
        if table_sub_entity is None and table_scope == "source":
            table_sub_entity = self.block_sub_entity(
                int(page_number) if page_number is not None else None
            )
        if table_scope == "unknown" and header_index_only:
            # Positive continuation: an index-only fragment with the same
            # column count as the immediately preceding table on the same or
            # previous page continues that table.
            previous = self._previous_table_attribution
            if (
                previous is not None
                and page_number is not None
                and previous["num_cols"] == num_cols
                and int(page_number) - previous["page"] in (0, 1)
            ):
                table_scope = previous["scope"]
                table_source = previous["source"]
                table_sub_entity = previous["sub_entity"]
        self._previous_table_attribution = {
            "num_cols": num_cols,
            "page": int(page_number) if page_number is not None else -10,
            "scope": table_scope,
            "source": table_source,
            "sub_entity": table_sub_entity,
        }

        rows: list[RowInfo] = []
        for row_idx in range(len(cells)):
            if row_idx < header_end:
                rows.append(RowInfo(row_idx, None, False, False, False, None, None))
                continue
            row = cells[row_idx]
            non_empty = [c.strip() for c in row if c.strip()]
            is_divider = len(non_empty) >= 2 and len(set(non_empty)) == 1
            label: str | None = None
            for col in range(min(3, len(row))):
                candidate = row[col].strip()
                if not candidate:
                    continue
                scan = self._scan(candidate)
                pure_number = (
                    len(scan.spans) == 1 and scan.spans[0].raw.strip() == candidate
                ) or re.fullmatch(r"[\d.,\- ]+", candidate)
                if not pure_number:
                    label = candidate
                    break
            substance = None
            for code_col in code_cols:
                if code_col < len(row) and row[code_col].strip():
                    substance = substance_from_code(row[code_col].strip())
                    if substance:
                        break
            if substance is None and label:
                substance = extract_substance(label)
            source_key = None
            for source_col in source_cols:
                if source_col < len(row):
                    candidate = row[source_col].strip()
                    if candidate and _SOURCE_CODE_CELL_RE.fullmatch(candidate):
                        source_key = candidate
                        break
            if source_key is None and label:
                source_key = extract_source_key(label)
            if source_key is None:
                source_key = table_source
            value_cells = [
                cell.strip() for cell in row if cell.strip() and cell.strip() != (label or "")
            ]
            is_category = (
                label is not None
                and not is_divider
                and not is_subset_label(label)  # «в том числе:» is a marker
                and not is_total_label(label)
                and all(cell in ("-", "—", "–") for cell in value_cells)
            )
            rows.append(
                RowInfo(
                    index=row_idx,
                    label=label,
                    is_total=is_total_label(label) if label else False,
                    is_subset=is_subset_label(label) if label else False,
                    is_divider=is_divider,
                    substance=substance,
                    source_key=source_key,
                    is_category=is_category,
                    period_key=extract_period(label) if label else None,
                )
            )

        table_period = extract_period(caption) if caption else None
        table_metric = classify_metric(caption) if caption else None

        sheet_cells: dict[tuple[int, int], CellParse] = {}
        for row_idx in range(header_end, len(cells)):
            row_info = rows[row_idx]
            if row_info.is_divider:
                for col in range(len(cells[row_idx])):
                    sheet_cells[(row_idx, col)] = CellParse(status="text")
                continue
            for col in range(len(cells[row_idx])):
                raw_cell = cells[row_idx][col]
                stripped = raw_cell.strip()
                if not stripped:
                    sheet_cells[(row_idx, col)] = CellParse(status="empty")
                    continue
                if row_info.label is not None and stripped == row_info.label:
                    sheet_cells[(row_idx, col)] = CellParse(status="text")
                    continue
                col_info = cols[col] if col < len(cols) else None
                if col_info is not None and col_info.is_identifier:
                    self._suppress(
                        "identifier_column",
                        stripped,
                        source_kind="table_cell",
                        table_id=table_id,
                        page=int(page_number) if page_number is not None else None,
                        row=row_idx,
                        col=col,
                        context=f"{row_info.label or ''} | {col_info.header[:60]}",
                    )
                    sheet_cells[(row_idx, col)] = CellParse(status="text")
                    continue
                scan = self._scan(stripped)
                for item in scan.suppressed:
                    self._suppress(
                        item.reason,
                        item.raw,
                        source_kind="table_cell",
                        table_id=table_id,
                        page=int(page_number) if page_number is not None else None,
                        row=row_idx,
                        col=col,
                        char_start=item.start,
                        context=stripped[:120],
                    )
                if not scan.spans:
                    sheet_cells[(row_idx, col)] = CellParse(status="text")
                    continue
                multi = len(scan.spans) > 1
                cell_mention_id: str | None = None
                cell_value: Decimal | None = None
                cell_quantum: Decimal | None = None
                cell_ambiguous_mention_id: str | None = None
                for span in scan.spans:
                    unit = span.unit
                    unit_source = "inline"
                    extra_flags: list[str] = []
                    if unit is None and col_info is not None and col_info.unit is not None:
                        unit = col_info.unit
                        unit_source = "column_header"
                        extra_flags.append("column_header_unit")
                    if unit is None:
                        unit_source = "none"
                        extra_flags.append("unitless")
                    if multi:
                        extra_flags.append("multi_number_cell")
                    if ocr_source:
                        extra_flags.append("ocr_source")
                    header_label = col_info.header if col_info else ""
                    context_label = " ".join(
                        part for part in (row_info.label, header_label, caption) if part
                    )
                    metric_group = (
                        classify_metric(header_label)
                        or classify_metric(row_info.label or "")
                        or table_metric
                    )
                    qualifiers = extract_qualifiers(header_label) | extract_qualifiers(
                        row_info.label or ""
                    )
                    period_key = (
                        (col_info.period_key if col_info else None)
                        or extract_period(row_info.label or "")
                        or table_period
                    )
                    scope = (
                        "total"
                        if row_info.is_total or (col_info is not None and col_info.is_total_col)
                        else "item"
                    )
                    location = MentionLocation(
                        source_kind="table_cell",
                        table_id=table_id,
                        row=row_idx,
                        col=col,
                        page_number=int(page_number) if page_number is not None else None,
                        char_start=span.start,
                        char_end=span.end,
                    )
                    raw_text = stripped if len(stripped) <= 120 else stripped[:120]
                    if row_info.label:
                        raw_text = f"{row_info.label} | {raw_text}"[:160]
                    row_scope = "source" if row_info.source_key is not None else table_scope
                    mention = self._build_mention(
                        span,
                        location,
                        raw_text,
                        unit,
                        unit_source,
                        metric_group,
                        normalize_label(context_label) or None,
                        row_info.substance,
                        row_info.source_key,
                        period_key,
                        qualifiers,
                        scope,
                        extra_flags,
                        aggregation_scope=row_scope,
                        sub_entity=table_sub_entity,
                    )
                    self.result.mentions.append(mention)
                    # A cell value feeds aggregation sums only when it is a
                    # single unambiguous scalar whose unit does not contradict
                    # the column unit; ambiguous «1,234»-style readings would
                    # silently corrupt totals by ×1000.
                    trusted = (
                        not multi
                        and span.kind == "scalar"
                        and span.value is not None
                        and "ambiguous_decimal_grouping" not in span.flags
                        and (
                            span.unit is None
                            or col_info is None
                            or col_info.unit is None
                            or span.unit == col_info.unit
                        )
                    )
                    if trusted:
                        cell_mention_id = mention.mention_id
                        cell_value = span.value
                        cell_quantum = span.display_quantum
                    elif "ambiguous_decimal_grouping" in span.flags and not multi:
                        cell_ambiguous_mention_id = mention.mention_id
                if multi:
                    sheet_cells[(row_idx, col)] = CellParse(status="multi")
                elif (
                    len(scan.spans) == 1
                    and scan.spans[0].kind == "scalar"
                    and scan.spans[0].value is not None
                    and "ambiguous_decimal_grouping" in scan.spans[0].flags
                ):
                    # Unresolved «1,234»-style cell: untrusted for sums, but
                    # its decimal reading is kept for contextual resolution.
                    sheet_cells[(row_idx, col)] = CellParse(
                        status="ambiguous",
                        value=scan.spans[0].value,
                        quantum=scan.spans[0].display_quantum,
                        mention_id=cell_ambiguous_mention_id,
                    )
                elif cell_value is not None:
                    sheet_cells[(row_idx, col)] = CellParse(
                        status="single",
                        value=cell_value,
                        quantum=cell_quantum,
                        mention_id=cell_mention_id,
                    )
                else:
                    sheet_cells[(row_idx, col)] = CellParse(status="text")

        fingerprint = hashlib.sha256(
            json.dumps(
                [[normalize_label(cell) for cell in row] for row in cells],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()[:16]

        self.result.sheets.append(
            TableSheet(
                table_id=table_id,
                project_id=self.project_id,
                document_id=self.document_id,
                page_number=int(page_number) if page_number is not None else None,
                caption=caption,
                header_rows=header_end,
                rows=rows,
                cols=cols,
                cells=sheet_cells,
                ocr_source=ocr_source,
                header_index_only=header_index_only,
                fingerprint=fingerprint,
                doc_style=self.doc_style,
                grouping_styles=tuple(sorted(self.grouping_styles)),
            )
        )


def _flag_table_echoes(result: ExtractionResult) -> None:
    """Narrative numbers equal to a table value in the same document are
    possibly the SAME physical table flattened into section text."""
    table_values: dict[tuple[str, str], set[str]] = {}
    for mention in result.mentions:
        if mention.location.source_kind == "table_cell" and mention.canonical_value:
            key = (mention.document_id, mention.canonical_value)
            table_values.setdefault(key, set()).add(mention.mention_id)
    updated: list[QuantMention] = []
    for mention in result.mentions:
        if (
            mention.location.source_kind == "section_text"
            and mention.canonical_value
            and (mention.document_id, mention.canonical_value) in table_values
        ):
            flags = sorted({*mention.flags, "possible_table_echo"})
            mention = mention.model_copy(
                update={"flags": flags, "extraction_confidence": _mention_confidence(flags)}
            )
        updated.append(mention)
    result.mentions = updated


def extract_mentions(
    documents: list[dict[str, Any]],
    sections_by_document: dict[str, list[dict[str, Any]]],
    tables_by_document: dict[str, list[dict[str, Any]]],
    pages_by_document: dict[str, list[dict[str, Any]]],
) -> ExtractionResult:
    """Extract all quantitative mentions for the given curated documents."""
    result = ExtractionResult()
    for document in sorted(documents, key=lambda d: str(d["document_id"])):
        document_id = str(document["document_id"])
        extractor = _DocumentExtractor(
            document,
            sections_by_document.get(document_id, []),
            tables_by_document.get(document_id, []),
            pages_by_document.get(document_id, []),
            result,
        )
        extractor.extract_sections()
        extractor.extract_tables()
    _flag_table_echoes(result)
    result.mentions.sort(
        key=lambda m: (
            m.project_id,
            m.document_id,
            m.location.source_kind,
            m.location.table_id or m.location.section_id or "",
            m.location.row if m.location.row is not None else -1,
            m.location.col if m.location.col is not None else -1,
            m.location.char_start if m.location.char_start is not None else -1,
            m.mention_id,
        )
    )
    return result
