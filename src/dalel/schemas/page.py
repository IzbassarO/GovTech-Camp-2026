"""Page-level extraction record (one line of ``pages.jsonl``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dalel.schemas.evidence import Provenance


class PageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    page_number: int = Field(ge=1)
    width: float | None = None
    height: float | None = None
    rotation: int | None = None
    text: str
    char_count: int
    ocr_applied: bool = False
    has_embedded_text: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance
