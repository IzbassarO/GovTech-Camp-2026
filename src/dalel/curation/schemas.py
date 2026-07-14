"""Pydantic models for curated dataset records.

Page/section/table/image records are verbatim copies of processed records
(their provenance is already complete) extended with curated fields
(``record_ref``, image materialization metadata). Every record is validated
against these production models during build AND during ``validate-curated``;
``schema.json`` is generated from the same models plus a deterministic
augmentation layer (see ``schema_contract.py``), so the distributed standalone
JSON Schema contract and the validation contract cannot drift apart.

Constraint conventions (mirrored into the distributed schema):
- identifiers are non-empty and never contain path separators or ``..``;
- SHA-256 fields match ``^[0-9a-f]{64}$``;
- feature-layer roles are locked to ``model_input`` / ``pre_review``;
- curated tables satisfy the table validity contract (dims >= 1, cells >= 1);
- materialized images carry positive sizes and dataset-relative paths.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dalel.schemas.document import SectionRecord
from dalel.schemas.image import ImageRecord
from dalel.schemas.manifest import DocumentType
from dalel.schemas.page import PageRecord
from dalel.schemas.table import TableRecord

SHA256_PATTERN = r"^[0-9a-f]{64}$"
# No path separators; non-empty. ``..`` exclusion is enforced by validators
# below and by a `not` clause in the distributed JSON Schema (Pydantic field
# patterns cannot use lookaheads).
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"
VERSION_PATTERN = r"^\d+\.\d+\.\d+$"
CURATED_IMAGE_PATH_PATTERN = r"^images/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$"

FINGERPRINT_ALGORITHM: Literal["dalel-input-inventory/v2"] = "dalel-input-inventory/v2"

INPUT_ROLES = (
    "canonical_manifest",
    "source_metadata",
    "processed_document",
    "processed_image",
    "label_source_table_gate",
    "weak_findings",
)


def _reject_traversal(value: str, field_name: str) -> str:
    """Reject absolute paths and ``..`` PATH SEGMENTS.

    Real dataset filenames legitimately contain consecutive dots (e.g.
    ``…гг..pdf``); only a whole ``..`` segment is traversal.
    """
    if value.startswith("/") or "\\" in value or any(part == ".." for part in value.split("/")):
        raise ValueError(f"{field_name} must be a safe relative path without '..' segments")
    return value


class RecordRef(BaseModel):
    """Reference to the original processed record (file + 1-based line)."""

    model_config = ConfigDict(extra="forbid")

    file: str = Field(min_length=1)
    line: int = Field(ge=1)

    @field_validator("file")
    @classmethod
    def _file_is_safe(cls, value: str) -> str:
        return _reject_traversal(value, "record_ref.file")


class CuratedProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, pattern=SAFE_ID_PATTERN)
    source_url: str | None = None
    region: str | None = None
    industry: str | None = None
    languages: list[str] = Field(default_factory=list)
    download_year: int | None = Field(default=None, ge=2000, le=2100)
    company_id: str | None = None
    developer_id: str | None = None
    model_input_document_ids: list[str] = Field(default_factory=list)
    label_source_document_ids: list[str] = Field(default_factory=list)


class CuratedDocument(BaseModel):
    """Feature-layer document record. Semantic contract: ONLY pre-review model
    inputs may appear in the curated feature layer."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, pattern=SAFE_ID_PATTERN)
    document_id: str = Field(min_length=1, pattern=SAFE_ID_PATTERN)
    document_type: DocumentType
    role: Literal["model_input"]
    file_format: Literal["pdf", "docx"]
    languages: list[str] = Field(default_factory=list)
    page_count: int | None = Field(default=None, ge=1)
    document_mode: Literal["digital", "scanned", "mixed", "docx_flow"] | None = None
    extraction_status: Literal["success", "partial"]
    parser_name: Literal["docling", "pymupdf", "python-docx"]
    parser_version: str | None = None
    ocr: dict[str, object]
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    source_url: str | None = None
    ingestion_schema_version: str = Field(pattern=VERSION_PATTERN)
    normalization_version: str = Field(pattern=VERSION_PATTERN)
    applied_normalizations: list[str] = Field(default_factory=list)
    normalization_warnings: list[str] = Field(default_factory=list)
    detected_table_items: int = Field(default=0, ge=0)
    serialized_table_count: int = Field(default=0, ge=0)
    skipped_empty_table_items: int = Field(default=0, ge=0)
    page_records: int = Field(default=0, ge=0)
    section_records: int = Field(default=0, ge=0)
    table_records: int = Field(default=0, ge=0)
    image_records: int = Field(default=0, ge=0)
    ingestion_warnings: list[str] = Field(default_factory=list)
    record_ref: RecordRef

    @field_validator("source_path")
    @classmethod
    def _source_path_is_safe(cls, value: str) -> str:
        return _reject_traversal(value, "source_path")


class CuratedPageRecord(PageRecord):
    """Processed page record + curated record reference."""

    record_ref: RecordRef


class CuratedSectionRecord(SectionRecord):
    """Processed section record + curated record reference."""

    record_ref: RecordRef


class CuratedTableRecord(TableRecord):
    """Processed table record + curated record reference.

    Field-level contract (mirrored in the distributed schema): positive
    dimensions and a non-empty grid; the inherited model validator adds the
    at-least-one-non-blank-cell rule.
    """

    num_rows: int = Field(ge=1)
    num_cols: int = Field(ge=1)
    cells: list[list[str]] = Field(min_length=1)
    record_ref: RecordRef


class CuratedImageRecord(ImageRecord):
    """Processed image record + curated materialization metadata.

    Coupling contract: whenever the processed record carries image bytes
    (``image_path`` is not null), the curated fields must pin the physical
    copy inside the dataset (path, SHA-256, positive size).
    """

    record_ref: RecordRef
    source_image_path: str | None = None
    curated_image_path: str | None = Field(default=None, pattern=CURATED_IMAGE_PATH_PATTERN)
    image_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    image_size_bytes: int | None = Field(default=None, ge=1)

    @field_validator("source_image_path", "curated_image_path")
    @classmethod
    def _paths_are_safe(cls, value: str | None) -> str | None:
        if value is not None:
            _reject_traversal(value, "image path")
        return value

    @model_validator(mode="after")
    def _materialization_coupling(self) -> CuratedImageRecord:
        if self.image_path is not None:
            missing = [
                name
                for name in ("curated_image_path", "image_sha256", "image_size_bytes")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    "image record with bytes must pin its curated copy;"
                    f" missing: {', '.join(missing)}"
                )
        return self


class WeakFindingRecord(BaseModel):
    """Label-layer weak finding. Never a gold label; never a model feature."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1, pattern=SAFE_ID_PATTERN)
    project_id: str = Field(min_length=1, pattern=SAFE_ID_PATTERN)
    issue_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str
    severity: Literal["unknown", "info", "low", "medium", "high"]
    source_document_id: str | None = None
    source_document_path: str = Field(min_length=1)
    source_page: int | None = Field(default=None, ge=1)
    target_document_ids: list[str] = Field(default_factory=list)
    target_document_paths: list[str] = Field(default_factory=list)
    evidence_text: str | None = None
    confidence: Literal["weak"] = "weak"
    expert_verified: Literal[False] = False
    review_status: Literal["not_expert_verified"] = "not_expert_verified"
    annotation_quality: Literal["weak_supervision_candidate"] = "weak_supervision_candidate"
    record_ref: RecordRef

    @field_validator("source_document_path")
    @classmethod
    def _source_is_safe(cls, value: str) -> str:
        return _reject_traversal(value, "source_document_path")


class DocumentGroup(BaseModel):
    """Grouping unit for any future split. Minimum split unit = project."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, pattern=SAFE_ID_PATTERN)
    project_id: str = Field(min_length=1, pattern=SAFE_ID_PATTERN)
    region: str | None = None
    industry: str | None = None
    languages: list[str] = Field(default_factory=list)
    download_year: int | None = Field(default=None, ge=2000, le=2100)
    company_id: str | None = None
    developer_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)
    ingestion_schema_versions: list[str] = Field(default_factory=list)
    has_weak_findings: bool = False
    label_source_document_ids: list[str] = Field(default_factory=list)


class InputManifestEntry(BaseModel):
    """One upstream input actually consumed by the curated build."""

    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    input_role: Literal[
        "canonical_manifest",
        "source_metadata",
        "processed_document",
        "processed_image",
        "label_source_table_gate",
        "weak_findings",
    ]

    @field_validator("relative_path")
    @classmethod
    def _path_is_safe(cls, value: str) -> str:
        return _reject_traversal(value, "relative_path")


class BuildReportModel(BaseModel):
    """``build_report.json``. Deliberately timestamp-free: byte-idempotent
    builds derive identity from the explicit input inventory fingerprint."""

    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    curation_version: str = Field(pattern=VERSION_PATTERN)
    fingerprint_algorithm: Literal["dalel-input-inventory/v2"]
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    input_files_hashed: int = Field(ge=1)
    input_roles: dict[str, int]
    input_root: str = Field(min_length=1)
    manifest: str = Field(min_length=1)
    table_validation: dict[str, object]
    normalizations: list[dict[str, object]]
    counts: dict[str, int]
    images_materialized: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)
    status: Literal["success", "failed"]


class DatasetStatisticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    curation_version: str = Field(pattern=VERSION_PATTERN)
    counts: dict[str, int]
    by_document_type: dict[str, int]
    by_extraction_status: dict[str, int]
    by_ingestion_schema: dict[str, int]
    by_document_mode: dict[str, int]
    per_project: dict[str, dict[str, int]]
    languages: list[str]
    regions: list[str]
    industries: list[str]
    table_validation: dict[str, int]
    split_proposal: dict[str, object]
