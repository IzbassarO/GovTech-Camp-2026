"""Pydantic v2 schemas for the Phase 0 ingestion layer."""

from dalel.schemas.document import DocumentRecord, OcrMetadata, SectionRecord
from dalel.schemas.evidence import BBox, Provenance
from dalel.schemas.image import ImageRecord
from dalel.schemas.manifest import ManifestDocument, ManifestProject
from dalel.schemas.page import PageRecord
from dalel.schemas.table import TableRecord

__all__ = [
    "BBox",
    "DocumentRecord",
    "ImageRecord",
    "ManifestDocument",
    "ManifestProject",
    "OcrMetadata",
    "PageRecord",
    "Provenance",
    "SectionRecord",
    "TableRecord",
]
