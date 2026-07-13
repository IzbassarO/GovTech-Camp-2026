"""Table extraction record (one line of ``tables.jsonl``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dalel.schemas.evidence import Provenance


class TableRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    table_id: str
    page_number: int | None = None
    num_rows: int = 0
    num_cols: int = 0
    cells: list[list[str]] = Field(default_factory=list)
    caption: str | None = None
    # Parser-provided confidence only; never fabricated. ``confidence_source``
    # names the parser mechanism that produced the value.
    confidence: float | None = None
    confidence_source: str | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance
