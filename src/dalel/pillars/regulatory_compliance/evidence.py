"""Project evidence extraction from the curated dataset (read-only).

Evidence units are the ONLY material P2 reasons over: every assessment,
retrieval and LLM quote must reference an evidence_id, and quotes must be
exact substrings of the referenced evidence text. Base evidence covers
document presence, section headings and project context; bounded text
snippets are added deterministically when the NLI baseline matches a
requirement concept inside section text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dalel.pillars.regulatory_compliance.normalization import normalize_text
from dalel.pillars.regulatory_compliance.schemas import ProjectEvidence, deterministic_id


@dataclass
class ProjectEvidenceStore:
    """All evidence for one project, addressable by evidence_id."""

    project_id: str
    industry: str | None = None
    region: str | None = None
    document_types: dict[str, list[str]] = field(default_factory=dict)  # type -> doc ids
    evidence: dict[str, ProjectEvidence] = field(default_factory=dict)
    # (document_id, section_id) -> raw section text for snippet extraction.
    section_texts: dict[tuple[str, str], str] = field(default_factory=dict)
    section_pages: dict[tuple[str, str], int | None] = field(default_factory=dict)

    def add(self, item: ProjectEvidence) -> ProjectEvidence:
        return self.evidence.setdefault(item.evidence_id, item)

    def ordered(self) -> list[ProjectEvidence]:
        return sorted(self.evidence.values(), key=lambda e: e.evidence_id)


def _evidence_id(*parts: str) -> str:
    return deterministic_id("P2E", *parts)


def build_evidence_stores(
    projects: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    sections_by_document: dict[str, list[dict[str, Any]]],
) -> dict[str, ProjectEvidenceStore]:
    """Deterministic base evidence per project."""
    stores: dict[str, ProjectEvidenceStore] = {}
    for project in sorted(projects, key=lambda p: str(p["project_id"])):
        project_id = str(project["project_id"])
        store = ProjectEvidenceStore(
            project_id=project_id,
            industry=project.get("industry"),
            region=project.get("region"),
        )
        context_bits = [
            f"industry:{project.get('industry')}" if project.get("industry") else "",
            f"region:{project.get('region')}" if project.get("region") else "",
            f"languages:{','.join(project.get('languages') or [])}",
        ]
        context_text = normalize_text(" ".join(bit for bit in context_bits if bit))
        store.add(
            ProjectEvidence(
                evidence_id=_evidence_id(project_id, "context", context_text),
                project_id=project_id,
                kind="project_context",
                text=context_text,
            )
        )
        stores[project_id] = store

    for document in sorted(documents, key=lambda d: str(d["document_id"])):
        project_id = str(document["project_id"])
        maybe_store = stores.get(project_id)
        if maybe_store is None:
            continue
        store = maybe_store
        document_id = str(document["document_id"])
        document_type = str(document["document_type"])
        store.document_types.setdefault(document_type, []).append(document_id)
        store.add(
            ProjectEvidence(
                evidence_id=_evidence_id(project_id, "document", document_id),
                project_id=project_id,
                kind="document_present",
                document_id=document_id,
                document_type=document_type,
                text=normalize_text(f"документ типа {document_type}: {document_id}"),
            )
        )
        for section in sections_by_document.get(document_id, []):
            section_id = str(section["section_id"])
            page = section.get("page_start")
            page_number = int(page) if page is not None else None
            text = str(section.get("text") or "")
            if text.strip():
                store.section_texts[(document_id, section_id)] = text
                store.section_pages[(document_id, section_id)] = page_number
            title = section.get("title")
            if title is None or not str(title).strip():
                continue
            store.add(
                ProjectEvidence(
                    evidence_id=_evidence_id(project_id, "heading", document_id, section_id),
                    project_id=project_id,
                    kind="section_heading",
                    document_id=document_id,
                    document_type=str(document["document_type"]),
                    section_id=section_id,
                    page_number=page_number,
                    text=normalize_text(str(title)),
                )
            )
    return stores


def add_text_snippet(
    store: ProjectEvidenceStore,
    document_id: str,
    document_type: str | None,
    section_id: str,
    snippet: str,
) -> ProjectEvidence:
    """Register a bounded snippet as addressable evidence (deterministic id
    from content; duplicates collapse)."""
    return store.add(
        ProjectEvidence(
            evidence_id=_evidence_id(store.project_id, "snippet", document_id, section_id, snippet),
            project_id=store.project_id,
            kind="text_snippet",
            document_id=document_id,
            document_type=document_type,
            section_id=section_id,
            page_number=store.section_pages.get((document_id, section_id)),
            text=snippet,
        )
    )
