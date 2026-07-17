"""Cross-modal context assembly: captions, headings, page text, P3/P4 links.

Context is assembled ONLY from artifacts the pipeline can cite: curated page
text, curated section headings, accepted P4 entities and accepted P3
quantitative mentions. Every derived field keeps its source, and absent
context is recorded as a limitation instead of being invented.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dalel.pillars.multimodal_visual_evidence.config import (
    CAPTION_MIN_CHARS,
    CAPTION_PATTERNS,
    ENTITY_TERM_MAX_COUNT,
    ENTITY_TERM_MIN_CHARS,
    FIGURE_REFERENCE_PATTERN,
    PAGE_CONTEXT_SNIPPET_CHARS,
)

_CAPTION_RES = [re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in CAPTION_PATTERNS]
_FIGURE_RE = re.compile(FIGURE_REFERENCE_PATTERN, re.IGNORECASE)


@dataclass
class DocumentTextIndex:
    """Page text and section headings for one document."""

    page_text: dict[int, str] = field(default_factory=dict)
    # (page_start, page_end, title, section_id), ordered by section position
    sections: list[tuple[int, int, str | None, str]] = field(default_factory=list)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def build_text_index(dataset_dir: Path) -> dict[str, DocumentTextIndex]:
    """Index curated pages and sections by document."""
    index: dict[str, DocumentTextIndex] = {}
    for row in _read_jsonl(dataset_dir / "pages.jsonl"):
        provenance = row.get("provenance") or {}
        document_id = str(provenance.get("document_id") or "")
        page_number = row.get("page_number")
        if not document_id or not isinstance(page_number, int):
            continue
        index.setdefault(document_id, DocumentTextIndex()).page_text[page_number] = str(
            row.get("text") or ""
        )
    for row in _read_jsonl(dataset_dir / "sections.jsonl"):
        provenance = row.get("provenance") or {}
        document_id = str(provenance.get("document_id") or "")
        if not document_id:
            continue
        page_start = row.get("page_start")
        page_end = row.get("page_end")
        title = row.get("title")
        section_id = str(row.get("section_id") or "")
        if isinstance(page_start, int) and isinstance(page_end, int) and section_id:
            index.setdefault(document_id, DocumentTextIndex()).sections.append(
                (page_start, page_end, str(title) if title else None, section_id)
            )
    return index


def find_caption(page_text: str) -> str | None:
    """First explicit figure-style caption line on the page, if any."""
    for pattern in _CAPTION_RES:
        match = pattern.search(page_text)
        if match:
            caption = " ".join(match.group(1).split()).strip()
            if len(caption) >= CAPTION_MIN_CHARS:
                return caption
    return None


def find_figure_references(page_text: str) -> list[str]:
    """Distinct, ordered numbered visual references on a page (`рис. 3`, ...)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _FIGURE_RE.finditer(page_text):
        reference = " ".join(match.group(0).split()).casefold()
        if reference not in seen:
            seen.add(reference)
            ordered.append(reference)
    return ordered


def nearest_heading(
    index: DocumentTextIndex, page_number: int | None
) -> tuple[str | None, str | None]:
    """Titled section covering the page (last wins => most specific)."""
    if page_number is None:
        return None, None
    best: tuple[str | None, str | None] = (None, None)
    for page_start, page_end, title, section_id in index.sections:
        if page_start <= page_number <= page_end:
            best = (title, section_id) if title else (best[0], section_id)
    return best


def page_snippet(page_text: str) -> str | None:
    snippet = " ".join(page_text.split())[:PAGE_CONTEXT_SNIPPET_CHARS].strip()
    return snippet or None


# --- P4 entity linkage --------------------------------------------------------


def load_entity_terms(p4_dir: Path | None) -> dict[str, list[str]]:
    """Distinct lowercase entity surface terms per project from accepted P4.

    Only reasonably specific labels are kept (length filter) and the list is
    bounded and sorted for determinism.
    """
    if p4_dir is None:
        return {}
    terms: dict[str, set[str]] = {}
    for row in _read_jsonl(p4_dir / "entities.jsonl"):
        project_id = str(row.get("project_id") or "")
        if not project_id:
            continue
        if str(row.get("entity_type") or "") in {"project", "document"}:
            continue
        labels = [str(row.get("canonical_label") or "")]
        aliases = row.get("aliases")
        if isinstance(aliases, list):
            labels.extend(str(alias) for alias in aliases)
        for label in labels:
            cleaned = " ".join(label.split()).casefold().strip("«»\"'. ")
            if len(cleaned) >= ENTITY_TERM_MIN_CHARS:
                terms.setdefault(project_id, set()).add(cleaned)
    return {
        project_id: sorted(values)[:ENTITY_TERM_MAX_COUNT] for project_id, values in terms.items()
    }


def match_entity_terms(texts: list[str | None], terms: list[str]) -> list[str]:
    """Entity terms present in any of the given texts (sorted, distinct)."""
    haystacks = [text.casefold() for text in texts if text]
    if not haystacks:
        return []
    matched = {term for term in terms if any(term in haystack for haystack in haystacks)}
    return sorted(matched)


# --- P3 quantitative linkage --------------------------------------------------


def load_quant_page_counts(p3_dir: Path | None) -> dict[tuple[str, int], int]:
    """Count of accepted P3 quantitative mentions per (document_id, page)."""
    if p3_dir is None:
        return {}
    counts: dict[tuple[str, int], int] = {}
    path = p3_dir / "mentions.jsonl"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            document_id = str(row.get("document_id") or "")
            location = row.get("location") or {}
            page = location.get("page_number") if isinstance(location, dict) else None
            if document_id and isinstance(page, int):
                counts[(document_id, page)] = counts.get((document_id, page), 0) + 1
    return counts
