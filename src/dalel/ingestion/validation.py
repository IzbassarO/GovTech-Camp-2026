"""Manifest loading and validation.

Import-light: this module powers ``dalel validate-manifest`` and must never
pull in Docling or any OCR engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from dalel.config import ALLOWED_LABEL_TIMINGS
from dalel.ingestion.hashing import sha256_file
from dalel.schemas.manifest import ManifestProject


class ManifestError(Exception):
    """The manifest is unreadable or structurally invalid."""


@dataclass
class ManifestValidationResult:
    projects: list[ManifestProject] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def document_count(self) -> int:
        return sum(len(p.documents) for p in self.projects)


def load_manifest(manifest_path: Path) -> list[ManifestProject]:
    """Load and schema-validate ``projects.jsonl``.

    Raises ``ManifestError`` on unreadable files, invalid JSON lines or
    schema violations. Unknown extra fields are preserved by the models.
    """
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest does not exist: {manifest_path}") from exc
    except UnicodeDecodeError as exc:
        raise ManifestError(f"manifest is not valid UTF-8: {exc}") from exc

    projects: list[ManifestProject] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            projects.append(ManifestProject.model_validate_json(line))
        except ValidationError as exc:
            raise ManifestError(f"manifest line {line_number} is invalid: {exc}") from exc
    if not projects:
        raise ManifestError(f"manifest contains no project records: {manifest_path}")
    return projects


def validate_manifest(
    manifest_path: Path,
    repo_root: Path,
    check_hashes: bool = True,
) -> ManifestValidationResult:
    """Validate manifest consistency against the filesystem.

    Checks: schema validity, duplicate project/document ids, duplicate local
    paths, path safety (inside the repository), file existence, leakage-boundary
    consistency and (optionally) SHA-256 equality with the physical files.
    """
    result = ManifestValidationResult()
    try:
        result.projects = load_manifest(manifest_path)
    except ManifestError as exc:
        result.errors.append(str(exc))
        return result

    seen_projects: set[str] = set()
    seen_documents: set[str] = set()
    seen_paths: set[str] = set()

    def _id_is_path_safe(identifier: str) -> bool:
        return (
            bool(identifier)
            and not identifier.startswith(".")
            and not any(marker in identifier for marker in ("/", "\\", ".."))
        )

    for project in result.projects:
        if project.project_id in seen_projects:
            result.errors.append(f"duplicate project_id: {project.project_id}")
        seen_projects.add(project.project_id)

        if not _id_is_path_safe(project.project_id):
            result.errors.append(
                f"unsafe project_id (used as an output path component): {project.project_id!r}"
            )

        metadata_path = repo_root / project.source_metadata_path
        if not metadata_path.is_file():
            result.errors.append(
                f"{project.project_id}: source_metadata_path does not exist:"
                f" {project.source_metadata_path}"
            )

        for document in project.documents:
            context = f"{project.project_id}/{document.document_id}"

            if document.document_id in seen_documents:
                result.errors.append(f"duplicate document_id: {document.document_id}")
            seen_documents.add(document.document_id)

            if not _id_is_path_safe(document.document_id):
                result.errors.append(
                    f"{context}: unsafe document_id (used as an output path component)"
                )

            if document.local_path in seen_paths:
                result.errors.append(f"{context}: duplicate local_path: {document.local_path}")
            seen_paths.add(document.local_path)

            if Path(document.local_path).is_absolute():
                result.errors.append(f"{context}: absolute local_path is forbidden")
                continue
            local_path = (repo_root / document.local_path).resolve()
            try:
                local_path.relative_to(repo_root.resolve())
            except ValueError:
                result.errors.append(f"{context}: local_path escapes the repository")
                continue

            if document.label_timing is not None and (
                document.label_timing not in ALLOWED_LABEL_TIMINGS
            ):
                result.errors.append(f"{context}: invalid label_timing {document.label_timing!r}")

            # Leakage-boundary consistency mirrors scripts/validate_dataset_foundation.py.
            if document.role == "label_source" and document.use_as_model_feature:
                result.errors.append(f"{context}: label_source must not be a model feature")
            if document.label_timing == "post_review" and document.use_as_model_feature:
                result.errors.append(f"{context}: post_review document must not be a model feature")
            if document.role == "model_input" and (
                not document.use_as_model_feature or document.label_timing != "pre_review"
            ):
                result.errors.append(f"{context}: model_input must be a pre_review model feature")
            if (
                document.role in {"auxiliary", "auxiliary_archive"}
                and document.use_as_model_feature
            ):
                result.errors.append(f"{context}: auxiliary document must not be a model feature")

            if not local_path.is_file():
                result.errors.append(f"{context}: file does not exist: {document.local_path}")
                continue

            if check_hashes:
                actual = sha256_file(local_path)
                if actual != document.sha256:
                    result.errors.append(
                        f"{context}: SHA-256 mismatch for {document.local_path}"
                        f" (manifest {document.sha256[:12]}…, actual {actual[:12]}…)"
                    )

    return result


def find_document(
    projects: list[ManifestProject], document_id: str
) -> tuple[ManifestProject, int] | None:
    """Locate a document by id; returns (project, index in project.documents)."""
    for project in projects:
        for index, document in enumerate(project.documents):
            if document.document_id == document_id:
                return project, index
    return None
