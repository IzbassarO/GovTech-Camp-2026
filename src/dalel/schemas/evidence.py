"""Provenance primitives shared by every extracted object.

Rule: never invent coordinates. If a page number or bbox is genuinely
unavailable it must be ``null`` and the owning record must carry a warning.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BBox(BaseModel):
    """Bounding box in page coordinates, as reported by the parser."""

    model_config = ConfigDict(extra="forbid")

    l: float  # noqa: E741 - established bbox field name (left)
    t: float
    r: float
    b: float
    coord_origin: str = "TOPLEFT"


class Provenance(BaseModel):
    """Where an extracted object came from and how it was produced."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    document_id: str
    document_type: str
    role: str
    source_path: str
    source_sha256: str
    page_number: int | None = None
    bbox: BBox | None = None
    extraction_method: str
    parser_name: str
    parser_version: str | None = None
    ocr_used: bool = False
    created_at: str
