"""Structured environmental dossier: schema, prepared manifests, reconciliation.

A public-hearing submission is not a flat file list — it is a dossier with
sections that differ in purpose, multiplicity and processing support. This
module owns:

- the canonical section schema (``DOSSIER_SECTIONS``) shared by the API and
  the upload UI;
- loading of versioned, safe prepared-demo manifests
  (``demo_manifests/<project_id>.json``) that describe the FULL official
  source package of a demo project — including files that exist only on the
  official portal;
- reconciliation of that manifest against the accepted curated dataset and
  P1–P4/Meta artifacts, so every displayed file carries an honest state
  (``analyzed`` / ``supporting_only`` / ``official_only`` / …) that is
  COMPUTED, never hardcoded.

Safety invariants (enforced by tests):
- no absolute paths, no ``data/raw`` paths, no private surnames from source
  filenames, no personal contact data in any manifest or response;
- analytical numbers (scores, finding counts) never live here — they come
  from the accepted artifact store;
- a file is presented as analyzed ONLY if the curated dataset and pillar
  artifacts actually reference it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from dalel.api.repository import ArtifactStore
from dalel.api.services import document_type_label, project_display_name

logger = logging.getLogger("dalel.api")

# --- canonical section schema -------------------------------------------------

SectionId = Literal[
    "project_documents",
    "media_publication",
    "notice_boards",
    "hearing_protocol",
    "public_feedback",
]

RequirementLevel = Literal[
    "required",
    "conditionally_required",
    "recommended",
    "optional",
    "external_source",
]

SourceOrigin = Literal["official_portal", "local_raw", "extracted_archive", "user_upload"]

ArchiveStatus = Literal["not_archive", "registered", "extracted", "extraction_unsupported"]

ReconciledStatus = Literal[
    "analyzed",
    "curated",
    "supporting_only",
    "extracted",
    "available_raw",
    "official_only",
    "unavailable",
    "unsupported_archive",
    "excluded_with_reason",
]

# Honest per-state labels. Deliberately NOT legal wording: registration and
# analysis coverage, never "юридическая комплектность".
RECONCILED_STATUS_LABELS: dict[str, str] = {
    "analyzed": "Включён в детальный анализ",
    "curated": "Подготовлен к анализу",
    "supporting_only": "Подтверждающий материал",
    "extracted": "Архив распакован",
    "available_raw": "Доступен локально",
    "official_only": "Зарегистрирован на официальном портале · нет локальной копии",
    "unavailable": "Недоступен",
    "unsupported_archive": "Формат архива не поддерживается",
    "excluded_with_reason": "Не включён в демонстрационный анализ",
}

REQUIREMENT_LABELS: dict[str, str] = {
    "required": "Ожидается для этого типа пакета",
    "conditionally_required": "Обычно присутствует в пакете слушаний · требует экспертной проверки",
    "recommended": "Рекомендуется для полноты пакета",
    "optional": "Дополнительный материал",
    "external_source": "Структурированные данные официального источника",
}

# Subtypes beyond the curated document types (which stay in
# ``services._DOCUMENT_TYPE_LABELS``): dossier roles seen on the official
# hearing portals.
_EXTRA_SUBTYPE_LABELS: dict[str, str] = {
    "authority_decision": "Решение уполномоченного органа",
    "newspaper_publication": "Газетная публикация",
    "publication_screenshot": "Скриншот публикации",
    "publication_certificate": "Справка о публикации",
    "notice_board_photo": "Фото объявления на доске",
    "hearing_protocol": "Протокол слушаний",
    "calculations": "Расчёты",
    "drawings": "Чертежи и схемы",
    "project_decision": "Проектные решения",
    "supplementary": "Дополнительный технический документ",
}


def subtype_label(value: str | None) -> str | None:
    if not value:
        return None
    return _EXTRA_SUBTYPE_LABELS.get(value) or document_type_label(value) or value


class DossierSectionDefinition(BaseModel):
    """Static definition of one dossier section (config, not data)."""

    model_config = ConfigDict(extra="forbid")

    section_id: SectionId
    order: int
    title_ru: str
    purpose: str
    requirement_level: RequirementLevel
    requirement_label: str
    accepted_formats: list[str]
    multiplicity_label: str
    min_expected_files: int
    upload_enabled: bool
    # Pillars that consume this section TODAY (accepted artifacts only).
    pillar_relevance: list[str]
    # Reserved future consumer (P5 visual evidence), never presented as active.
    future_pillar: str | None = None


DOSSIER_SECTIONS: tuple[DossierSectionDefinition, ...] = (
    DossierSectionDefinition(
        section_id="project_documents",
        order=1,
        title_ru="Проектная документация",
        purpose=(
            "Электронная версия проекта: пояснительная записка, раздел ООС/ОВОС,"
            " расчёты, чертежи, проектные решения и решения уполномоченного органа."
        ),
        requirement_level="required",
        requirement_label=REQUIREMENT_LABELS["required"],
        accepted_formats=["pdf", "docx"],
        multiplicity_label="Один или несколько файлов",
        min_expected_files=1,
        upload_enabled=True,
        pillar_relevance=["P1", "P2", "P3", "P4"],
    ),
    DossierSectionDefinition(
        section_id="media_publication",
        order=2,
        title_ru="Подтверждение публикации в СМИ",
        purpose=(
            "Материалы, подтверждающие публикацию объявления о слушаниях в СМИ:"
            " газетная полоса, скриншот или справка о публикации."
        ),
        requirement_level="conditionally_required",
        requirement_label=REQUIREMENT_LABELS["conditionally_required"],
        accepted_formats=["pdf", "jpg", "jpeg", "png"],
        multiplicity_label="Ноль или несколько файлов",
        min_expected_files=0,
        upload_enabled=True,
        pillar_relevance=[],
        future_pillar="P5",
    ),
    DossierSectionDefinition(
        section_id="notice_boards",
        order=3,
        title_ru="Объявления на информационных досках",
        purpose="Фотофиксация объявлений о слушаниях на информационных досках и стендах.",
        requirement_level="conditionally_required",
        requirement_label=REQUIREMENT_LABELS["conditionally_required"],
        accepted_formats=["pdf", "jpg", "jpeg", "png"],
        multiplicity_label="Ноль или несколько файлов",
        min_expected_files=0,
        upload_enabled=True,
        pillar_relevance=[],
        future_pillar="P5",
    ),
    DossierSectionDefinition(
        section_id="hearing_protocol",
        order=4,
        title_ru="Протокол общественных слушаний",
        purpose=(
            "Протокол публичных слушаний или обсуждений — отдельным файлом либо архивом"
            " с языковыми версиями."
        ),
        requirement_level="conditionally_required",
        requirement_label=REQUIREMENT_LABELS["conditionally_required"],
        accepted_formats=["pdf", "docx", "zip", "rar"],
        multiplicity_label="Ноль или несколько файлов",
        min_expected_files=0,
        upload_enabled=True,
        pillar_relevance=[],
    ),
    DossierSectionDefinition(
        section_id="public_feedback",
        order=5,
        title_ru="Вопросы, предложения и ответы общественности",
        purpose=(
            "Структурированные вопросы, предложения и ответы участников слушаний."
            " Загружаются не файлом, а из официального источника."
        ),
        requirement_level="external_source",
        requirement_label=REQUIREMENT_LABELS["external_source"],
        accepted_formats=[],
        multiplicity_label="Структурированные записи официального источника",
        min_expected_files=0,
        upload_enabled=False,
        pillar_relevance=[],
    ),
)

SECTION_BY_ID: dict[str, DossierSectionDefinition] = {
    definition.section_id: definition for definition in DOSSIER_SECTIONS
}

_ARCHIVE_FORMATS = {"rar", "zip"}


# --- prepared manifest (versioned safe config on disk) -------------------------


class OfficialSourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portal_name: str
    hearing_registration_number: str | None = None
    hearing_method_label: str | None = None
    hearing_period_label: str | None = None
    initiator_type_label: str | None = None
    region_label: str | None = None
    official_title: str | None = None
    source_url: str | None = None
    official_categories: list[str] = []
    verified_at: str | None = None


class PreparedDocument(BaseModel):
    """One source material of the prepared demo package (safe fields only)."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str
    section_id: SectionId
    official_category: str | None = None
    safe_display_name: str
    # Original filename ONLY when it is explicitly public AND free of personal
    # data; source filenames with private surnames stay null.
    original_name: str | None = None
    subtype: str | None = None
    media_type: str
    official_size_label: str | None = None
    source_origin: SourceOrigin
    official_source_registered: bool
    local_available: bool
    archive_status: ArchiveStatus = "not_archive"
    extracted_from: str | None = None
    curated_document_id: str | None = None
    label_source_document_id: str | None = None
    supporting_evidence_only: bool = False
    missing_reason: str | None = None
    provenance_reference: str | None = None
    limitations: list[str] = []
    eligible_for_p5: bool = False
    visual_media_type: str | None = None


class PublicFeedbackInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registered_in_official_source: bool
    official_heading: str | None = None
    submission_count: int
    question_count: int
    response_status: Literal["registered_not_verified", "present", "absent"]
    submitted_at_label: str | None = None
    provenance_reference: str | None = None
    included_in_analysis: bool
    note: str


class PreparedManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str
    demo_project_id: str
    official_source: OfficialSourceInfo
    location_reference_status: str
    geospatial_analysis_status: str
    documents: list[PreparedDocument]
    public_feedback: PublicFeedbackInfo | None = None


_MANIFEST_DIR = Path(__file__).resolve().parent / "demo_manifests"


def load_prepared_manifest(project_id: str) -> PreparedManifest | None:
    """Load the versioned prepared manifest for ``project_id`` if one exists.

    Invalid manifests degrade to ``None`` (the API falls back to the curated
    dossier view) — they never crash the demo path or leak parser errors.
    """
    path = _MANIFEST_DIR / f"{project_id}.json"
    if not path.is_file():
        return None
    try:
        return PreparedManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError):
        logger.exception("invalid prepared demo manifest for %s", project_id)
        return None


# --- reconciled response models -------------------------------------------------


class DossierDocument(BaseModel):
    """A source material with its honest, reconciled processing state."""

    model_config = ConfigDict(extra="forbid")

    document_id: str  # manifest id (or synthetic id for curated/user files)
    curated_document_id: str | None = None
    section_id: SectionId
    official_category: str | None = None
    safe_display_name: str
    original_name: str | None = None
    subtype: str | None = None
    subtype_label: str | None = None
    media_type: str
    size_label: str | None = None
    source_origin: SourceOrigin
    official_source_registered: bool
    local_available: bool
    archive_status: ArchiveStatus
    extracted_from: str | None = None
    text_extracted: bool
    page_count: int | None = None
    curated: bool
    analyzed_by: list[str]
    meta_evidence: bool
    registered_label_source: bool
    supporting_evidence_only: bool
    reconciled_status: ReconciledStatus
    status_label: str
    missing_reason: str | None = None
    provenance_reference: str | None = None
    limitations: list[str]
    # P5 readiness (visual evidence) — registered, never presented as active.
    eligible_for_p5: bool
    visual_media_type: str | None = None
    visual_analysis_status: Literal["not_available"] = "not_available"


class DossierSectionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    official_registered: int
    local_available: int
    analyzed: int
    supporting: int
    official_only: int
    user_supplied: int
    coverage_state: Literal[
        "included_in_analysis",
        "local_materials",
        "official_only",
        "external_registered",
        "empty",
    ]
    status_note: str


class DossierSectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: DossierSectionDefinition
    status: DossierSectionStatus
    documents: list[DossierDocument]


class PackageCompleteness(BaseModel):
    """Computed material counts. Analysis completeness — never a legal verdict."""

    model_config = ConfigDict(extra="forbid")

    heading: str = "Комплектность материалов для анализа"
    official_registered_total: int
    locally_available_total: int
    extracted_total: int
    analyzed_total: int
    supporting_total: int
    official_only_total: int
    user_supplied_total: int
    sections_total: int
    sections_with_materials: int


class AnalysisCoverageRecord(BaseModel):
    """One row of the document → pillar coverage matrix."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    safe_display_name: str
    section_id: SectionId
    section_title: str
    prepared: bool
    p1: bool
    p2: bool
    p3: bool
    p4: bool
    meta_evidence: bool
    limitation: str | None = None


class PublicFeedbackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registered_in_official_source: bool
    official_heading: str | None = None
    submission_count: int
    question_count: int
    responses_status_label: str
    submitted_at_label: str | None = None
    provenance_reference: str | None = None
    included_in_analysis: bool
    feeds_pillars: list[str]
    note: str


class DossierProjectIdentity(BaseModel):
    """Section 0 — project identity. Never an upload slot."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    display_name: str
    official_title: str | None = None
    hearing_registration_number: str | None = None
    project_type_label: str | None = None
    region_label: str | None = None
    initiator_type_label: str | None = None
    hearing_method_label: str | None = None
    hearing_period_label: str | None = None
    portal_name: str | None = None
    source_url: str | None = None
    official_source_verified_at: str | None = None
    # P6 readiness (geospatial context) — registered, never presented as active.
    location_reference_status: str = "not_registered"
    geospatial_analysis_status: str = "not_available"
    eligible_for_p6: bool = False


class DossierManifestResponse(BaseModel):
    """The prepared dossier with reconciled per-file states."""

    model_config = ConfigDict(extra="forbid")

    demo_project_id: str
    project_name: str
    manifest_version: str
    prepared: bool  # true when a versioned prepared manifest backs this view
    identity: DossierProjectIdentity
    sections: list[DossierSectionView]
    public_feedback: PublicFeedbackSummary | None = None
    completeness: PackageCompleteness
    coverage_matrix: list[AnalysisCoverageRecord]
    limitations: list[str]


class DossierSchemaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    sections: list[DossierSectionDefinition]


def build_dossier_schema_response() -> DossierSchemaResponse:
    return DossierSchemaResponse(sections=list(DOSSIER_SECTIONS))


# --- reconciliation ---------------------------------------------------------------

_RESPONSES_STATUS_LABELS: dict[str, str] = {
    "registered_not_verified": "Раздел ответа зарегистрирован · содержание не проверено",
    "present": "Ответы опубликованы",
    "absent": "Ответы не опубликованы",
}


def _pillar_ids_for_document(store: ArtifactStore, curated_document_id: str) -> list[str]:
    """Pillars whose accepted artifacts actually scored this document."""
    analyzed: list[str] = []
    for key in ("p1", "p2", "p3", "p4"):
        pillar = store.pillars.get(key)
        if pillar is None or not pillar.available:
            continue
        if curated_document_id in pillar.document_scores:
            analyzed.append(pillar.descriptor.pillar_id)
    return analyzed


def _registered_label_source(
    store: ArtifactStore, project_id: str, label_source_document_id: str | None
) -> bool:
    if not label_source_document_id:
        return False
    project = store.project(project_id)
    if project is None:
        return False
    registered = project.get("label_source_document_ids") or []
    return label_source_document_id in {str(item) for item in registered}


def _reconciled_status(document: DossierDocument, excluded: bool) -> ReconciledStatus:
    if excluded:
        return "excluded_with_reason"
    if document.curated and document.analyzed_by:
        return "analyzed"
    if document.curated:
        return "curated"
    is_archive = document.media_type in _ARCHIVE_FORMATS
    if is_archive and document.archive_status == "extraction_unsupported":
        return "unsupported_archive"
    if is_archive and document.archive_status == "extracted":
        return "extracted"
    if document.supporting_evidence_only and document.local_available:
        return "supporting_only"
    if document.local_available:
        return "available_raw"
    if document.official_source_registered:
        return "official_only"
    return "unavailable"


def reconcile_document(
    store: ArtifactStore, project_id: str, prepared: PreparedDocument
) -> DossierDocument:
    """Compute the honest processing state of one prepared source material.

    ``curated``/``analyzed_by``/``meta_evidence`` are derived from the
    accepted artifact store — a stale ``curated_document_id`` in the manifest
    degrades to "not curated" with a limitation instead of a false claim.
    """
    curated_record: dict[str, Any] | None = None
    limitations = list(prepared.limitations)
    if prepared.curated_document_id:
        curated_record = store.document(prepared.curated_document_id)
        if curated_record is None:
            limitations.append(
                "Ссылка на подготовленный документ не найдена в curated-наборе:"
                " материал показан как неподготовленный."
            )
    curated = curated_record is not None
    analyzed_by = (
        _pillar_ids_for_document(store, prepared.curated_document_id)
        if curated and prepared.curated_document_id
        else []
    )
    meta_evidence = bool(analyzed_by) and store.meta.assessment(project_id) is not None
    page_count: int | None = None
    if curated_record is not None:
        raw_pages = curated_record.get("page_count")
        page_count = int(raw_pages) if raw_pages else None

    document = DossierDocument(
        document_id=prepared.manifest_id,
        curated_document_id=prepared.curated_document_id if curated else None,
        section_id=prepared.section_id,
        official_category=prepared.official_category,
        safe_display_name=prepared.safe_display_name,
        original_name=prepared.original_name,
        subtype=prepared.subtype,
        subtype_label=subtype_label(prepared.subtype),
        media_type=prepared.media_type,
        size_label=prepared.official_size_label,
        source_origin=prepared.source_origin,
        official_source_registered=prepared.official_source_registered,
        local_available=prepared.local_available,
        archive_status=prepared.archive_status,
        extracted_from=prepared.extracted_from,
        text_extracted=curated,
        page_count=page_count,
        curated=curated,
        analyzed_by=analyzed_by,
        meta_evidence=meta_evidence,
        registered_label_source=_registered_label_source(
            store, project_id, prepared.label_source_document_id
        ),
        supporting_evidence_only=prepared.supporting_evidence_only,
        reconciled_status="unavailable",  # recomputed below
        status_label="",
        missing_reason=prepared.missing_reason,
        provenance_reference=prepared.provenance_reference,
        limitations=limitations,
        eligible_for_p5=prepared.eligible_for_p5,
        visual_media_type=prepared.visual_media_type,
    )
    status = _reconciled_status(document, excluded=False)
    return document.model_copy(
        update={"reconciled_status": status, "status_label": RECONCILED_STATUS_LABELS[status]}
    )


def _curated_fallback_documents(store: ArtifactStore, project_id: str) -> list[DossierDocument]:
    """Dossier view for projects WITHOUT a prepared manifest.

    Built purely from the curated dataset: every curated document is a
    project-documentation entry; nothing about official portal categories is
    invented for unverified projects.
    """
    documents: list[DossierDocument] = []
    for record in store.project_documents(project_id):
        document_id = str(record["document_id"])
        analyzed_by = _pillar_ids_for_document(store, document_id)
        doc_type = str(record.get("document_type") or "")
        raw_pages = record.get("page_count")
        document = DossierDocument(
            document_id=document_id,
            curated_document_id=document_id,
            section_id="project_documents",
            official_category=None,
            safe_display_name=document_type_label(doc_type) or doc_type or document_id,
            original_name=None,
            subtype=doc_type or None,
            subtype_label=subtype_label(doc_type),
            media_type=str(record.get("file_format") or "pdf"),
            size_label=None,
            source_origin="local_raw",
            official_source_registered=False,
            local_available=True,
            archive_status="not_archive",
            extracted_from=None,
            text_extracted=True,
            page_count=int(raw_pages) if raw_pages else None,
            curated=True,
            analyzed_by=analyzed_by,
            meta_evidence=bool(analyzed_by) and store.meta.assessment(project_id) is not None,
            registered_label_source=False,
            supporting_evidence_only=False,
            reconciled_status="unavailable",
            status_label="",
            missing_reason=None,
            provenance_reference=f"curated:{store.dataset_version}",
            limitations=[],
            eligible_for_p5=False,
            visual_media_type=None,
        )
        status = _reconciled_status(document, excluded=False)
        documents.append(
            document.model_copy(
                update={
                    "reconciled_status": status,
                    "status_label": RECONCILED_STATUS_LABELS[status],
                }
            )
        )
    return documents


def _section_status(
    definition: DossierSectionDefinition,
    documents: list[DossierDocument],
    feedback: PublicFeedbackSummary | None,
) -> DossierSectionStatus:
    analyzed = sum(1 for d in documents if d.reconciled_status == "analyzed")
    supporting = sum(
        1 for d in documents if d.reconciled_status in ("supporting_only", "extracted")
    )
    official_only = sum(1 for d in documents if d.reconciled_status == "official_only")
    user_supplied = sum(1 for d in documents if d.source_origin == "user_upload")
    local_available = sum(1 for d in documents if d.local_available)

    if definition.section_id == "public_feedback":
        registered = feedback is not None and feedback.registered_in_official_source
        return DossierSectionStatus(
            total=0,
            official_registered=0,
            local_available=0,
            analyzed=0,
            supporting=0,
            official_only=0,
            user_supplied=0,
            coverage_state="external_registered" if registered else "empty",
            status_note=(
                "Зарегистрировано в официальном источнике"
                if registered
                else "Записи не найдены в официальном источнике"
            ),
        )

    if analyzed > 0:
        coverage_state: Literal[
            "included_in_analysis",
            "local_materials",
            "official_only",
            "external_registered",
            "empty",
        ] = "included_in_analysis"
        note = "Включён в детальный анализ"
    elif local_available > 0 or user_supplied > 0:
        coverage_state = "local_materials"
        note = "Материалы доступны · вне текущего детального анализа"
    elif official_only > 0:
        coverage_state = "official_only"
        note = "Найдено в официальном источнике · не найдено в локальной копии"
    else:
        coverage_state = "empty"
        note = "Материалы не найдены"

    return DossierSectionStatus(
        total=len(documents),
        official_registered=sum(1 for d in documents if d.official_source_registered),
        local_available=local_available,
        analyzed=analyzed,
        supporting=supporting,
        official_only=official_only,
        user_supplied=user_supplied,
        coverage_state=coverage_state,
        status_note=note,
    )


def build_completeness(
    documents: list[DossierDocument], feedback: PublicFeedbackSummary | None
) -> PackageCompleteness:
    sections_with_materials = len({d.section_id for d in documents})
    if feedback is not None and feedback.registered_in_official_source:
        sections_with_materials += 1
    return PackageCompleteness(
        official_registered_total=sum(1 for d in documents if d.official_source_registered),
        locally_available_total=sum(1 for d in documents if d.local_available),
        extracted_total=sum(1 for d in documents if d.source_origin == "extracted_archive"),
        analyzed_total=sum(1 for d in documents if d.reconciled_status == "analyzed"),
        supporting_total=sum(
            1 for d in documents if d.reconciled_status in ("supporting_only", "extracted")
        ),
        official_only_total=sum(1 for d in documents if d.reconciled_status == "official_only"),
        user_supplied_total=sum(1 for d in documents if d.source_origin == "user_upload"),
        sections_total=len(DOSSIER_SECTIONS),
        sections_with_materials=sections_with_materials,
    )


def build_coverage_matrix(documents: list[DossierDocument]) -> list[AnalysisCoverageRecord]:
    records: list[AnalysisCoverageRecord] = []
    for document in documents:
        limitation = document.missing_reason or (
            document.limitations[0] if document.limitations else None
        )
        records.append(
            AnalysisCoverageRecord(
                document_id=document.document_id,
                safe_display_name=document.safe_display_name,
                section_id=document.section_id,
                section_title=SECTION_BY_ID[document.section_id].title_ru,
                prepared=document.curated,
                p1="P1" in document.analyzed_by,
                p2="P2" in document.analyzed_by,
                p3="P3" in document.analyzed_by,
                p4="P4" in document.analyzed_by,
                meta_evidence=document.meta_evidence,
                limitation=limitation,
            )
        )
    return records


def _feedback_summary(info: PublicFeedbackInfo | None) -> PublicFeedbackSummary | None:
    if info is None:
        return None
    return PublicFeedbackSummary(
        registered_in_official_source=info.registered_in_official_source,
        official_heading=info.official_heading,
        submission_count=info.submission_count,
        question_count=info.question_count,
        responses_status_label=_RESPONSES_STATUS_LABELS[info.response_status],
        submitted_at_label=info.submitted_at_label,
        provenance_reference=info.provenance_reference,
        included_in_analysis=info.included_in_analysis,
        feeds_pillars=[],
        note=info.note,
    )


def _identity(
    store: ArtifactStore, project_id: str, manifest: PreparedManifest | None
) -> DossierProjectIdentity:
    from dalel.api.services import industry_label

    project = store.project(project_id) or {}
    official = manifest.official_source if manifest is not None else None
    region = official.region_label if official is not None else None
    return DossierProjectIdentity(
        project_id=project_id,
        display_name=project_display_name(project_id),
        official_title=official.official_title if official is not None else None,
        hearing_registration_number=(
            official.hearing_registration_number if official is not None else None
        ),
        project_type_label=industry_label(str(project.get("industry") or "") or None),
        region_label=region or (str(project.get("region")) if project.get("region") else None),
        initiator_type_label=official.initiator_type_label if official is not None else None,
        hearing_method_label=official.hearing_method_label if official is not None else None,
        hearing_period_label=official.hearing_period_label if official is not None else None,
        portal_name=official.portal_name if official is not None else None,
        source_url=(
            (official.source_url if official is not None else None)
            or (str(project.get("source_url")) if project.get("source_url") else None)
        ),
        official_source_verified_at=official.verified_at if official is not None else None,
        location_reference_status=(
            manifest.location_reference_status if manifest is not None else "not_registered"
        ),
        geospatial_analysis_status=(
            manifest.geospatial_analysis_status if manifest is not None else "not_available"
        ),
        eligible_for_p6=manifest is not None
        and manifest.location_reference_status != "not_registered",
    )


def build_section_views(
    documents: list[DossierDocument], feedback: PublicFeedbackSummary | None
) -> list[DossierSectionView]:
    """Group reconciled documents into ordered section views (no silent drops:
    every document belongs to exactly one known section by schema)."""
    views: list[DossierSectionView] = []
    for definition in DOSSIER_SECTIONS:
        section_documents = [d for d in documents if d.section_id == definition.section_id]
        views.append(
            DossierSectionView(
                definition=definition,
                status=_section_status(definition, section_documents, feedback),
                documents=section_documents,
            )
        )
    return views


def build_dossier_manifest_response(
    store: ArtifactStore, project_id: str
) -> DossierManifestResponse:
    manifest = load_prepared_manifest(project_id)
    limitations: list[str] = []
    if manifest is not None:
        documents = [
            reconcile_document(store, project_id, prepared) for prepared in manifest.documents
        ]
        feedback = _feedback_summary(manifest.public_feedback)
        manifest_version = manifest.manifest_version
        limitations.append(
            "Состав официального пакета зафиксирован по официальной публичной странице"
            " слушаний; аналитические показатели берутся только из принятых артефактов."
        )
    else:
        documents = _curated_fallback_documents(store, project_id)
        feedback = None
        manifest_version = "curated-only"
        limitations.append(
            "Для проекта нет подготовленного манифеста официального пакета:"
            " показан только подготовленный curated-набор документов."
        )
    return DossierManifestResponse(
        demo_project_id=project_id,
        project_name=project_display_name(project_id),
        manifest_version=manifest_version,
        prepared=manifest is not None,
        identity=_identity(store, project_id, manifest),
        sections=build_section_views(documents, feedback),
        public_feedback=feedback,
        completeness=build_completeness(documents, feedback),
        coverage_matrix=build_coverage_matrix(documents),
        limitations=limitations,
    )
