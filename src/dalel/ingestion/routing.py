"""Document selection (leakage boundary) and parser routing.

The manifest is an allowlist, never a suggestion: by default only
``role == model_input`` / ``use_as_model_feature == true`` /
``label_timing == pre_review`` documents are ingested. Label sources require
the explicit ``--include-label-sources`` flag and are written to a separate
output tree. Archives (RAR) are always registered as skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from dalel.schemas.manifest import ManifestDocument, ManifestProject


class ParserRoute(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    SKIP_ARCHIVE = "skip_archive"
    SKIP_UNSUPPORTED = "skip_unsupported"


class SkipReason(StrEnum):
    NOT_A_MODEL_INPUT = "excluded_by_leakage_boundary"
    ARCHIVE = "auxiliary_archive_never_ingested"
    UNSUPPORTED_FORMAT = "unsupported_file_format"


@dataclass
class SelectedDocument:
    project: ManifestProject
    document: ManifestDocument


@dataclass
class SkippedDocument:
    project: ManifestProject
    document: ManifestDocument
    reason: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class Selection:
    selected: list[SelectedDocument] = field(default_factory=list)
    skipped: list[SkippedDocument] = field(default_factory=list)


def route_for(document: ManifestDocument) -> ParserRoute:
    """Choose the parser route from manifest facts. Never guess from the
    filename and never rename: extensionless or archive formats rely on the
    audited ``file_format`` recorded in the manifest."""
    file_format = document.file_format.lower()
    if document.role == "auxiliary_archive" or file_format in {"rar", "zip", "7z"}:
        return ParserRoute.SKIP_ARCHIVE
    if file_format == "pdf":
        return ParserRoute.PDF
    if file_format == "docx":
        return ParserRoute.DOCX
    return ParserRoute.SKIP_UNSUPPORTED


def select_documents(
    projects: list[ManifestProject],
    project_id: str | None = None,
    document_id: str | None = None,
    include_label_sources: bool = False,
) -> Selection:
    """Apply the leakage boundary and explicit CLI filters.

    Every manifest document in scope lands either in ``selected`` or in
    ``skipped`` with a stated reason, so runs are fully accounted for.
    """
    selection = Selection()

    for project in projects:
        if project_id is not None and project.project_id != project_id:
            continue
        for document in project.documents:
            if document_id is not None and document.document_id != document_id:
                continue

            route = route_for(document)
            if route is ParserRoute.SKIP_ARCHIVE:
                selection.skipped.append(
                    SkippedDocument(
                        project=project,
                        document=document,
                        reason=SkipReason.ARCHIVE.value,
                        warnings=["auxiliary archive is never unpacked or used as a feature"],
                    )
                )
                continue

            if document.is_default_ingestible:
                if route is ParserRoute.SKIP_UNSUPPORTED:
                    selection.skipped.append(
                        SkippedDocument(
                            project=project,
                            document=document,
                            reason=SkipReason.UNSUPPORTED_FORMAT.value,
                            warnings=[
                                f"unsupported file_format {document.file_format!r};"
                                " file was not renamed or guessed"
                            ],
                        )
                    )
                else:
                    selection.selected.append(SelectedDocument(project, document))
                continue

            # Not a default-ingestible document: label source or auxiliary.
            if document.role == "label_source" and include_label_sources:
                if route is ParserRoute.SKIP_UNSUPPORTED:
                    selection.skipped.append(
                        SkippedDocument(
                            project=project,
                            document=document,
                            reason=SkipReason.UNSUPPORTED_FORMAT.value,
                            warnings=[
                                f"label-source file_format {document.file_format!r} is not"
                                " parseable; skipped with no rename or format guessing"
                            ],
                        )
                    )
                else:
                    selection.selected.append(SelectedDocument(project, document))
            else:
                selection.skipped.append(
                    SkippedDocument(
                        project=project,
                        document=document,
                        reason=SkipReason.NOT_A_MODEL_INPUT.value,
                        warnings=(
                            ["use --include-label-sources to parse this label source"]
                            if document.role == "label_source"
                            else []
                        ),
                    )
                )

    return selection
