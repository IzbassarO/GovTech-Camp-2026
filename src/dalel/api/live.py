"""Secure live-upload job intake and bounded background execution.

This module owns only the API/job boundary. The analytical implementation is
loaded through ``dalel.api.live_processing.process_live_job`` and receives a
job-local workspace; it has no access to the prepared-demo ``ArtifactStore``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import unicodedata
import zipfile
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dalel.api.errors import ApiError
from dalel.api.job_store import (
    JobCapacityError,
    JobCredentials,
    JobNotFoundError,
    SecureJobStore,
)

logger = logging.getLogger(__name__)

LIVE_MODE = "live_analysis"
LIVE_JOB_TOKEN_HEADER = "X-Dalel-Job-Token"

MAX_FILE_COUNT = int(os.environ.get("DALEL_LIVE_MAX_FILES", "20"))
MAX_FILE_BYTES = int(os.environ.get("DALEL_LIVE_MAX_FILE_BYTES", str(50 * 1024 * 1024)))
MAX_TOTAL_BYTES = int(os.environ.get("DALEL_LIVE_MAX_TOTAL_BYTES", str(200 * 1024 * 1024)))
MAX_ARCHIVE_FILES = int(os.environ.get("DALEL_LIVE_MAX_ARCHIVE_FILES", "100"))
MAX_ARCHIVE_EXPANDED_BYTES = int(
    os.environ.get("DALEL_LIVE_MAX_ARCHIVE_EXPANDED_BYTES", str(250 * 1024 * 1024))
)
MAX_ARCHIVE_RATIO = int(os.environ.get("DALEL_LIVE_MAX_ARCHIVE_RATIO", "200"))
LIVE_JOB_TTL_SECONDS = int(os.environ.get("DALEL_LIVE_JOB_TTL_SECONDS", "1800"))
LIVE_MAX_ACTIVE_JOBS = int(os.environ.get("DALEL_LIVE_MAX_ACTIVE_JOBS", "4"))
LIVE_MAX_RETAINED_JOBS = int(os.environ.get("DALEL_LIVE_MAX_RETAINED_JOBS", "32"))
LIVE_WORKERS = int(os.environ.get("DALEL_LIVE_WORKERS", "2"))
UPLOAD_CHUNK_BYTES = 1024 * 1024


def _default_job_root() -> Path:
    configured = os.environ.get("DALEL_LIVE_JOB_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "dalel-live-jobs").resolve()


LiveSectionId = Literal[
    "project_documents",
    "official_supporting_documents",
    "hearing_protocol",
    "procedural_publication_evidence",
    "visual_geographic_materials",
    "public_feedback_metadata",
]

LiveJobState = Literal[
    "created",
    "receiving",
    "validating",
    "preparing",
    "running_p1",
    "running_p2",
    "running_p3",
    "running_p4",
    "running_meta",
    "completed",
    "failed",
    "cancelled",
    "expired",
]

_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "expired"})
_PROCESSING_STATES = frozenset(
    {
        "validating",
        "preparing",
        "running_p1",
        "running_p2",
        "running_p3",
        "running_p4",
        "running_meta",
    }
)

_SECTION_FORMATS: dict[str, tuple[str, ...]] = {
    "project_documents": ("pdf", "docx"),
    "official_supporting_documents": ("pdf", "docx"),
    "hearing_protocol": ("pdf", "docx", "zip", "rar"),
    "procedural_publication_evidence": ("pdf", "jpg", "jpeg", "png"),
    "visual_geographic_materials": ("pdf", "jpg", "jpeg", "png"),
    "public_feedback_metadata": (),
}

_SECTION_TITLES: dict[str, str] = {
    "project_documents": "Проектная документация",
    "official_supporting_documents": "Официальные решения и подтверждающие документы",
    "hearing_protocol": "Протокол общественных слушаний",
    "procedural_publication_evidence": "Подтверждение процедурной публикации",
    "visual_geographic_materials": "Визуальные и географические материалы",
    "public_feedback_metadata": "Структурированные данные обратной связи",
}


class LiveSectionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: LiveSectionId
    order: int
    title_ru: str
    accepted_formats: list[str]
    upload_enabled: bool


class LivePackageLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_file_count: int
    max_file_bytes: int
    max_total_bytes: int
    max_archive_files: int
    max_archive_expanded_bytes: int
    max_archive_ratio: int
    job_ttl_seconds: int
    max_active_jobs: int


class LivePackageSchemaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["live_analysis"] = "live_analysis"
    sections: list[LiveSectionDefinition]
    upload_limits: LivePackageLimits
    visual_analysis_status: Literal["not_available"] = "not_available"
    geospatial_analysis_status: Literal["not_available"] = "not_available"
    generated_explanation: None = None
    generation_status: Literal["not_available"] = "not_available"


def build_live_package_schema() -> LivePackageSchemaResponse:
    sections = [
        LiveSectionDefinition(
            section_id=section_id,  # type: ignore[arg-type]
            order=index,
            title_ru=_SECTION_TITLES[section_id],
            accepted_formats=list(_SECTION_FORMATS[section_id]),
            upload_enabled=section_id != "public_feedback_metadata",
        )
        for index, section_id in enumerate(_SECTION_FORMATS, start=1)
    ]
    return LivePackageSchemaResponse(
        sections=sections,
        upload_limits=LivePackageLimits(
            max_file_count=MAX_FILE_COUNT,
            max_file_bytes=MAX_FILE_BYTES,
            max_total_bytes=MAX_TOTAL_BYTES,
            max_archive_files=MAX_ARCHIVE_FILES,
            max_archive_expanded_bytes=MAX_ARCHIVE_EXPANDED_BYTES,
            max_archive_ratio=MAX_ARCHIVE_RATIO,
            job_ttl_seconds=LIVE_JOB_TTL_SECONDS,
            max_active_jobs=LIVE_MAX_ACTIVE_JOBS,
        ),
    )


class LiveSectionAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: LiveSectionId
    upload_indices: list[int] = Field(default_factory=list, max_length=MAX_FILE_COUNT)

    @field_validator("upload_indices")
    @classmethod
    def _non_negative_indices(cls, value: list[int]) -> list[int]:
        if any(index < 0 for index in value):
            raise ValueError("upload indices must be non-negative")
        if len(set(value)) != len(value):
            raise ValueError("upload indices must be unique within a section")
        return value


class LivePublicFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_count: int = Field(ge=0, le=1_000_000)
    question_count: int = Field(ge=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=1000)


class LiveJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["live_analysis"] = "live_analysis"
    project_display_name: str | None = Field(default=None, min_length=1, max_length=120)
    sections: list[LiveSectionAssignment] = Field(min_length=1, max_length=6)
    public_feedback: LivePublicFeedbackInput | None = None

    @model_validator(mode="after")
    def _unique_sections(self) -> LiveJobRequest:
        section_ids = [section.section_id for section in self.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("section ids must be unique")
        feedback_section = "public_feedback_metadata" in section_ids
        if feedback_section != (self.public_feedback is not None):
            raise ValueError(
                "public_feedback and the public_feedback_metadata section must be supplied together"
            )
        return self


ArchiveState = Literal[
    "not_archive",
    "registered",
    "extracted",
    "extraction_unsupported",
    "extraction_failed",
]


class LiveFileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str
    section_id: LiveSectionId
    display_filename: str
    media_type: Literal["pdf", "docx", "zip", "rar", "jpg", "png"]
    size_bytes: int
    sha256: str
    duplicate_of: str | None = None
    archive_status: ArchiveState


class LiveJobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int
    state: LiveJobState
    progress: int = Field(ge=0, le=100)
    operation: str
    metrics: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class LiveJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    project_id: str
    project_display_name: str
    mode: Literal["live_analysis"] = "live_analysis"
    status: LiveJobState
    progress: int = Field(ge=0, le=100)
    current_operation: str
    file_count: int
    total_size_bytes: int
    files: list[LiveFileResponse]
    result: dict[str, Any] | None = None
    failure_code: str | None = None
    limitations: list[str] = Field(default_factory=list)
    visual_analysis_status: Literal["not_available"] = "not_available"
    geospatial_analysis_status: Literal["not_available"] = "not_available"
    generated_explanation: None = None
    generation_status: Literal["not_available"] = "not_available"


class LiveJobCreatedResponse(LiveJobResponse):
    access_token: str


class LiveJobEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: LiveJobState
    events: list[LiveJobEvent]


@dataclass
class _StoredFile:
    public: LiveFileResponse
    internal_path: str
    declared_content_type: str | None


@dataclass
class _LiveJobRecord:
    job_id: str
    project_id: str
    project_display_name: str
    workspace: Path
    request: LiveJobRequest
    status: LiveJobState = "created"
    progress: int = 0
    current_operation: str = "Задание создано"
    files: list[_StoredFile] = field(default_factory=list)
    total_size_bytes: int = 0
    result: dict[str, Any] | None = None
    failure_code: str | None = None
    limitations: list[str] = field(default_factory=list)
    events: list[LiveJobEvent] = field(default_factory=list)
    event_sequence: int = 0
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    future: Future[None] | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


def _safe_display_text(value: str, *, fallback: str, max_length: int) -> str:
    normalized = unicodedata.normalize("NFC", value)
    cleaned = "".join(
        " " if unicodedata.category(char).startswith("C") else char for char in normalized
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned or fallback)[:max_length]


def _safe_filename(filename: str | None, index: int) -> str:
    raw = filename or f"upload-{index + 1}"
    portable = raw.replace("\\", "/")
    path = PurePosixPath(portable)
    if portable.startswith("/") or re.match(r"^[A-Za-z]:", portable) or ".." in path.parts:
        raise ApiError(422, "unsafe_filename", "Имя файла содержит небезопасный путь.")
    name = path.name
    if not name or name in {".", ".."}:
        raise ApiError(422, "unsafe_filename", "Имя файла некорректно.")
    safe = _safe_display_text(name, fallback=f"upload-{index + 1}", max_length=200)
    return safe.replace("/", "_").replace("\\", "_")


def _extension(filename: str) -> str:
    if "." not in filename:
        return ""
    extension = filename.rsplit(".", 1)[-1].lower().strip()
    return "jpg" if extension == "jpeg" else extension


_EXPECTED_CONTENT_TYPES: dict[str, frozenset[str]] = {
    "pdf": frozenset({"application/pdf"}),
    "docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    "zip": frozenset({"application/zip", "application/x-zip-compressed"}),
    "rar": frozenset({"application/vnd.rar", "application/x-rar-compressed"}),
    "jpg": frozenset({"image/jpeg"}),
    "png": frozenset({"image/png"}),
}
_GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream"})


def _validate_declared_content_type(extension: str, content_type: str | None) -> None:
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared in _GENERIC_CONTENT_TYPES:
        return
    if declared not in _EXPECTED_CONTENT_TYPES[extension]:
        raise ApiError(
            422,
            "mime_mismatch",
            "Заявленный MIME-тип файла не соответствует его расширению.",
        )


def _looks_like_zip(header: bytes) -> bool:
    return header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))


def _validate_magic(path: Path, extension: str, header: bytes) -> None:
    valid = False
    if extension == "pdf":
        valid = header.lstrip().startswith(b"%PDF-")
    elif extension == "png":
        valid = header.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension == "jpg":
        valid = header.startswith(b"\xff\xd8\xff")
    elif extension == "rar":
        valid = header.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
    elif extension in {"zip", "docx"}:
        valid = _looks_like_zip(header) and zipfile.is_zipfile(path)
    if not valid:
        raise ApiError(
            422,
            "file_signature_mismatch",
            "Содержимое файла не соответствует заявленному формату.",
        )


def _archive_member_is_unsafe(name: str) -> bool:
    portable = name.replace("\\", "/")
    path = PurePosixPath(portable)
    return (
        not portable
        or portable.startswith("/")
        or bool(re.match(r"^[A-Za-z]:", portable))
        or ".." in path.parts
        or "\x00" in portable
    )


def _validate_zip(path: Path, *, require_docx: bool) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            if require_docx and not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise ApiError(
                    422,
                    "invalid_docx",
                    "Файл DOCX не содержит обязательную структуру документа.",
                )
            file_infos = [info for info in infos if not info.is_dir()]
            if len(file_infos) > MAX_ARCHIVE_FILES:
                raise ApiError(413, "archive_file_limit", "В архиве слишком много файлов.")
            expanded = 0
            normalized_names: set[str] = set()
            for info in file_infos:
                if _archive_member_is_unsafe(info.filename):
                    raise ApiError(
                        422,
                        "archive_path_traversal",
                        "Архив содержит небезопасный путь.",
                    )
                if len(info.filename) > 500:
                    raise ApiError(
                        422,
                        "archive_name_too_long",
                        "Архив содержит слишком длинное имя файла.",
                    )
                normalized = unicodedata.normalize(
                    "NFC", info.filename.replace("\\", "/")
                ).casefold()
                if normalized in normalized_names:
                    raise ApiError(
                        422,
                        "archive_duplicate_path",
                        "Архив содержит повторяющиеся пути.",
                    )
                normalized_names.add(normalized)
                mode = info.external_attr >> 16
                # Some valid DOCX/ZIP creators store permission bits without
                # POSIX file-type bits. Treat that as an unknown regular type;
                # reject only explicit links or explicit non-regular entries.
                file_type = stat.S_IFMT(mode)
                if stat.S_ISLNK(mode) or file_type not in {0, stat.S_IFREG}:
                    raise ApiError(
                        422,
                        "archive_unsafe_entry",
                        "Архив содержит ссылку или специальный файл.",
                    )
                if info.flag_bits & 0x1:
                    raise ApiError(
                        422,
                        "archive_encrypted",
                        "Зашифрованные архивы не поддерживаются.",
                    )
                if info.file_size > MAX_FILE_BYTES:
                    raise ApiError(413, "archive_entry_limit", "Файл внутри архива слишком велик.")
                expanded += info.file_size
                if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ApiError(
                        413,
                        "archive_expanded_size_limit",
                        "Распакованный размер архива превышает лимит.",
                    )
                compressed = max(1, info.compress_size)
                if info.file_size > 0 and info.file_size / compressed > MAX_ARCHIVE_RATIO:
                    raise ApiError(
                        413,
                        "archive_compression_ratio_limit",
                        "Коэффициент сжатия архива превышает безопасный лимит.",
                    )
                if not require_docx and _extension(info.filename) in {"zip", "rar", "7z"}:
                    raise ApiError(
                        422,
                        "nested_archive_unsupported",
                        "Вложенные архивы не поддерживаются.",
                    )
    except ApiError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ApiError(422, "invalid_archive", "Архив повреждён или не читается.") from exc


def _public_payload(value: Any) -> Any:
    """Drop workspace/path/token details from processor-owned result payloads."""
    if isinstance(value, dict):
        return {
            str(key): _public_payload(item)
            for key, item in value.items()
            if "token" not in str(key).lower()
            and str(key).lower()
            not in {"workspace", "internal_path", "absolute_path", "output_dir"}
        }
    if isinstance(value, list):
        return [_public_payload(item) for item in value]
    if isinstance(value, Path):
        return None
    if isinstance(value, str) and os.path.isabs(value):
        return "[скрытый внутренний путь]"
    return value


class LiveJobManager:
    def __init__(
        self,
        *,
        job_root: Path | None = None,
        workers: int = LIVE_WORKERS,
        max_active_jobs: int = LIVE_MAX_ACTIVE_JOBS,
        ttl_seconds: int = LIVE_JOB_TTL_SECONDS,
        max_retained_jobs: int = LIVE_MAX_RETAINED_JOBS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.job_root = (job_root or _default_job_root()).resolve()
        self.max_active_jobs = max_active_jobs
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="dalel-live"
        )
        self._manager_lock = threading.RLock()
        self._stop_sweeper = threading.Event()
        self._sweeper: threading.Thread | None = None
        self._store: SecureJobStore[_LiveJobRecord] = SecureJobStore(
            prefix="live",
            ttl_seconds=ttl_seconds,
            max_records=max_retained_jobs,
            cleanup=self._cleanup_record,
            clock=clock,
        )

    def _workspace_for(self, job_id: str) -> Path:
        workspace = (self.job_root / job_id).resolve()
        if workspace.parent != self.job_root:
            raise RuntimeError("unsafe generated workspace")
        return workspace

    def _cleanup_record(self, record: _LiveJobRecord) -> None:
        record.cancel_requested.set()
        with record.lock:
            if record.status not in _TERMINAL_STATES:
                record.status = "expired"
            future = record.future
        if future is not None and not future.done():
            future.cancel()
            future.add_done_callback(lambda _: shutil.rmtree(record.workspace, ignore_errors=True))
            return
        shutil.rmtree(record.workspace, ignore_errors=True)

    def start(self) -> None:
        with self._manager_lock:
            if self._sweeper is not None and self._sweeper.is_alive():
                return
            self.job_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.job_root, 0o700)
            self._cleanup_orphan_workspaces()
            self._stop_sweeper.clear()
            self._sweeper = threading.Thread(
                target=self._sweep_loop,
                name="dalel-live-cleanup",
                daemon=True,
            )
            self._sweeper.start()

    def _cleanup_orphan_workspaces(self) -> None:
        active_ids = {record.job_id for record in self._store.values_internal()}
        for child in self.job_root.iterdir():
            if child.name.startswith("live_") and child.name not in active_ids:
                if child.is_symlink():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)

    def _sweep_loop(self) -> None:
        while not self._stop_sweeper.wait(min(30.0, max(1.0, LIVE_JOB_TTL_SECONDS / 4))):
            self._store.sweep_expired()

    def shutdown(self, *, wait: bool = False) -> None:
        self.stop_sweeper()
        self._store.clear()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def stop_sweeper(self) -> None:
        """Stop periodic cleanup without destroying the reusable executor."""
        self._stop_sweeper.set()
        sweeper = self._sweeper
        if sweeper is not None and sweeper is not threading.current_thread():
            sweeper.join(timeout=2)
        self._sweeper = None

    def reset(self) -> None:
        """Deterministic test hook: cancel all jobs and remove all workspaces."""
        self._store.clear()

    def force_cleanup(self) -> int:
        return self._store.sweep_expired()

    def _active_count(self) -> int:
        return sum(
            1 for record in self._store.values_internal() if record.status not in _TERMINAL_STATES
        )

    def _append_event(
        self,
        record: _LiveJobRecord,
        state: LiveJobState,
        progress: int,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = _public_payload(details or {})
        metrics = safe_details.get("metrics") if isinstance(safe_details, dict) else None
        warnings = safe_details.get("warnings", []) if isinstance(safe_details, dict) else []
        limitations = safe_details.get("limitations", []) if isinstance(safe_details, dict) else []
        record.status = state
        record.progress = max(record.progress, min(100, max(0, progress)))
        record.current_operation = _safe_display_text(
            operation, fallback="Обновление статуса", max_length=500
        )
        record.event_sequence += 1
        record.events.append(
            LiveJobEvent(
                sequence=record.event_sequence,
                state=state,
                progress=record.progress,
                operation=record.current_operation,
                metrics=metrics if isinstance(metrics, dict) else None,
                warnings=(
                    [str(item)[:500] for item in warnings] if isinstance(warnings, list) else []
                ),
                limitations=(
                    [str(item)[:500] for item in limitations]
                    if isinstance(limitations, list)
                    else []
                ),
            )
        )
        if len(record.events) > 200:
            record.events = record.events[-200:]

    def _assignment_map(self, request: LiveJobRequest, file_count: int) -> dict[int, str]:
        assignments: dict[int, str] = {}
        for section in request.sections:
            if section.section_id == "public_feedback_metadata" and section.upload_indices:
                raise ApiError(
                    422,
                    "section_not_uploadable",
                    "Раздел структурированной обратной связи не принимает файлы.",
                )
            for index in section.upload_indices:
                if index >= file_count:
                    raise ApiError(
                        422,
                        "unknown_upload_index",
                        "Назначение раздела ссылается на отсутствующий файл.",
                    )
                if index in assignments:
                    raise ApiError(
                        422,
                        "duplicate_upload_assignment",
                        "Один файл назначен более чем одному разделу.",
                    )
                assignments[index] = section.section_id
        if set(assignments) != set(range(file_count)):
            raise ApiError(
                422,
                "unassigned_upload",
                "Каждый загруженный файл должен быть назначен ровно одному разделу.",
            )
        return assignments

    def _reserve(self, request: LiveJobRequest) -> tuple[_LiveJobRecord, JobCredentials]:
        with self._manager_lock:
            self.job_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.job_root, 0o700)
            if self._active_count() >= self.max_active_jobs:
                raise ApiError(
                    503,
                    "live_job_capacity_reached",
                    "Достигнут лимит одновременно обрабатываемых заданий.",
                )

            project_name = _safe_display_text(
                request.project_display_name or "Новый проект",
                fallback="Новый проект",
                max_length=120,
            )

            def factory(job_id: str) -> _LiveJobRecord:
                workspace = self._workspace_for(job_id)
                project_id = f"live_project_{job_id.removeprefix('live_')[:16]}"
                return _LiveJobRecord(
                    job_id=job_id,
                    project_id=project_id,
                    project_display_name=project_name,
                    workspace=workspace,
                    request=request,
                )

            try:
                record, credentials = self._store.create(factory)
            except JobCapacityError as exc:
                raise ApiError(
                    503,
                    "live_job_capacity_reached",
                    "Хранилище временных заданий заполнено.",
                ) from exc

            try:
                record.workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
                (record.workspace / "input").mkdir(mode=0o700)
            except OSError as exc:
                self._store.discard_internal(record.job_id, cleanup=True)
                raise ApiError(
                    503,
                    "live_workspace_unavailable",
                    "Не удалось создать изолированное рабочее пространство.",
                ) from exc
            with record.lock:
                self._append_event(record, "created", 0, "Задание создано")
                self._append_event(record, "receiving", 1, "Приём файлов")
            return record, credentials

    async def create_job(
        self, request: LiveJobRequest, uploads: list[UploadFile]
    ) -> LiveJobCreatedResponse:
        if not uploads:
            raise ApiError(422, "empty_upload", "Необходимо загрузить хотя бы один файл.")
        if len(uploads) > MAX_FILE_COUNT:
            raise ApiError(413, "file_count_limit", "Превышен лимит количества файлов.")
        assignments = self._assignment_map(request, len(uploads))
        record, credentials = self._reserve(request)
        hashes: dict[str, str] = {}
        try:
            for index, upload in enumerate(uploads):
                stored = await self._receive_one(record, upload, index, assignments[index])
                duplicate_of = hashes.get(stored.public.sha256)
                if duplicate_of is None:
                    hashes[stored.public.sha256] = stored.public.file_id
                else:
                    stored.public = stored.public.model_copy(update={"duplicate_of": duplicate_of})
                record.files.append(stored)
            with record.lock:
                record.total_size_bytes = sum(item.public.size_bytes for item in record.files)
                self._write_request(record)
                self._append_event(record, "validating", 5, "Проверка принятого пакета")
                record.future = self._executor.submit(self._run_processor, record.job_id)
            return LiveJobCreatedResponse(
                **self._snapshot(record).model_dump(mode="python"),
                access_token=credentials.access_token,
            )
        except Exception:
            self._store.discard_internal(record.job_id, cleanup=True)
            raise
        finally:
            for upload in uploads:
                with contextlib.suppress(Exception):
                    await upload.close()

    async def _receive_one(
        self,
        record: _LiveJobRecord,
        upload: UploadFile,
        index: int,
        section_id: str,
    ) -> _StoredFile:
        display_name = _safe_filename(upload.filename, index)
        extension = _extension(display_name)
        accepted = {"jpg" if item == "jpeg" else item for item in _SECTION_FORMATS[section_id]}
        if extension not in accepted:
            raise ApiError(
                422,
                "unsupported_file_type",
                f"Формат файла не поддерживается разделом «{_SECTION_TITLES[section_id]}».",
            )
        _validate_declared_content_type(extension, upload.content_type)
        file_id = f"LIVEFILE__{index + 1:04d}"
        internal_name = f"{file_id}.{extension}"
        final_path = record.workspace / "input" / internal_name
        partial_path = final_path.with_suffix(final_path.suffix + ".part")
        digest = hashlib.sha256()
        size = 0
        header = bytearray()
        try:
            with partial_path.open("xb") as handle:
                os.chmod(partial_path, 0o600)
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise ApiError(413, "file_size_limit", "Размер файла превышает лимит.")
                    if record.total_size_bytes + size > MAX_TOTAL_BYTES:
                        raise ApiError(
                            413,
                            "total_upload_size_limit",
                            "Общий размер загружаемого пакета превышает лимит.",
                        )
                    digest.update(chunk)
                    if len(header) < 4096:
                        header.extend(chunk[: 4096 - len(header)])
                    handle.write(chunk)
            if size == 0:
                raise ApiError(422, "empty_file", "Пустые файлы не поддерживаются.")
            _validate_magic(partial_path, extension, bytes(header))
            if extension in {"zip", "docx"}:
                _validate_zip(partial_path, require_docx=extension == "docx")
            partial_path.replace(final_path)
        except Exception:
            partial_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise

        archive_status: ArchiveState
        if extension == "zip":
            archive_status = "registered"
        elif extension == "rar":
            archive_status = "extraction_unsupported"
        else:
            archive_status = "not_archive"
        public = LiveFileResponse(
            file_id=file_id,
            section_id=section_id,  # type: ignore[arg-type]
            display_filename=display_name,
            media_type=extension,  # type: ignore[arg-type]
            size_bytes=size,
            sha256=digest.hexdigest(),
            archive_status=archive_status,
        )
        record.total_size_bytes += size
        return _StoredFile(
            public=public,
            internal_path=f"input/{internal_name}",
            declared_content_type=upload.content_type,
        )

    def _write_request(self, record: _LiveJobRecord) -> None:
        payload = {
            "schema_version": "1.0",
            "mode": LIVE_MODE,
            "job_id": record.job_id,
            "project_id": record.project_id,
            "project_display_name": record.project_display_name,
            "sections": [section.model_dump(mode="json") for section in record.request.sections],
            "public_feedback": (
                record.request.public_feedback.model_dump(mode="json")
                if record.request.public_feedback is not None
                else None
            ),
            "limits": build_live_package_schema().upload_limits.model_dump(mode="json"),
            "files": [
                {
                    **item.public.model_dump(mode="json"),
                    "internal_path": item.internal_path,
                    "declared_content_type": item.declared_content_type,
                }
                for item in record.files
            ],
        }
        temp_path = record.workspace / "request.json.tmp"
        final_path = record.workspace / "request.json"
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temp_path, 0o600)
        temp_path.replace(final_path)

    def _progress_callback(
        self,
        record: _LiveJobRecord,
        state: str,
        progress: int,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if state not in _PROCESSING_STATES:
            raise ValueError(f"unsupported processing state: {state}")
        with record.lock:
            if record.cancel_requested.is_set():
                return
            self._append_event(
                record,
                state,  # type: ignore[arg-type]
                progress,
                operation,
                details,
            )

    def _run_processor(self, job_id: str) -> None:
        try:
            record = self._store.get_internal(job_id)
        except JobNotFoundError:
            return
        try:
            processing_module = importlib.import_module("dalel.api.live_processing")
            process_live_job = processing_module.process_live_job

            result = process_live_job(
                record.workspace,
                progress=lambda state, progress, operation, details=None: self._progress_callback(
                    record, state, progress, operation, details
                ),
                cancelled=record.cancel_requested.is_set,
            )
            with record.lock:
                if record.cancel_requested.is_set():
                    self._append_event(record, "cancelled", record.progress, "Задание отменено")
                    return
                archive_updates = (
                    result.get("archive_updates") if isinstance(result, dict) else None
                )
                if isinstance(archive_updates, dict):
                    allowed_archive_states = {
                        "registered",
                        "extracted",
                        "extraction_unsupported",
                        "extraction_failed",
                    }
                    for stored_file in record.files:
                        update = archive_updates.get(stored_file.public.file_id)
                        if isinstance(update, dict):
                            update = update.get("archive_status")
                        if (
                            isinstance(update, str)
                            and update in allowed_archive_states
                            and stored_file.public.media_type in {"zip", "rar"}
                        ):
                            stored_file.public = stored_file.public.model_copy(
                                update={"archive_status": update}
                            )
                safe_result = _public_payload(result)
                if not isinstance(safe_result, dict):
                    raise TypeError("live processor result must be a dictionary")
                safe_result.setdefault("visual_analysis_status", "not_available")
                safe_result.setdefault("geospatial_analysis_status", "not_available")
                safe_result.setdefault("generated_explanation", None)
                safe_result.setdefault("generation_status", "not_available")
                record.result = safe_result
                self._append_event(record, "completed", 100, "Анализ завершён")
        except Exception as exc:
            with record.lock:
                cancelled = record.cancel_requested.is_set() or type(exc).__name__ == (
                    "LiveProcessingCancelled"
                )
                if cancelled:
                    self._append_event(record, "cancelled", record.progress, "Задание отменено")
                else:
                    record.failure_code = "live_processing_failed"
                    record.limitations.append(
                        "Обработка не завершена; подготовленные демонстрационные"
                        " результаты не подставлялись."
                    )
                    self._append_event(
                        record,
                        "failed",
                        record.progress,
                        "Обработка завершилась ошибкой",
                    )
                    logger.error("live job %s failed (%s)", record.job_id, type(exc).__name__)
            if not cancelled:
                # Failed processing never retains user bytes. The authenticated
                # in-memory snapshot remains available until TTL for diagnosis.
                shutil.rmtree(record.workspace, ignore_errors=True)

    def _snapshot(self, record: _LiveJobRecord) -> LiveJobResponse:
        with record.lock:
            return LiveJobResponse(
                job_id=record.job_id,
                project_id=record.project_id,
                project_display_name=record.project_display_name,
                status=record.status,
                progress=record.progress,
                current_operation=record.current_operation,
                file_count=len(record.files),
                total_size_bytes=record.total_size_bytes,
                files=[item.public.model_copy(deep=True) for item in record.files],
                result=_public_payload(record.result),
                failure_code=record.failure_code,
                limitations=list(record.limitations),
            )

    @staticmethod
    def _not_found() -> ApiError:
        # Same response for absent, expired, and incorrect-token requests.
        return ApiError(404, "live_job_not_found", "Задание не найдено.")

    def get_job(self, job_id: str, access_token: str) -> LiveJobResponse:
        try:
            record = self._store.get(job_id, access_token)
        except JobNotFoundError as exc:
            raise self._not_found() from exc
        return self._snapshot(record)

    def get_events(self, job_id: str, access_token: str) -> LiveJobEventsResponse:
        try:
            record = self._store.get(job_id, access_token)
        except JobNotFoundError as exc:
            raise self._not_found() from exc
        with record.lock:
            return LiveJobEventsResponse(
                job_id=record.job_id,
                status=record.status,
                events=[event.model_copy(deep=True) for event in record.events],
            )

    def cancel_job(self, job_id: str, access_token: str) -> LiveJobResponse:
        try:
            record = self._store.get(job_id, access_token)
        except JobNotFoundError as exc:
            raise self._not_found() from exc
        with record.lock:
            record.cancel_requested.set()
            if record.status not in _TERMINAL_STATES:
                self._append_event(record, "cancelled", record.progress, "Запрошена отмена задания")
            snapshot = self._snapshot(record)
        with contextlib.suppress(JobNotFoundError):
            self._store.delete(job_id, access_token)
        return snapshot


_LIVE_MANAGER = LiveJobManager()


def get_live_job_manager() -> LiveJobManager:
    return _LIVE_MANAGER


def reset_live_jobs() -> None:
    _LIVE_MANAGER.reset()


def force_live_job_cleanup() -> int:
    return _LIVE_MANAGER.force_cleanup()


async def parse_live_request(raw_request: str) -> LiveJobRequest:
    """Parse the JSON form field without reflecting parser internals to users."""
    try:
        loaded = await asyncio.to_thread(json.loads, raw_request)
        return LiveJobRequest.model_validate(loaded)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ApiError(
            422,
            "invalid_live_request",
            "Поле request содержит некорректное описание пакета.",
        ) from exc
