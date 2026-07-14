"""Table extraction record (one line of ``tables.jsonl``).

Validity contract: a serialized table record must describe an actual table —
positive dimensions, a non-empty grid and at least one cell with non-blank
content. Parser artifacts that fail this contract are filtered upstream and
turned into ``empty_table_item_skipped`` warnings; the model validator below is
the second line of defence against accidental serialization.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dalel.schemas.evidence import Provenance


def table_content_is_valid(num_rows: int, num_cols: int, cells: list[list[str]]) -> bool:
    """True only for a table with positive dimensions and real cell content."""
    if num_rows <= 0 or num_cols <= 0 or not cells:
        return False
    return any(cell.strip() for row in cells for cell in row)


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

    @model_validator(mode="after")
    def _reject_empty_table(self) -> TableRecord:
        if not table_content_is_valid(self.num_rows, self.num_cols, self.cells):
            raise ValueError(
                "invalid table record: requires num_rows > 0, num_cols > 0, a non-empty"
                " cells grid and at least one non-blank cell; empty parser table items"
                " must be skipped with an empty_table_item_skipped warning instead"
            )
        return self
