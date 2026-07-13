"""Image extraction record (one line of ``images.jsonl``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dalel.schemas.evidence import Provenance


class ImageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    image_id: str
    page_number: int | None = None
    width_px: int | None = None
    height_px: int | None = None
    # Path relative to the document output directory, e.g. ``images/img_0001.png``.
    # ``null`` when the parser reported an image but its bytes were unavailable.
    image_path: str | None = None
    classification: str | None = None
    classification_source: str | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance
