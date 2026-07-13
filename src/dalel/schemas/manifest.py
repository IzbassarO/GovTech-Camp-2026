"""Schemas matching the actual canonical manifest ``data/manifests/projects.jsonl``.

The manifest is the source of truth produced by the dataset pre-flight audit.
Unknown fields must survive a read/re-serialize round trip, so both models
use ``extra="allow"``. Optional fields are never invented.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentType = Literal[
    "ndv",
    "pek",
    "puo",
    "ovvos",
    "roos",
    "action_plan",
    "nontechnical_summary",
    "explanatory_note",
    "working_project_note",
    "hearing_protocol",
    "motivated_refusal",
    "map",
    "photo",
    "appendix",
    "archive",
    "unknown",
]

Role = Literal["model_input", "label_source", "auxiliary", "auxiliary_archive"]

LabelTiming = Literal["pre_review", "post_review"]


class ManifestDocument(BaseModel):
    """One document entry of a manifest project record."""

    model_config = ConfigDict(extra="allow")

    document_id: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    original_filename: str | None = None
    document_type: DocumentType
    role: Role
    use_as_model_feature: bool
    file_format: str = Field(min_length=1)
    sha256: str
    label_timing: LabelTiming | None = None
    notes: str | None = None

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex64(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
            raise ValueError("sha256 must be a 64-character hex string")
        return value.lower()

    @property
    def is_default_ingestible(self) -> bool:
        """Leakage boundary: the default ingestion allowlist."""
        return (
            self.role == "model_input"
            and self.use_as_model_feature is True
            and self.label_timing == "pre_review"
        )


class ManifestProject(BaseModel):
    """One line of ``projects.jsonl``."""

    model_config = ConfigDict(extra="allow")

    schema_version: str
    project_id: str = Field(min_length=1)
    source_metadata_path: str = Field(min_length=1)
    source_url: str | None = None
    downloaded_at: str | None = None
    region: str | None = None
    industry: str | None = None
    languages: list[str] = Field(default_factory=list)
    company_id: str | None = None
    developer_id: str | None = None
    documents: list[ManifestDocument] = Field(default_factory=list)
