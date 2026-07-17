"""Secure, job-local P0 through Meta orchestration for live uploads."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

Progress = Callable[[str, int, str, dict[str, Any] | None], None]

SECTIONS = (
    "project_documents",
    "official_supporting_documents",
    "hearing_protocol",
    "procedural_publication_evidence",
    "visual_geographic_materials",
    "public_feedback_metadata",
)
FILE_SECTIONS = frozenset(SECTIONS[:-1])
MEDIA_TYPES = frozenset({"pdf", "docx", "zip", "rar", "jpg", "png"})
ARCHIVE_MEMBER_TYPES = frozenset({"pdf", "docx", "jpg", "png"})
CHUNK_BYTES = 1024 * 1024
DEFAULT_LIMITS = {
    "max_file_count": 20,
    "max_file_bytes": 50 * 1024 * 1024,
    "max_total_bytes": 200 * 1024 * 1024,
    "max_archive_files": 100,
    "max_archive_expanded_bytes": 250 * 1024 * 1024,
    "max_archive_ratio": 200,
}


class LiveProcessingError(RuntimeError):
    """Fatal failure with a path- and filename-free code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LiveProcessingCancelled(RuntimeError):
    """Cooperative cancellation requested by the job owner."""


@dataclass(frozen=True)
class DocumentPlan:
    document_id: str
    file_id: str
    section_id: str
    display_name: str
    internal_path: str
    media_type: str
    sha256: str
    document_type: str
    role: str


def _cancel(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise LiveProcessingCancelled


def _progress(
    callback: Progress | None,
    state: str,
    percent: int,
    operation: str,
    details: dict[str, Any] | None = None,
) -> None:
    if callback is not None:
        callback(state, percent, operation, details)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_in(workspace: Path, relative: str, boundary: Path) -> Path:
    part = Path(relative)
    if part.is_absolute() or any(item in {"", ".", ".."} for item in part.parts):
        raise LiveProcessingError("unsafe_internal_path")
    path = (workspace / part).resolve()
    try:
        path.relative_to(boundary.resolve())
    except ValueError as exc:
        raise LiveProcessingError("unsafe_internal_path") from exc
    return path


def _prefix(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(4096)


def _valid_docx(path: Path, limits: dict[str, int]) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            names = {item.filename for item in infos}
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                return False
            if len(infos) > limits["max_archive_files"]:
                return False
            expanded = 0
            normalized_names: set[str] = set()
            for info in infos:
                if _unsafe_archive_name(info.filename):
                    return False
                normalized = unicodedata.normalize(
                    "NFC", info.filename.replace("\\", "/")
                ).casefold()
                if normalized in normalized_names:
                    return False
                normalized_names.add(normalized)
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if stat.S_ISLNK(mode) or file_type not in {0, stat.S_IFREG}:
                    return False
                if info.flag_bits & 1 or info.file_size > limits["max_file_bytes"]:
                    return False
                expanded += info.file_size
                if expanded > limits["max_archive_expanded_bytes"]:
                    return False
                if (
                    info.file_size > 0
                    and info.file_size > max(1, info.compress_size) * limits["max_archive_ratio"]
                ):
                    return False
        return True
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return False


def _valid_magic(path: Path, media_type: str, limits: dict[str, int]) -> bool:
    try:
        prefix = _prefix(path)
    except OSError:
        return False
    if media_type == "pdf":
        return prefix.lstrip().startswith(b"%PDF-")
    if media_type == "png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "jpg":
        return prefix.startswith(b"\xff\xd8\xff")
    if media_type == "rar":
        return prefix.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
    if media_type == "zip":
        return prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    return media_type == "docx" and prefix.startswith(b"PK") and _valid_docx(path, limits)


def _load_request(workspace: Path) -> tuple[dict[str, Any], dict[str, int]]:
    try:
        request = json.loads((workspace / "request.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveProcessingError("invalid_job_request") from exc
    if not isinstance(request, dict) or request.get("mode") != "live_analysis":
        raise LiveProcessingError("invalid_job_request")
    for key in ("job_id", "project_id"):
        value = request.get(key)
        if (
            not isinstance(value, str)
            or not value
            or value.startswith(".")
            or not re.fullmatch(r"[A-Za-z0-9_-]+", value)
        ):
            raise LiveProcessingError("invalid_job_identifier")
    if not isinstance(request.get("files"), list):
        raise LiveProcessingError("invalid_file_inventory")
    raw_limits = request.get("limits")
    limits: dict[str, int] = {}
    for key, maximum in DEFAULT_LIMITS.items():
        value = raw_limits.get(key, maximum) if isinstance(raw_limits, dict) else maximum
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise LiveProcessingError("invalid_job_limits")
        limits[key] = min(value, maximum)
    return request, limits


def _validate_files(
    workspace: Path, request: dict[str, Any], limits: dict[str, int]
) -> list[dict[str, Any]]:
    files = request["files"]
    if len(files) > limits["max_file_count"]:
        raise LiveProcessingError("file_count_limit")
    input_root = workspace / "input"
    seen_ids: set[str] = set()
    canonical_by_hash: dict[str, str] = {}
    inventory: list[dict[str, Any]] = []
    total = 0
    for raw in files:
        if not isinstance(raw, dict):
            raise LiveProcessingError("invalid_file_inventory")
        file_id = raw.get("file_id")
        section = raw.get("section_id")
        media = str(raw.get("media_type") or "").lower()
        media = "jpg" if media == "jpeg" else media
        if (
            not isinstance(file_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id)
            or file_id in seen_ids
            or section not in FILE_SECTIONS
            or media not in MEDIA_TYPES
        ):
            raise LiveProcessingError("invalid_file_inventory")
        seen_ids.add(file_id)
        relative = raw.get("internal_path")
        if not isinstance(relative, str):
            raise LiveProcessingError("invalid_file_inventory")
        path = _path_in(workspace, relative, input_root)
        if path.is_symlink() or not path.is_file():
            raise LiveProcessingError("input_file_unavailable")
        size = path.stat().st_size
        if (
            not isinstance(raw.get("size_bytes"), int)
            or raw["size_bytes"] != size
            or size <= 0
            or size > limits["max_file_bytes"]
        ):
            raise LiveProcessingError("input_size_mismatch")
        total += size
        if total > limits["max_total_bytes"]:
            raise LiveProcessingError("total_upload_size_limit")
        digest = _hash_file(path)
        if str(raw.get("sha256") or "").lower() != digest:
            raise LiveProcessingError("input_hash_mismatch")
        if not _valid_magic(path, media, limits):
            raise LiveProcessingError("input_signature_mismatch")
        duplicate = canonical_by_hash.get(digest)
        if raw.get("duplicate_of") is not None and raw.get("duplicate_of") != duplicate:
            raise LiveProcessingError("invalid_duplicate_reference")
        if duplicate is None:
            canonical_by_hash[digest] = file_id
        inventory.append(
            {
                **raw,
                "file_id": file_id,
                "section_id": section,
                "media_type": media,
                "size_bytes": size,
                "sha256": digest,
                "duplicate_of": duplicate,
                "archive_status": (
                    "registered"
                    if media == "zip"
                    else "extraction_unsupported"
                    if media == "rar"
                    else "not_archive"
                ),
                "status": "duplicate" if duplicate else "accepted",
                "limitations": (
                    ["Exact duplicate; excluded from repeated parsing."] if duplicate else []
                ),
            }
        )
    return inventory


def _unsafe_archive_name(name: str) -> bool:
    portable = name.replace("\\", "/")
    path = PurePosixPath(portable)
    return (
        not portable
        or portable.startswith("/")
        or bool(re.match(r"^[A-Za-z]:", portable))
        or ".." in path.parts
        or "\x00" in portable
    )


def _extension(name: str) -> str:
    value = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return "jpg" if value == "jpeg" else value


def _display_name(value: str, fallback: str) -> str:
    name = PurePosixPath(value.replace("\\", "/")).name
    normalized = unicodedata.normalize("NFC", name)
    cleaned = "".join(
        " " if unicodedata.category(char).startswith("C") else char for char in normalized
    )
    return (re.sub(r"\s+", " ", cleaned).strip() or fallback)[:200]


def _extract_archives(
    workspace: Path,
    inventory: list[dict[str, Any]],
    limits: dict[str, int],
    cancelled: Callable[[], bool] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    expanded = list(inventory)
    canonical = {
        str(item["sha256"]): str(item["file_id"])
        for item in inventory
        if item.get("duplicate_of") is None
    }
    total_members = 0
    total_bytes = 0
    limitations: list[str] = []
    for parent in inventory:
        _cancel(cancelled)
        if parent["media_type"] == "rar":
            parent["limitations"].append(
                "RAR extraction is unavailable; contents were not analyzed."
            )
            limitations.append("RAR archives could not be extracted.")
            continue
        if parent["media_type"] != "zip" or parent.get("duplicate_of") is not None:
            continue
        path = _path_in(workspace, str(parent["internal_path"]), workspace / "input")
        children: list[dict[str, Any]] = []
        outputs: list[Path] = []
        failure: str | None = None
        try:
            with zipfile.ZipFile(path) as archive:
                normalized_names: set[str] = set()
                for info in archive.infolist():
                    _cancel(cancelled)
                    if info.is_dir():
                        continue
                    total_members += 1
                    if total_members > limits["max_archive_files"]:
                        raise LiveProcessingError("archive_file_limit")
                    if _unsafe_archive_name(info.filename):
                        raise LiveProcessingError("archive_path_traversal")
                    normalized = info.filename.replace("\\", "/").casefold()
                    if normalized in normalized_names:
                        raise LiveProcessingError("archive_duplicate_path")
                    normalized_names.add(normalized)
                    mode = info.external_attr >> 16
                    file_type = stat.S_IFMT(mode)
                    if stat.S_ISLNK(mode) or file_type not in {0, stat.S_IFREG}:
                        raise LiveProcessingError("archive_unsafe_entry")
                    if info.flag_bits & 1:
                        raise LiveProcessingError("archive_encrypted")
                    media = _extension(info.filename)
                    if media in {"zip", "rar", "7z"}:
                        raise LiveProcessingError("nested_archive_unsupported")
                    if media not in ARCHIVE_MEMBER_TYPES:
                        continue
                    out_dir = (
                        workspace
                        / "extracted"
                        / hashlib.sha256(str(parent["file_id"]).encode()).hexdigest()[:16]
                    )
                    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                    index = len(children) + 1
                    out = out_dir / f"member_{index:04d}.{media}"
                    digest = hashlib.sha256()
                    size = 0
                    try:
                        with archive.open(info) as source, out.open("xb") as target:
                            os.chmod(out, 0o600)
                            while chunk := source.read(CHUNK_BYTES):
                                size += len(chunk)
                                total_bytes += len(chunk)
                                if size > limits["max_file_bytes"]:
                                    raise LiveProcessingError("archive_entry_limit")
                                if total_bytes > limits["max_archive_expanded_bytes"]:
                                    raise LiveProcessingError("archive_expanded_size_limit")
                                if size > max(1, info.compress_size) * limits["max_archive_ratio"]:
                                    raise LiveProcessingError("archive_ratio_limit")
                                target.write(chunk)
                                digest.update(chunk)
                    except Exception:
                        out.unlink(missing_ok=True)
                        raise
                    if size <= 0 or size != info.file_size or not _valid_magic(out, media, limits):
                        out.unlink(missing_ok=True)
                        raise LiveProcessingError("archive_member_integrity")
                    outputs.append(out)
                    sha = digest.hexdigest()
                    duplicate = canonical.get(sha)
                    child_id = (
                        "LIVEARCHIVE__"
                        + hashlib.sha256(f"{parent['file_id']}|{index}|{sha}".encode()).hexdigest()[
                            :20
                        ]
                    )
                    if duplicate is None:
                        canonical[sha] = child_id
                    children.append(
                        {
                            "file_id": child_id,
                            "section_id": parent["section_id"],
                            "display_filename": _display_name(
                                info.filename, f"archive-member-{index}"
                            ),
                            "media_type": media,
                            "size_bytes": size,
                            "sha256": sha,
                            "duplicate_of": duplicate,
                            "archive_status": "not_archive",
                            "status": "duplicate" if duplicate else "accepted",
                            "limitations": (
                                ["Exact duplicate; excluded from repeated parsing."]
                                if duplicate
                                else []
                            ),
                            "internal_path": out.relative_to(workspace).as_posix(),
                            "source_origin": "extracted_archive",
                            "extracted_from": parent["file_id"],
                        }
                    )
        except LiveProcessingCancelled:
            raise
        except (LiveProcessingError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
            failure = exc.code if isinstance(exc, LiveProcessingError) else "invalid_archive"
        if failure is None:
            parent["archive_status"] = "extracted"
            parent["status"] = "extracted"
            expanded.extend(children)
        else:
            for output in outputs:
                output.unlink(missing_ok=True)
            canonical = {
                str(item["sha256"]): str(item["file_id"])
                for item in expanded
                if item.get("duplicate_of") is None
            }
            parent["archive_status"] = "extraction_failed"
            parent["status"] = "extraction_failed"
            parent["limitations"].append("ZIP extraction failed a security or integrity check.")
            limitations.append(f"ZIP extraction limitation: {failure}.")
    archives_by_id = {
        str(item["file_id"]): item for item in inventory if item.get("media_type") in {"zip", "rar"}
    }
    for item in inventory:
        duplicate_of = item.get("duplicate_of")
        if item.get("media_type") != "zip" or not isinstance(duplicate_of, str):
            continue
        canonical_archive = archives_by_id.get(duplicate_of)
        if canonical_archive is not None:
            item["archive_status"] = canonical_archive["archive_status"]
            item["limitations"].append("Duplicate ZIP archive was not extracted twice.")
    return expanded, sorted(set(limitations))


def _document_type(section: str, filename: str) -> tuple[str, str, float]:
    name = filename.casefold()
    if section == "hearing_protocol":
        return "hearing_protocol", "dossier_section", 1.0
    if section == "visual_geographic_materials":
        if any(value in name for value in ("карта", "map", "генплан")):
            return "map", "filename_hint", 0.65
        if any(value in name for value in ("фото", "photo")):
            return "photo", "filename_hint", 0.65
        return "appendix", "dossier_section", 0.5
    if section == "procedural_publication_evidence":
        return "appendix", "dossier_section", 0.7
    if section == "official_supporting_documents":
        if "отказ" in name or "refusal" in name:
            return "motivated_refusal", "filename_hint", 0.75
        return "appendix", "dossier_section", 0.5
    hints = (
        ("ndv", ("ндв", "emission limit")),
        ("pek", ("пэк", "environmental control")),
        ("puo", ("пуо", "waste management")),
        ("ovvos", ("овос", "ovvos", "eia")),
        ("roos", ("роос", "roos")),
        ("action_plan", ("ппм", "action plan")),
        ("nontechnical_summary", ("нетехническ", "nontechnical")),
        ("explanatory_note", ("опз", "пояснительн", "explanatory")),
        ("working_project_note", ("рабоч", "working project")),
    )
    for kind, tokens in hints:
        if any(token in name for token in tokens):
            return kind, "filename_hint", 0.7
    return "unknown", "unclassified", 0.0


def _write_manifest(
    workspace: Path, request: dict[str, Any], inventory: list[dict[str, Any]]
) -> tuple[Path, dict[str, Any], list[DocumentPlan]]:
    project_id = str(request["project_id"])
    documents: list[dict[str, Any]] = []
    plans: list[DocumentPlan] = []
    for item in inventory:
        if (
            item.get("media_type") not in {"pdf", "docx"}
            or item.get("duplicate_of") is not None
            or item.get("status") not in {"accepted", "extracted"}
        ):
            continue
        section = str(item["section_id"])
        role = "model_input" if section == "project_documents" else "label_source"
        kind, source, confidence = _document_type(section, str(item.get("display_filename") or ""))
        document_id = f"{project_id}__live__{len(plans) + 1:04d}"
        plan = DocumentPlan(
            document_id=document_id,
            file_id=str(item["file_id"]),
            section_id=section,
            display_name=str(item.get("display_filename") or document_id),
            internal_path=str(item["internal_path"]),
            media_type=str(item["media_type"]),
            sha256=str(item["sha256"]),
            document_type=kind,
            role=role,
        )
        plans.append(plan)
        documents.append(
            {
                "document_id": document_id,
                "local_path": plan.internal_path,
                "original_filename": plan.display_name,
                "document_type": kind,
                "role": role,
                "use_as_model_feature": role == "model_input",
                "file_format": plan.media_type,
                "sha256": plan.sha256,
                "label_timing": "pre_review" if role == "model_input" else "post_review",
                "notes": "Conservative job-local type classification.",
                "live_file_id": plan.file_id,
                "dossier_section_id": section,
                "classification_source": source,
                "classification_confidence": confidence,
            }
        )
    metadata_dir = workspace / "data" / "raw" / project_id
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = metadata_dir / "source_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "project_id": project_id,
                "source_type": "authenticated_live_upload",
                "project_display_name": request.get("project_display_name"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    project = {
        "schema_version": "1.0",
        "project_id": project_id,
        "source_metadata_path": metadata_path.relative_to(workspace).as_posix(),
        "source_url": None,
        "region": None,
        "industry": None,
        "languages": [],
        "documents": documents,
        "live_job_id": request["job_id"],
    }
    manifest_dir = workspace / "data" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "live_projects.jsonl"
    path.write_text(
        json.dumps(project, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path, project, plans


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for value in [json.loads(line)]
        if isinstance(value, dict)
    ]


def _ingest_plans(
    workspace: Path,
    manifest: Path,
    plans: list[DocumentPlan],
    progress: Progress | None,
    cancelled: Callable[[], bool] | None,
) -> Any:
    from dalel.config import OcrMode
    from dalel.ingestion.pipeline import IngestOptions, ingest_documents
    from dalel.ingestion.reports import BatchResult, utc_now_iso

    batch = BatchResult(started_at=utc_now_iso())
    total = max(1, len(plans))
    for index, plan in enumerate(plans, start=1):
        _cancel(cancelled)
        _progress(
            progress,
            "preparing",
            min(34, 18 + int(16 * (index - 1) / total)),
            "Извлечение текста, таблиц и изображений",
            {"metrics": {"documents_started": index, "documents_total": len(plans)}},
        )
        result = ingest_documents(
            IngestOptions(
                manifest_path=manifest,
                repo_root=workspace,
                document_id=plan.document_id,
                ocr_mode=OcrMode.AUTO,
                include_label_sources=True,
                force=True,
                parser_policy="lightweight",
            )
        )
        batch.results.extend(result.results)
    batch.completed_at = utc_now_iso()
    return batch


def _full_text_fallback(
    workspace: Path, project_id: str, plans: list[DocumentPlan], batch: Any
) -> int:
    from dalel.config import INGESTION_SCHEMA_VERSION
    from dalel.schemas.document import SectionRecord
    from dalel.schemas.evidence import Provenance

    results = {item.document_id: item for item in batch.results}
    added = 0
    for plan in plans:
        result = results.get(plan.document_id)
        if result is None or result.status not in {"success", "partial"}:
            continue
        tree = "model_inputs" if plan.role == "model_input" else "label_sources"
        directory = workspace / "data" / "processed" / tree / project_id / plan.document_id
        if _read_jsonl(directory / "sections.jsonl"):
            continue
        sections: list[SectionRecord] = []
        for page in _read_jsonl(directory / "pages.jsonl"):
            text = str(page.get("text") or "").strip()
            number = page.get("page_number")
            provenance = page.get("provenance")
            if not text or not isinstance(number, int) or not isinstance(provenance, dict):
                continue
            sections.append(
                SectionRecord(
                    schema_version=INGESTION_SCHEMA_VERSION,
                    section_id=f"{plan.document_id}__live_full_text__{number:04d}",
                    page_start=number,
                    page_end=number,
                    text=text,
                    char_count=len(text),
                    warnings=["Live-only fallback: heading structure was unavailable."],
                    # Preserve the accepted provenance enum. The record and
                    # document warnings explicitly identify this live-only
                    # structural fallback without claiming a new parser.
                    provenance=Provenance.model_validate(provenance),
                )
            )
        if not sections:
            continue
        (directory / "sections.jsonl").write_text(
            "".join(item.model_dump_json() + "\n" for item in sections),
            encoding="utf-8",
        )
        warning = "Live-only page-text sections were created without heading structure."
        for filename in ("document.json", "ingestion_report.json"):
            path = directory / filename
            payload = json.loads(path.read_text(encoding="utf-8"))
            warnings = [str(value) for value in payload.get("warnings", [])]
            warnings.append(warning)
            payload["warnings"] = list(dict.fromkeys(warnings))
            if payload.get("extraction_status") == "success":
                payload["extraction_status"] = "partial"
            if filename == "ingestion_report.json":
                payload["section_count"] = len(sections)
                payload["warning_count"] = len(payload["warnings"])
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        result.sections = len(sections)
        result.warning_count += 1
        if result.status == "success":
            result.status = "partial"
        added += len(sections)
    return added


def _curate(
    workspace: Path, project: dict[str, Any], batch: Any
) -> tuple[Path | None, dict[str, Any], set[str]]:
    successful = {
        item.document_id
        for item in batch.results
        if item.status in {"success", "partial", "skipped_cached"}
    }
    documents = [item for item in project["documents"] if item["document_id"] in successful]
    model_inputs = {
        str(item["document_id"]) for item in documents if item.get("role") == "model_input"
    }
    if not model_inputs:
        return (
            None,
            {
                "status": "unavailable",
                "reason": "No successfully extracted project document was available.",
            },
            set(),
        )
    curated_project = {**project, "documents": documents}
    manifest = workspace / "data" / "manifests" / "curation_projects.jsonl"
    manifest.write_text(
        json.dumps(curated_project, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    from dalel.curation.builder import CurateOptions, build_curated_dataset

    annotations = workspace / "data" / "annotations"
    annotations.mkdir(parents=True, exist_ok=True)
    output = workspace / "data" / "curated" / "v1"
    try:
        result = build_curated_dataset(
            CurateOptions(
                input_root=workspace / "data" / "processed",
                output_dir=output,
                repo_root=workspace,
                manifest_path=manifest,
                annotations_root=annotations,
            )
        )
    except Exception:
        return (
            None,
            {"status": "failed", "reason": "Job-local curation failed validation."},
            model_inputs,
        )
    summary = {
        "status": result.status,
        "counts": result.counts,
        "input_fingerprint": result.input_fingerprint,
        "error_count": len(result.errors),
    }
    return output if result.status == "success" else None, summary, model_inputs


def _primitive_metrics(metrics: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    return {
        str(key): value
        for key, value in metrics.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }


def _metric_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "label": key.replace("_", " "),
            "value": str(value),
            "hint": None,
            "technical_id": key,
        }
        for key, value in list(_primitive_metrics(metrics).items())[:5]
    ]


def _stage(
    stage_id: str,
    title: str,
    status: str,
    *,
    pillar_id: str | None = None,
    operation: str | None = None,
    metrics: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    limitations: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "pillar_id": pillar_id,
        "title": title,
        "status": status,
        "operation": operation,
        "progress": 100 if status in {"completed", "insufficient_input", "unavailable"} else 0,
        "metrics": metrics or [],
        "warnings": warnings or [],
        "limitations": limitations or [],
        "reason": reason,
    }


def _model_rows(values: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in values:
        if hasattr(value, "model_dump"):
            rows.append(value.model_dump(mode="json"))
        elif isinstance(value, dict):
            rows.append(value)
    return rows


def _run_p1(dataset: Path, output: Path, annotations: Path, project_id: str) -> Any:
    from dalel.pillars.document_integrity.pipeline import P1Options, run_p1

    return run_p1(
        P1Options(
            dataset_dir=dataset,
            output_dir=output,
            annotations_root=annotations,
            project_id=project_id,
        )
    )


def _run_p2(dataset: Path, output: Path, annotations: Path, project_id: str) -> Any:
    from dalel.pillars.regulatory_compliance.corpus import DEMO_CORPUS_RESOURCE
    from dalel.pillars.regulatory_compliance.pipeline import P2Options, run_p2
    from dalel.pillars.regulatory_compliance.validation import validate_p2_outputs

    result = run_p2(
        P2Options(
            dataset_dir=dataset,
            output_dir=output,
            annotations_root=annotations,
            regulations=None,
            provider_name="none",
            use_cache=False,
            project_id=project_id,
        )
    )
    validation = validate_p2_outputs(dataset, DEMO_CORPUS_RESOURCE, output, annotations)
    if not validation.ok:
        raise LiveProcessingError("p2_validation_failed")
    return result


def _run_p3(dataset: Path, output: Path, annotations: Path, project_id: str) -> Any:
    from dalel.pillars.quantitative_consistency.pipeline import P3Options, run_p3
    from dalel.pillars.quantitative_consistency.validation import validate_p3_outputs

    result = run_p3(
        P3Options(
            dataset_dir=dataset,
            output_dir=output,
            annotations_root=annotations,
            project_id=project_id,
        )
    )
    validation = validate_p3_outputs(dataset, output, annotations)
    if not validation.ok:
        raise LiveProcessingError("p3_validation_failed")
    return result


def _run_p4(dataset: Path, output: Path, annotations: Path, project_id: str) -> Any:
    from dalel.pillars.cross_document_coherence.pipeline import P4Options, run_p4
    from dalel.pillars.cross_document_coherence.validation import validate_p4_outputs

    result = run_p4(
        P4Options(
            dataset_dir=dataset,
            output_dir=output,
            annotations_root=annotations,
            project_id=project_id,
        )
    )
    validation = validate_p4_outputs(dataset, output, annotations)
    if not validation.ok:
        raise LiveProcessingError("p4_validation_failed")
    return result


def _run_pillars(
    workspace: Path,
    dataset: Path | None,
    project_id: str,
    progress: Progress | None,
    cancelled: Callable[[], bool] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Path]]:
    annotations = workspace / "data" / "annotations"
    annotations.mkdir(parents=True, exist_ok=True)
    root = workspace / "data" / "results"
    specs = (
        ("P1", "running_p1", 40, "Проверка целостности документов", _run_p1),
        ("P2", "running_p2", 53, "Сопоставление с нормативным корпусом", _run_p2),
        ("P3", "running_p3", 66, "Проверка количественной согласованности", _run_p3),
        ("P4", "running_p4", 79, "Проверка междокументной связности", _run_p4),
    )
    stages: list[dict[str, Any]] = []
    pillars: dict[str, Any] = {}
    available: dict[str, Path] = {}
    for pillar_id, state, percent, operation, runner in specs:
        _cancel(cancelled)
        _progress(progress, state, percent, operation)
        if dataset is None:
            reason = "Curated model-input dataset is unavailable."
            limitations = ["Missing evidence is not interpreted as low risk."]
            pillars[pillar_id] = {
                "pillar_id": pillar_id,
                "status": "unavailable",
                "reason": reason,
                "coverage": None,
                "assessment_confidence": None,
                "metrics": {},
                "warnings": [],
                "limitations": limitations,
            }
            stages.append(
                _stage(
                    pillar_id.lower(),
                    operation,
                    "unavailable",
                    pillar_id=pillar_id,
                    reason=reason,
                    limitations=limitations,
                )
            )
            continue
        output = root / pillar_id.lower()
        warnings: list[str] = []
        if pillar_id == "P2":
            warnings.append(
                "The packaged regulatory corpus is synthetic/demo-only and non-authoritative."
            )
        try:
            result = runner(dataset, output, annotations, project_id)
            available[pillar_id] = output
            status = "completed"
            current_reason: str | None = None
            current_limitations: list[str] = []
            if pillar_id == "P3" and not result.mentions:
                status = "insufficient_input"
                current_reason = "No reliable quantitative mentions were extracted."
                current_limitations.append(
                    "Insufficient numeric evidence is not interpreted as consistency."
                )
            if pillar_id == "P4" and len(result.document_scores) < 2:
                status = "insufficient_input"
                current_reason = "Fewer than two model-input documents were available."
                current_limitations.append(
                    "Cross-document coherence cannot be established from one document."
                )
            payload: dict[str, Any] = {
                "pillar_id": pillar_id,
                "status": status,
                "reason": current_reason,
                "coverage": None,
                "assessment_confidence": None,
                "metrics": _primitive_metrics(result.metrics),
                "warnings": warnings,
                "limitations": current_limitations,
                "findings": _model_rows(result.findings),
                "document_scores": _model_rows(result.document_scores),
                "project_scores": _model_rows(result.project_scores),
            }
            for name in (
                "section_matches",
                "assessments",
                "retrievals",
                "evidence",
                "mentions",
                "suppressed_samples",
                "candidates",
                "aggregation_checks",
                "claims",
                "entities",
                "edges",
                "resolution_decisions",
                "suppressed",
            ):
                values = getattr(result, name, None)
                if isinstance(values, list):
                    payload[name] = _model_rows(values)
            pillars[pillar_id] = payload
            stages.append(
                _stage(
                    pillar_id.lower(),
                    operation,
                    status,
                    pillar_id=pillar_id,
                    operation=operation,
                    metrics=_metric_rows(result.metrics),
                    warnings=warnings,
                    limitations=current_limitations,
                    reason=current_reason,
                )
            )
        except Exception:
            reason = f"{pillar_id} could not produce a valid job-local artifact."
            pillars[pillar_id] = {
                "pillar_id": pillar_id,
                "status": "failed",
                "reason": reason,
                "coverage": None,
                "assessment_confidence": None,
                "metrics": {},
                "warnings": warnings,
                "limitations": [],
            }
            stages.append(
                _stage(
                    pillar_id.lower(),
                    operation,
                    "failed",
                    pillar_id=pillar_id,
                    operation=operation,
                    warnings=warnings,
                    reason=reason,
                )
            )
    return stages, pillars, available


def _run_meta(
    workspace: Path,
    project_id: str,
    available: dict[str, Path],
    progress: Progress | None,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    _cancel(cancelled)
    title = "Интегрированный приоритет проверки"
    _progress(progress, "running_meta", 91, title)
    if not available:
        reason = "No validated pillar artifact is available."
        stage = _stage(
            "meta",
            title,
            "unavailable",
            reason=reason,
            limitations=["Unavailable pillars are never counted as zero risk."],
        )
        return None, {"status": "unavailable", "reason": reason}, stage
    unavailable = workspace / "data" / "results" / "unavailable"
    paths = {
        pillar: available.get(pillar, unavailable / pillar.lower())
        for pillar in ("P1", "P2", "P3", "P4")
    }
    try:
        from dalel.meta_review.pipeline import run_meta

        result = run_meta(
            paths["P1"],
            paths["P2"],
            paths["P3"],
            paths["P4"],
            workspace / "data" / "results" / "meta",
            workspace / "data" / "annotations",
        )
        assessment = next(item for item in result.assessments if item.project_id == project_id)
        payload = assessment.model_dump(mode="json")
        payload["available_pillars"] = list(result.metrics.get("pillars_available", []))
        payload["missing_pillars"] = list(result.metrics.get("pillars_unavailable", []))
        payload["review_notice"] = str(result.metrics.get("interpretation") or "")
        summary = {
            "status": "completed",
            "metrics": result.metrics,
            "calibrated_probability": payload.get("calibrated_probability"),
            "shap_contributions": payload.get("shap_contributions"),
        }
        stage = _stage(
            "meta",
            title,
            "completed",
            operation=title,
            metrics=_metric_rows(result.metrics),
            limitations=["This prioritizes expert review; it is not a legal or harm probability."],
        )
        return payload, summary, stage
    except Exception:
        reason = "Meta could not align the available validated pillar artifacts."
        return (
            None,
            {"status": "failed", "reason": reason},
            _stage("meta", title, "failed", operation=title, reason=reason),
        )


_P5_PHASE_TITLES = {
    "inventory": "Инвентаризация визуальных активов",
    "duplicate_clustering": "Кластеризация дубликатов",
    "classification": "Модельная классификация изображений",
    "ocr_context": "OCR и привязка контекста",
    "cross_modal_checks": "Кросс-модальные проверки",
    "findings": "Формирование находок и оценок",
    "completed": "P5 завершён",
}

_P5_TITLE = "Мультимодальный анализ визуальных доказательств"

P5_META_NOTICE = (
    "P5 отображается отдельно и будет включён в интегральную оценку после реализации P6 и Meta v2."
)


def _p5_direct_assets(
    workspace: Path, project_id: str, inventory: list[dict[str, Any]], plans: list[DocumentPlan]
) -> list[Any]:
    """Live-only P5 inputs: uploaded rasters and label-source document images."""
    from dalel.pillars.multimodal_visual_evidence.assets import DirectAssetSpec

    specs: list[Any] = []
    for item in sorted(inventory, key=lambda row: str(row.get("file_id", ""))):
        media = str(item.get("media_type") or "").lower()
        if media not in {"jpg", "jpeg", "png"}:
            continue
        internal = str(item.get("internal_path") or "")
        try:
            path = _path_in(workspace, internal, workspace)
        except LiveProcessingError:
            continue
        if not path.is_file():
            continue
        file_id = str(item.get("file_id") or "")
        from_archive = item.get("source_origin") == "extracted_archive"
        specs.append(
            DirectAssetSpec(
                key=file_id,
                path=path,
                project_id=project_id,
                document_id=file_id,
                image_id=file_id,
                extraction_origin=("extracted_archive_image" if from_archive else "uploaded_image"),
                extraction_method=(
                    "archive_stream_extraction" if from_archive else "direct_upload"
                ),
                provenance_reference=(
                    f"archive:{item.get('extracted_from')}:{file_id}"
                    if from_archive
                    else f"upload:{file_id}"
                ),
                source_reference=f"intake:{file_id}",
                workspace_relative_path=internal,
                dossier_section=str(item.get("section_id") or "") or None,
                display_hint=str(item.get("display_filename") or ""),
            )
        )
    # Label-source document images (e.g. hearing-protocol scans) are P5 inputs
    # for visual triage without ever letting their text cross the model-input
    # boundary of P1–P4.
    label_root = workspace / "data" / "processed" / "label_sources" / project_id
    for plan in sorted(plans, key=lambda p: p.document_id):
        if plan.role == "model_input":
            continue
        images_path = label_root / plan.document_id / "images.jsonl"
        if not images_path.is_file():
            continue
        for index, line in enumerate(images_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            relative = row.get("image_path")
            if not relative:
                continue
            try:
                path = _path_in(label_root / plan.document_id, str(relative), workspace)
            except LiveProcessingError:
                continue
            if not path.is_file():
                continue
            image_id = str(row.get("image_id") or f"img_{index:04d}")
            raw_provenance = row.get("provenance")
            provenance: dict[str, Any] = raw_provenance if isinstance(raw_provenance, dict) else {}
            page_number = row.get("page_number")
            specs.append(
                DirectAssetSpec(
                    key=f"{plan.document_id}:{image_id}",
                    path=path,
                    project_id=project_id,
                    document_id=plan.document_id,
                    image_id=image_id,
                    extraction_origin="label_source_document_image",
                    extraction_method=str(
                        provenance.get("extraction_method") or "p0.5_image_extraction"
                    ),
                    provenance_reference=f"label_source:{plan.document_id}",
                    source_reference=(
                        f"processed:label_sources:{plan.document_id}:images.jsonl:{index}"
                    ),
                    workspace_relative_path=str(path.relative_to(workspace)),
                    document_type=plan.document_type,
                    page_number=page_number if isinstance(page_number, int) else None,
                    dossier_section=plan.section_id,
                    display_hint=plan.display_name,
                )
            )
    return specs


def _run_p5(
    workspace: Path,
    curated: Path | None,
    project_id: str,
    plans: list[DocumentPlan],
    inventory: list[dict[str, Any]],
    progress: Progress | None,
    cancelled: Callable[[], bool] | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Run live P5 after P4. Failure never blocks P1–P4 or Meta v1.

    Returns ``(pillar_payload, stage, visual_analysis_status)``.
    """
    _cancel(cancelled)
    _progress(progress, "running_p5", 85, _P5_TITLE)
    limitations = [P5_META_NOTICE]
    try:
        direct = _p5_direct_assets(workspace, project_id, inventory, plans)
        if curated is None and not direct:
            reason = "Ни подготовленного набора документов, ни загруженных изображений нет."
            payload: dict[str, Any] = {
                "pillar_id": "P5",
                "status": "unavailable",
                "reason": reason,
                "coverage": None,
                "assessment_confidence": None,
                "metrics": {},
                "warnings": [],
                "limitations": limitations,
                "meta_integration_status": "pending_p6_meta_v2",
            }
            stage = _stage(
                "p5",
                _P5_TITLE,
                "unavailable",
                pillar_id="P5",
                reason=reason,
                limitations=limitations,
            )
            return payload, stage, "not_available"

        from dalel.pillars.multimodal_visual_evidence.pipeline import (
            P5Options,
        )
        from dalel.pillars.multimodal_visual_evidence.pipeline import (
            run_p5 as run_p5_pipeline,
        )
        from dalel.pillars.multimodal_visual_evidence.validation import validate_p5_outputs

        results_root = workspace / "data" / "results"
        dataset_dir = curated if curated is not None else workspace / "data" / "curated" / "v1"

        def phase_progress(phase: str) -> None:
            title = _P5_PHASE_TITLES.get(phase, phase)
            _progress(progress, "running_p5", 85, f"P5: {title}")

        result = run_p5_pipeline(
            P5Options(
                dataset_dir=dataset_dir,
                output_dir=results_root / "p5",
                annotations_root=workspace / "data" / "annotations",
                project_id=project_id,
                p3_dir=(results_root / "p3") if (results_root / "p3").is_dir() else None,
                p4_dir=(results_root / "p4") if (results_root / "p4").is_dir() else None,
                direct_assets=direct,
                dossier_sections={plan.document_id: plan.section_id for plan in plans},
                document_hints={plan.document_id: plan.display_name for plan in plans},
                allow_missing_dataset=True,
                progress=phase_progress,
            )
        )
        validation = validate_p5_outputs(dataset_dir, results_root / "p5")
        if not validation.ok:
            raise LiveProcessingError("p5_validation_failed")

        model_available = result.metrics.get("model_status") == "available"
        project_score = next((s for s in result.project_scores if s.project_id == project_id), None)
        warnings = []
        if not model_available:
            warnings.append(
                "Визуальные материалы зарегистрированы, но мультимодальная модель недоступна."
            )
        summary = {
            "total_asset_count": project_score.total_asset_count if project_score else 0,
            "analyzed_representative_count": (
                project_score.analyzed_representative_count if project_score else 0
            ),
            "excluded_duplicate_count": (
                project_score.excluded_duplicate_count if project_score else 0
            ),
            "excluded_header_or_logo_count": (
                project_score.excluded_header_or_logo_count if project_score else 0
            ),
            "procedural_asset_count": (
                project_score.procedural_asset_count if project_score else 0
            ),
            "duplicate_cluster_count": (
                project_score.duplicate_cluster_count if project_score else 0
            ),
            "review_priority": (
                project_score.visual_evidence_review_priority_score if project_score else 0
            ),
            "visual_coverage": project_score.visual_coverage if project_score else None,
            "assessment_confidence": (
                project_score.assessment_confidence if project_score else None
            ),
            "model_status": "available" if model_available else "unavailable",
        }
        payload = {
            "pillar_id": "P5",
            "status": "completed",
            "reason": None,
            "coverage": project_score.visual_coverage if project_score else None,
            "assessment_confidence": (
                project_score.assessment_confidence if project_score else None
            ),
            "metrics": _primitive_metrics(result.metrics),
            "warnings": warnings,
            "limitations": limitations,
            "meta_integration_status": "pending_p6_meta_v2",
            "summary": summary,
            "assets": _model_rows(result.assets),
            "asset_contexts": _model_rows(result.contexts),
            "classifications": _model_rows(result.classifications),
            "duplicate_clusters": _model_rows(result.clusters),
            "findings": _model_rows(result.findings),
            "suppressions": _model_rows(result.suppressions),
            "document_scores": _model_rows(result.document_scores),
            "project_scores": _model_rows(result.project_scores),
        }
        stage = _stage(
            "p5",
            _P5_TITLE,
            "completed",
            pillar_id="P5",
            operation=_P5_TITLE,
            metrics=[
                {
                    "label": "visual assets",
                    "value": str(summary["total_asset_count"]),
                    "hint": None,
                    "technical_id": "assets_total",
                },
                {
                    "label": "analyzed representatives",
                    "value": str(summary["analyzed_representative_count"]),
                    "hint": None,
                    "technical_id": "analyzed_representatives",
                },
                {
                    "label": "duplicates excluded",
                    "value": str(summary["excluded_duplicate_count"]),
                    "hint": None,
                    "technical_id": "duplicates_excluded",
                },
                {
                    "label": "findings",
                    "value": str(len(result.findings)),
                    "hint": None,
                    "technical_id": "findings",
                },
            ],
            warnings=warnings,
            limitations=limitations,
        )
        return payload, stage, ("completed" if model_available else "model_unavailable")
    except LiveProcessingCancelled:
        raise
    except Exception:
        reason = "P5 не смог сформировать корректный артефакт в рамках задания."
        payload = {
            "pillar_id": "P5",
            "status": "failed",
            "reason": reason,
            "coverage": None,
            "assessment_confidence": None,
            "metrics": {},
            "warnings": [],
            "limitations": limitations,
            "meta_integration_status": "pending_p6_meta_v2",
        }
        stage = _stage(
            "p5",
            _P5_TITLE,
            "failed",
            pillar_id="P5",
            operation=_P5_TITLE,
            reason=reason,
            limitations=limitations,
        )
        return payload, stage, "failed"


def _inventory_payload(inventory: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
    supplied = {str(item["section_id"]) for item in inventory if item.get("duplicate_of") is None}
    if request.get("public_feedback") is not None:
        supplied.add("public_feedback_metadata")
    project_documents = [
        item
        for item in inventory
        if item["section_id"] == "project_documents"
        and item["media_type"] in {"pdf", "docx"}
        and item.get("duplicate_of") is None
    ]
    return {
        "expected_sections": list(SECTIONS),
        "supplied_sections": [value for value in SECTIONS if value in supplied],
        "missing_sections": [value for value in SECTIONS if value not in supplied],
        "unsupported_materials": [
            str(item["file_id"])
            for item in inventory
            if item.get("archive_status") in {"extraction_unsupported", "extraction_failed"}
        ],
        "duplicate_files": [
            str(item["file_id"]) for item in inventory if item.get("duplicate_of") is not None
        ],
        "package_readiness": (
            "Пакет содержит проектные документы и готов к доступным проверкам."
            if project_documents
            else "Проектные документы отсутствуют; P1–P4 и Meta могут быть недоступны."
        ),
        "files": [
            {
                "file_id": item["file_id"],
                "safe_display_name": str(
                    item.get("display_filename") or item.get("file_id") or "file"
                ),
                "section_id": item["section_id"],
                "size_bytes": item["size_bytes"],
                "media_type": item["media_type"],
                "sha256": item["sha256"],
                "duplicate_of": item.get("duplicate_of"),
                "archive_status": item.get("archive_status", "not_archive"),
                "status": item.get("status", "accepted"),
                "limitations": list(item.get("limitations") or []),
                "source_origin": item.get("source_origin", "user_upload"),
                "extracted_from": item.get("extracted_from"),
            }
            for item in inventory
        ],
        "public_feedback": request.get("public_feedback"),
    }


def process_live_job(
    workspace: Path,
    *,
    progress: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run genuine live analysis using only one authenticated job workspace."""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise LiveProcessingError("workspace_unavailable")
    _cancel(cancelled)
    _progress(progress, "validating", 7, "Повторная проверка принятого пакета")
    request, limits = _load_request(workspace)
    original_inventory = _validate_files(workspace, request, limits)
    inventory, archive_limitations = _extract_archives(
        workspace, original_inventory, limits, cancelled
    )
    package = _inventory_payload(inventory, request)
    p0_stage = _stage(
        "p0",
        "Проверка полноты и безопасности пакета",
        "completed",
        operation="Повторная проверка принятого пакета",
        metrics=[
            {
                "label": "files",
                "value": str(len(inventory)),
                "hint": None,
                "technical_id": "files",
            },
            {
                "label": "sections supplied",
                "value": str(len(package["supplied_sections"])),
                "hint": None,
                "technical_id": "sections_supplied",
            },
            {
                "label": "duplicates",
                "value": str(len(package["duplicate_files"])),
                "hint": None,
                "technical_id": "duplicates",
            },
        ],
        limitations=archive_limitations,
    )

    _cancel(cancelled)
    _progress(progress, "preparing", 17, "Подготовка изолированного набора документов")
    manifest, project, plans = _write_manifest(workspace, request, inventory)
    batch = _ingest_plans(workspace, manifest, plans, progress, cancelled)
    fallback_count = _full_text_fallback(workspace, str(request["project_id"]), plans, batch)
    curated, curation, model_inputs = _curate(workspace, project, batch)

    from dalel.api.visual_triage import build_visual_inventory

    visuals = build_visual_inventory(
        workspace,
        job_id=str(request["job_id"]),
        curated_dir=curated,
        inventory=inventory,
        processed_root=workspace / "data" / "processed",
        project_id=str(request["project_id"]),
        document_sections={item.document_id: item.section_id for item in plans},
        document_hints={item.document_id: item.display_name for item in plans},
        document_roles={item.document_id: item.role for item in plans},
    )
    statuses = batch.by_status()
    prepared_count = sum(
        count
        for status, count in statuses.items()
        if status in {"success", "partial", "skipped_cached"}
    )
    preparation = {
        "document_count": len(plans),
        "prepared_document_count": prepared_count,
        "page_count": sum(
            item.pages
            for item in batch.results
            if item.status in {"success", "partial", "skipped_cached"}
        ),
        "extracted_visual_asset_count": visuals["assets_total"],
        "extraction_failure_count": statuses.get("failed", 0),
        "full_text_fallback_section_count": fallback_count,
        "model_input_document_count": len(model_inputs),
        "curation": curation,
        "documents": [
            {
                "document_id": item.document_id,
                "status": item.status,
                "reason": item.reason,
                "parser_name": item.parser_name,
                "pages": item.pages,
                "tables": item.tables,
                "images": item.images,
                "sections": item.sections,
                "ocr_pages": item.ocr_pages,
                "warning_count": item.warning_count,
            }
            for item in batch.results
        ],
    }
    preparation_status = (
        "completed"
        if curated is not None
        else "insufficient_input"
        if prepared_count
        else "unavailable"
    )
    p05_stage = _stage(
        "p0_5",
        "Извлечение и подготовка Curated Dataset v1",
        preparation_status,
        operation="Подготовка документов",
        metrics=[
            {
                "label": "documents prepared",
                "value": str(prepared_count),
                "hint": None,
                "technical_id": "documents_prepared",
            },
            {
                "label": "pages",
                "value": str(preparation["page_count"]),
                "hint": None,
                "technical_id": "pages",
            },
            {
                "label": "visual assets",
                "value": str(visuals["assets_total"]),
                "hint": None,
                "technical_id": "visual_assets",
            },
        ],
        reason=(
            None
            if curated is not None
            else "No successfully extracted project document entered the feature layer."
        ),
        limitations=(
            []
            if curated is not None
            else ["Post-review documents do not cross the model-input boundary."]
        ),
    )
    _progress(
        progress,
        "preparing",
        36,
        "Подготовка документов завершена",
        {
            "metrics": {
                "documents_prepared": prepared_count,
                "pages": preparation["page_count"],
                "visual_assets": visuals["assets_total"],
            }
        },
    )
    pillar_stages, pillars, available = _run_pillars(
        workspace,
        curated,
        str(request["project_id"]),
        progress,
        cancelled,
    )
    p5_payload, p5_stage, visual_status = _run_p5(
        workspace,
        curated,
        str(request["project_id"]),
        plans,
        inventory,
        progress,
        cancelled,
    )
    pillars["P5"] = p5_payload
    # Meta v1 deliberately remains based on P1–P4 only; P5 is reported apart.
    meta, meta_summary, meta_stage = _run_meta(
        workspace,
        str(request["project_id"]),
        available,
        progress,
        cancelled,
    )
    if meta is not None:
        for contribution in meta.get("pillar_contributions", []):
            pillar_id = contribution.get("pillar_id")
            if pillar_id in pillars:
                pillars[pillar_id]["coverage"] = contribution.get("evidence_coverage")
                pillars[pillar_id]["assessment_confidence"] = contribution.get(
                    "assessment_confidence"
                )
    _cancel(cancelled)
    warnings = ["P2 uses the packaged synthetic/demo-only regulatory corpus."]
    if visual_status == "completed":
        p5_limitation = P5_META_NOTICE
    elif visual_status == "model_unavailable":
        p5_limitation = (
            "Визуальные материалы зарегистрированы, но мультимодальная модель недоступна."
        )
    else:
        p5_limitation = "P5 visual semantics are not available for this job."
    limitations = list(
        dict.fromkeys(
            [
                *archive_limitations,
                p5_limitation,
                "P6 geospatial analysis is not available.",
                (
                    "Structured public-feedback metadata is inventoried but does not "
                    "enter accepted P1–P4 formulas."
                ),
                (
                    "Generated explanations, calibrated probabilities, and production "
                    "SHAP are unavailable."
                ),
            ]
        )
    )
    archive_updates = {
        str(item["file_id"]): {"archive_status": item["archive_status"]}
        for item in original_inventory
        if item["media_type"] in {"zip", "rar"}
    }
    return {
        "schema_version": "1.0",
        "mode": "live_analysis",
        "project_id": request["project_id"],
        "project_name": str(request.get("project_display_name") or "Новый проект"),
        "inventory": package,
        "preparation": preparation,
        "stages": [p0_stage, p05_stage, *pillar_stages, p5_stage, meta_stage],
        "pillars": pillars,
        "meta": meta,
        "meta_summary": meta_summary,
        "visual_inventory": visuals,
        "archive_updates": archive_updates,
        "warnings": warnings,
        "limitations": limitations,
        "visual_analysis_status": visual_status,
        "geospatial_analysis_status": "not_available",
        "generated_explanation": None,
        "generation_status": "not_available",
    }
