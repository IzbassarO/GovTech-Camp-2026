"""Phase 0 configuration constants and path conventions.

This module must stay import-light: no Docling, no OCR, no model loading.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

INGESTION_SCHEMA_VERSION = "1.0.0"

# Document types confirmed by the dataset pre-flight audit. Do not shrink.
ALLOWED_DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
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
    }
)

ALLOWED_ROLES: frozenset[str] = frozenset(
    {
        "model_input",
        "label_source",
        "auxiliary",
        "auxiliary_archive",
    }
)

ALLOWED_LABEL_TIMINGS: frozenset[str] = frozenset({"pre_review", "post_review"})

# A page whose embedded text has fewer stripped characters than this is
# treated as lacking usable embedded text and becomes an OCR candidate.
MIN_USABLE_CHARS_PER_PAGE = 32

# Embedded images smaller than this (either dimension, px) are decorative
# artifacts (bullets, line fragments) and are not extracted.
MIN_IMAGE_DIMENSION_PX = 16

MODEL_INPUTS_DIRNAME = "model_inputs"
LABEL_SOURCES_DIRNAME = "label_sources"


class OcrMode(StrEnum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class ExtractionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    SKIPPED_CACHED = "skipped_cached"


def derive_repo_root(manifest_path: Path) -> Path:
    """Derive the repository root from a manifest path.

    The canonical layout is ``<root>/data/manifests/projects.jsonl``; manifest
    document paths are relative to ``<root>``. If the manifest does not follow
    that layout, fall back to the manifest's own directory.
    """
    resolved = manifest_path.resolve()
    parent = resolved.parent
    if parent.name == "manifests" and parent.parent.name == "data":
        return parent.parent.parent
    return parent


def processed_root(repo_root: Path) -> Path:
    return repo_root / "data" / "processed"


def output_root_for_role(repo_root: Path, role: str) -> Path:
    """Return the output root that keeps label sources apart from model inputs.

    Fails closed: only roles that are ever parsed have an output root.
    Auxiliary documents and archives are never written anywhere.
    """
    if role == "model_input":
        return processed_root(repo_root) / MODEL_INPUTS_DIRNAME
    if role == "label_source":
        return processed_root(repo_root) / LABEL_SOURCES_DIRNAME
    raise ValueError(f"role {role!r} has no output root; it must never be ingested")
