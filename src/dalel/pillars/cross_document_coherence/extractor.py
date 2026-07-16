"""Grounded entity-claim extraction from Curated Dataset v1 records.

Every claim is anchored to a verbatim substring of a real curated container
(a section's heading+text, a table cell, or an accepted project-metadata
field), so the validator can independently re-find the evidence. Extraction
uses deterministic lexicons and structured patterns only — no LLM, no fuzzy
matching, no embeddings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dalel.pillars.cross_document_coherence.config import (
    ACTIVITY_CATEGORY_MARKERS,
    CLAIM_CONFIDENCE,
    DESIGNER_MARKERS,
    IDENTITY_SECTION_WINDOW,
    OPERATOR_MARKERS,
    ROLE_MARKER_WINDOW_CHARS,
)
from dalel.pillars.cross_document_coherence.normalization import (
    collapse_whitespace,
    normalize_address,
    normalize_bin,
    normalize_org_name,
    normalize_period,
    normalize_region,
    normalize_text,
)
from dalel.pillars.cross_document_coherence.schemas import (
    ClaimProvenance,
    EntityClaim,
    deterministic_id,
)

# --- deterministic extraction patterns --------------------------------------

# Legal-form + guillemet/quoted organization name.
_ORG_RE = re.compile(
    r"(Товарищество с ограниченной ответственностью|Акционерное общество"
    r"|Индивидуальный предприниматель|ТОО|ОАО|ЗАО|ГКП|АО|ИП\s+КХ|ИП)"
    r"\s*[«\"„“]([^»\"“”„]{2,80})[»\"”“]",
    re.IGNORECASE,
)
# Kazakhstan BIN: the label «БИН» (Cyrillic) followed by exactly 12 digits.
_BIN_RE = re.compile(r"БИН[:\s]*?(\d{12})(?!\d)", re.IGNORECASE)
# Reporting period: an explicit period marker + YYYY–YYYY.
_PERIOD_RE = re.compile(
    r"(?:на|период|срок действия|на период)\s*(20\d\d)\s*(?:г\.?|год|гг\.?)?\s*"
    r"[-–—]\s*(20\d\d)",
    re.IGNORECASE,
)
# Administrative address: from an explicit address marker to end of clause.
_ADDRESS_RE = re.compile(
    r"(?:юридический адрес(?:\s+предприятия)?|адрес(?:\s+предприятия)?|"
    r"расположен\w*\s+по\s+адресу)[:\s]+([^\n.;]{6,90})",
    re.IGNORECASE,
)
# Structured emission-source heading: «Источник №0001. Дымовая труба ...».
_SOURCE_RE = re.compile(
    r"Источник\s*[№N]\s*(\d{3,5})\.?\s*([^\n]{0,80})",
    re.IGNORECASE,
)
# Production-object description in a design/summary cover line.
_OBJECT_RE = re.compile(
    r"(Производство|Строительство|Реконструкция|Модернизация|Эксплуатация)\s+"
    r"([^\n«»\"]{6,90})",
    re.IGNORECASE,
)
# EXPLICIT structured activity/category classification LABEL + value. Only an
# explicit label qualifies; ambiguous inline references are never extracted.
_CATEGORY_RE = re.compile(
    r"(?:" + "|".join(re.escape(m) for m in ACTIVITY_CATEGORY_MARKERS) + r")"
    r"\s*[:\-–]?\s*([^\n.,;]{1,40})",
    re.IGNORECASE,
)


def _exact_span(text: str, start: int, end: int) -> tuple[str, int, int]:
    """Return the EXACT original substring and its (start, end) so that
    ``text[start:end] == raw_value`` always holds (Blocker B invariant).

    Candidate discovery may run on the original text; this resolves the span
    verbatim — never on collapsed or truncated text.
    """
    return text[start:end], start, end


@dataclass
class ExtractionResult:
    claims: list[EntityClaim] = field(default_factory=list)
    # counters for metrics / honest reporting
    documents_scanned: int = 0
    sections_scanned: int = 0
    org_mentions: int = 0


def section_evidence_text(section: dict[str, Any]) -> str:
    """Canonical per-section text used for both extraction and validation:
    the heading (if any) followed by the body, so headings are groundable."""
    title = section.get("title")
    text = section.get("text") or ""
    if title:
        return f"{title}\n{text}"
    return text


def _role_for(text_cf: str, start: int) -> str:
    """Positively-marked organization role from the preceding window."""
    window = text_cf[max(0, start - ROLE_MARKER_WINDOW_CHARS) : start]
    if any(marker in window for marker in (m.casefold() for m in OPERATOR_MARKERS)):
        return "operator"
    if any(marker in window for marker in (m.casefold() for m in DESIGNER_MARKERS)):
        return "designer"
    return "unknown"


def _claim(
    project_id: str,
    entity_type: str,
    attribute: str,
    raw_value: str,
    normalized_value: str,
    provenance: ClaimProvenance,
    method: str,
    confidence: float,
    *,
    scope: str = "package",
    qualifiers: list[str] | None = None,
    flags: list[str] | None = None,
) -> EntityClaim:
    claim_id = deterministic_id(
        "P4C",
        project_id,
        provenance.document_id or "",
        entity_type,
        attribute,
        normalized_value,
        provenance.section_id or provenance.table_id or "meta",
        str(provenance.char_start if provenance.char_start is not None else ""),
    )
    return EntityClaim(
        claim_id=claim_id,
        project_id=project_id,
        candidate_entity_type=entity_type,
        attribute=attribute,
        raw_value=raw_value,
        normalized_value=normalized_value,
        provenance=provenance,
        extraction_method=method,
        confidence=confidence,
        scope=scope,
        qualifiers=sorted(qualifiers or []),
        quality_flags=sorted(flags or []),
    )


def _section_prov(
    document_id: str,
    document_type: str,
    section_id: str,
    page: int | None,
    start: int,
    end: int,
) -> ClaimProvenance:
    return ClaimProvenance(
        document_id=document_id,
        document_type=document_type,
        source_kind="section_text",
        section_id=section_id,
        page_number=page,
        char_start=start,
        char_end=end,
    )


def _ocr_flag(document: dict[str, Any], page: int | None) -> list[str]:
    ocr = document.get("ocr") or {}
    ocr_pages = set(ocr.get("ocr_pages") or [])
    if page is not None and page in ocr_pages:
        return ["ocr_source"]
    return []


def extract_claims(
    documents: list[dict[str, Any]],
    sections_by_document: dict[str, list[dict[str, Any]]],
    tables_by_document: dict[str, list[dict[str, Any]]],
    projects_by_id: dict[str, dict[str, Any]],
) -> ExtractionResult:
    result = ExtractionResult()

    # --- project-metadata claims (region, industry) --------------------------
    for project_id in sorted(projects_by_id):
        project = projects_by_id[project_id]
        region = project.get("region")
        if region:
            prov = ClaimProvenance(source_kind="project_metadata")
            result.claims.append(
                _claim(
                    project_id,
                    "administrative_location",
                    "region",
                    str(region),
                    normalize_region(str(region)),
                    prov,
                    "project_metadata_region",
                    CLAIM_CONFIDENCE["administrative_region"],
                )
            )
        industry = project.get("industry")
        if industry:
            prov = ClaimProvenance(source_kind="project_metadata")
            result.claims.append(
                _claim(
                    project_id,
                    "activity",
                    "industry",
                    str(industry),
                    normalize_text(str(industry)),
                    prov,
                    "project_metadata_industry",
                    CLAIM_CONFIDENCE["activity_industry"],
                )
            )

    # --- document-body claims ------------------------------------------------
    for document in sorted(documents, key=lambda d: str(d["document_id"])):
        document_id = str(document["document_id"])
        project_id = str(document["project_id"])
        document_type = str(document["document_type"])
        result.documents_scanned += 1
        sections = sections_by_document.get(document_id, [])
        # Identity statements live in the leading sections. Keep original order.
        for section in sections[:IDENTITY_SECTION_WINDOW]:
            result.sections_scanned += 1
            self_text = section_evidence_text(section)
            if not self_text.strip():
                continue
            text_cf = self_text.casefold()
            section_id = str(section.get("section_id"))
            page = section.get("page_start")
            flags = _ocr_flag(document, page)

            def _prov(
                start: int,
                end: int,
                _d: str = document_id,
                _dt: str = document_type,
                _s: str = section_id,
                _p: Any = page,
            ) -> ClaimProvenance:
                return _section_prov(_d, _dt, _s, _p, start, end)

            # organizations (+role, +legal form)
            for match in _ORG_RE.finditer(self_text):
                result.org_mentions += 1
                raw_value, start, end = _exact_span(self_text, match.start(), match.end())
                _canonical, normalized_key, legal_form = normalize_org_name(raw_value)
                if not normalized_key:
                    continue
                role = _role_for(text_cf, match.start())
                attribute = (
                    "operator_name"
                    if role == "operator"
                    else ("designer_name" if role == "designer" else "organization_name")
                )
                result.claims.append(
                    _claim(
                        project_id,
                        "organization",
                        attribute,
                        raw_value,
                        normalized_key,
                        _prov(start, end),
                        f"org_legal_form:{role}",
                        CLAIM_CONFIDENCE[attribute],
                        # Legal form is a MATERIAL identity attribute: it prevents
                        # unsafe cross-form merges (Blocker A).
                        qualifiers=[f"role:{role}", f"legal_form:{legal_form or 'none'}"],
                        flags=flags,
                    )
                )

            # explicit BIN identifiers (role from same-section operator context):
            # a BIN found in a section that also carries an operator marker is the
            # operator's identifier; otherwise its role stays unknown.
            section_has_operator = any(
                marker in text_cf for marker in (m.casefold() for m in OPERATOR_MARKERS)
            )
            for match in _BIN_RE.finditer(self_text):
                raw_value, start, end = _exact_span(self_text, match.start(1), match.end(1))
                bin_value = normalize_bin(raw_value)
                if bin_value is None:
                    continue
                role = "operator" if section_has_operator else "unknown"
                result.claims.append(
                    _claim(
                        project_id,
                        "organization",
                        "bin",
                        raw_value,
                        bin_value,
                        _prov(start, end),
                        "identifier_bin",
                        CLAIM_CONFIDENCE["identifier"],
                        qualifiers=[f"role:{role}"],
                        flags=flags,
                    )
                )

            # reporting periods
            for match in _PERIOD_RE.finditer(self_text):
                period = normalize_period(match.group(1), match.group(2))
                if period is None:
                    continue
                raw_value, start, end = _exact_span(self_text, match.start(), match.end())
                result.claims.append(
                    _claim(
                        project_id,
                        "reporting_period",
                        "reporting_period",
                        raw_value,
                        period,
                        _prov(start, end),
                        "reporting_period_marker",
                        CLAIM_CONFIDENCE["reporting_period"],
                        flags=flags,
                    )
                )

            # administrative addresses
            for match in _ADDRESS_RE.finditer(self_text):
                raw_value, start, end = _exact_span(self_text, match.start(1), match.end(1))
                if not raw_value.strip():
                    continue
                result.claims.append(
                    _claim(
                        project_id,
                        "administrative_location",
                        "address",
                        raw_value,
                        normalize_address(raw_value),
                        _prov(start, end),
                        "address_marker",
                        CLAIM_CONFIDENCE["administrative_address"],
                        flags=[*flags, "address_partial"],
                    )
                )

            # explicit structured activity/category classification (labeled only)
            for match in _CATEGORY_RE.finditer(self_text):
                raw_value, start, end = _exact_span(self_text, match.start(1), match.end(1))
                if not raw_value.strip():
                    continue
                result.claims.append(
                    _claim(
                        project_id,
                        "activity",
                        "category",
                        raw_value,
                        normalize_text(raw_value),
                        _prov(start, end),
                        "activity_category_label",
                        CLAIM_CONFIDENCE["activity_object"],
                        flags=flags,
                    )
                )

            # production-object / activity description (free text)
            for match in _OBJECT_RE.finditer(self_text):
                start = match.start()
                end = min(match.end(), start + 90)
                raw_value, start, end = _exact_span(self_text, start, end)
                result.claims.append(
                    _claim(
                        project_id,
                        "activity",
                        "object",
                        raw_value,
                        normalize_text(raw_value),
                        _prov(start, end),
                        "activity_object",
                        CLAIM_CONFIDENCE["activity_object"],
                        flags=flags,
                    )
                )

            # structured emission sources (facility components)
            for match in _SOURCE_RE.finditer(self_text):
                code = match.group(1)
                name = collapse_whitespace(match.group(2))
                label = f"№{code}" + (f" {name}" if name else "")
                start = match.start()
                end = min(match.end(), start + 90)
                raw_value, start, end = _exact_span(self_text, start, end)
                result.claims.append(
                    _claim(
                        project_id,
                        "emission_source",
                        "source_code",
                        raw_value,
                        f"{document_id}:{code}",
                        _prov(start, end),
                        "emission_source_heading",
                        CLAIM_CONFIDENCE["emission_source"],
                        scope="document",
                        qualifiers=[f"code:{code}", f"label:{label[:60]}"],
                        flags=flags,
                    )
                )

    # Deduplicate identical claims (same content-derived id) deterministically.
    unique: dict[str, EntityClaim] = {}
    for claim in result.claims:
        unique.setdefault(claim.claim_id, claim)
    result.claims = sorted(unique.values(), key=lambda c: (c.project_id, c.claim_id))
    return result
