"""Prepared-replay demo job layer: structured dossier -> animated analysis -> result.

This is explicitly NOT a real ingestion or analysis pipeline. Every job
replays the accepted P1-P4 and Meta artifacts of one configured demo
project (Bayterek by default) through the same normalized service-layer
builders the rest of the API uses. No uploaded file content is ever read,
transmitted, stored or analyzed here -- section assignments only carry
client-supplied display metadata (filename, size) so the dossier screen can
show a realistic package. Every metric in a stage comes from the real
artifact store; only stage order, status copy and prepared-manifest display
labels are presentation constants.

The dossier layer (``dalel.api.dossier``) reconciles the FULL official
source package against the curated dataset and pillar artifacts, so the
demo distinguishes three scopes honestly: the official package, the local
raw copy, and the analyzed subset.

Replay jobs are computed synchronously and kept in a bounded, authenticated
ephemeral store. Job identifiers and access tokens are independent 256-bit
random values; only a digest of the token is retained.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dalel.api.dossier import (
    SECTION_BY_ID,
    DossierDocument,
    DossierManifestResponse,
    build_dossier_manifest_response,
)
from dalel.api.errors import ApiError
from dalel.api.job_store import JobCapacityError, JobNotFoundError, SecureJobStore
from dalel.api.repository import ArtifactStore
from dalel.api.services import (
    build_meta_assessment,
    build_pillar_summary,
    project_display_name,
)

# --- configuration -------------------------------------------------------

# Explicit, configured demo project slug -- never resolved by matching a
# display name. Bayterek also happens to be the highest accepted Meta
# review-priority project in the current dataset; if a future dataset build
# ever drops this id, `_resolve_demo_project` falls back to the top-ranked
# project instead of failing the guaranteed demo path.
DEMO_PROJECT_ID = "project_003_bayterek"

DISCLAIMER = (
    "Демонстрационный запуск воспроизводит заранее рассчитанные результаты"
    " подготовленного проекта Bayterek."
)

# Completion-screen honesty note (see the dossier reconciliation): the score
# is built from the analyzed subset; the rest of the package is context.
ANALYSIS_SCOPE_NOTE = (
    "Итоговая оценка сформирована по документам, включённым в текущий доказательный анализ."
    " Остальные материалы зарегистрированы как контекст или подтверждающие доказательства."
)

_STATUS_MESSAGES: dict[str, tuple[str, ...]] = {
    "p0": (
        "Регистрируем материалы пакета…",
        "Проверяем разделы, форматы и дубликаты…",
        "Сверяем с официальным источником…",
    ),
    "p0_5": (
        "Классифицируем документы по разделам…",
        "Проверяем распаковку архивов…",
        "Извлекаем текст и страницы…",
        "Инициализируем провенанс документов…",
    ),
    "p1": (
        "Проверяем структуру страниц…",
        "Ищем пропуски и аномалии…",
        "Фиксируем замечания…",
    ),
    "p2": (
        "Извлекаем применимые требования…",
        "Сопоставляем доказательства…",
        "Формируем экспертные сигналы…",
    ),
    "p3": (
        "Извлекаем числовые показатели…",
        "Нормализуем единицы измерения…",
        "Сопоставляем значения…",
    ),
    "p4": (
        "Выделяем сущности проекта…",
        "Связываем сведения между документами…",
        "Проверяем идентичность и контекст…",
    ),
    "meta": (
        "Объединяем сигналы P1–P4…",
        "Оцениваем покрытие доказательств…",
        "Формируем объяснимый приоритет…",
    ),
}

# What each pillar DOES, one line, for the stage "operation" area.
_PILLAR_OPERATIONS: dict[str, str] = {
    "p1": (
        "Проверяет структурную полноту документов: ожидаемые разделы, пустые"
        " страницы, OCR-зависимость, повторы и аномалии."
    ),
    "p2": (
        "Сопоставляет применимые документы пакета с требованиями"
        " демонстрационного нормативного корпуса."
    ),
    "p3": (
        "Извлекает числовые показатели, нормализует единицы и сравнивает"
        " значения только при достаточном контексте."
    ),
    "p4": (
        "Связывает утверждения, сущности и сведения между документами и"
        " проверяет их согласованность."
    ),
}

_META_OPERATION = (
    "Объединяет сигналы P1–P4 с учётом покрытия доказательств в объяснимый приоритет проверки."
)

# User-facing Russian titles for Meta feature ids (§ presentation only:
# values and arithmetic come from the accepted artifacts unchanged; the raw
# feature id stays available as the metric's technical id).
FEATURE_TITLES_RU: dict[str, str] = {
    "p1_high_severity_findings": "Критичные структурные замечания",
    "p1_low_severity_rate": "Замечания низкой важности",
    "p1_medium_severity_rate": "Замечания средней важности",
    "p1_ocr_or_empty_page_rate": "Пустые страницы и зависимость от OCR",
    "p1_project_priority_signal": "Общий структурный сигнал пакета",
    "p1_structural_anomaly_rate": "Структурные аномалии документов",
    "p2_authoritative_coverage": "Покрытие нормативного корпуса",
    "p2_insufficient_evidence": "Недостаточно подтверждающих свидетельств",
    "p2_missing_document_cues": "Признаки отсутствующих документов",
    "p2_potential_conflicts": "Потенциальные нормативные несоответствия",
    "p2_retrieval_confidence": "Уверенность сопоставления требований",
    "p2_synthetic_info_notices": "Демонстрационные нормативные пометки",
    "p3_aggregation_mismatches": "Расхождения итоговых сумм",
    "p3_compared_candidate_rate": "Доля сопоставленных числовых пар",
    "p3_high_severity_findings": "Критичные числовые расхождения",
    "p3_medium_severity_findings": "Числовые расхождения средней важности",
    "p3_proven_conflicts": "Доказанные числовые противоречия",
    "p3_quantitative_mentions": "Плотность числовых показателей",
    "p3_suppressed_candidate_rate": "Исключённые сравнения без контекста",
    "p3_unresolved_context_findings": "Значения без ясного контекста",
    "p4_graph_evidence_rate": "Покрытие графа связей доказательствами",
    "p4_linked_document_rate": "Связанность документов пакета",
    "p4_medium_severity_findings": "Междокументные замечания средней важности",
    "p4_other_diagnostic_findings": "Прочие диагностические сигналы",
    "p4_proven_conflicts": "Доказанные междокументные противоречия",
    "p4_suppressed_comparison_rate": "Исключённые междокументные сравнения",
    "p4_unresolved_identity_findings": "Неподтверждённая идентичность объектов",
}

# Review-priority level, primary UI translation (§ raw level stays in
# technical id). Masculine forms agree with «приоритет/уровень».
PRIORITY_LEVEL_RU: dict[str, str] = {
    "low": "низкий",
    "moderate": "умеренный",
    "elevated": "повышенный",
    "high": "высокий",
}


def feature_title_ru(feature_name: str) -> str:
    return FEATURE_TITLES_RU.get(feature_name, feature_name)


def priority_level_ru(level: str) -> str:
    return PRIORITY_LEVEL_RU.get(level, level)


# --- request/response schemas -------------------------------------------------


class DemoJobRequest(BaseModel):
    """Immutable prepared replay request.

    ``extra='forbid'`` is the server-side boundary: legacy ``sections`` and
    ``selected_files`` payloads are rejected rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["prepared_replay"] = "prepared_replay"


class DemoStageMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    hint: str | None = None
    # Raw internal id (feature id, level code) for the technical-details
    # expander; never the primary label.
    technical_id: str | None = None


class DemoStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str
    pillar_id: str | None = None
    title: str
    status_messages: list[str]
    headline: str
    # Which dossier documents/sections feed this stage (display strings).
    inputs: list[str] = Field(default_factory=list)
    input_note: str | None = None
    # What the stage does, one line.
    operation: str | None = None
    metrics: list[DemoStageMetric] = Field(default_factory=list)
    warning: str | None = None
    empty_state: str | None = None
    limitations: str | None = None


class DemoJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    project_id: str
    project_name: str
    status: Literal["completed"] = "completed"
    mode: Literal["prepared_replay"] = "prepared_replay"
    disclaimer: str = DISCLAIMER
    analysis_scope_note: str = ANALYSIS_SCOPE_NOTE
    # Complete immutable prepared dossier; replay never merges user files.
    dossier: DossierManifestResponse
    registered_source_count: int
    locally_available_count: int
    analyzed_count: int
    uploaded_file_count: int
    uploaded_total_size_label: str
    stages: list[DemoStage]
    # Future AlemLLM slot: never populated today, never a hidden LLM call.
    generated_explanation: str | None = None
    generation_status: Literal["not_available"] = "not_available"
    limitations: list[str] = Field(default_factory=list)
    result_url: str


class DemoJobCreatedResponse(DemoJobResponse):
    """Creation-only credentials; GET snapshots never contain this token."""

    access_token: str


# --- helpers -----------------------------------------------------------------


def _resolve_demo_project(store: ArtifactStore, requested_id: str | None) -> dict[str, Any]:
    if requested_id is not None and requested_id != DEMO_PROJECT_ID:
        raise ApiError(
            404,
            "demo_project_not_found",
            "Подготовленная демонстрация доступна только для проекта Bayterek.",
        )
    project = store.project(DEMO_PROJECT_ID)
    if project is not None:
        return project
    raise ApiError(
        503,
        "demo_unavailable",
        "Подготовленные результаты проекта Bayterek недоступны.",
    )


# --- stages -----------------------------------------------------------------


def _all_documents(dossier: DossierManifestResponse) -> list[DossierDocument]:
    return [document for section in dossier.sections for document in section.documents]


def _stage_p0_intake(dossier: DossierManifestResponse) -> DemoStage:
    documents = _all_documents(dossier)
    completeness = dossier.completeness
    archives = [d for d in documents if d.media_type in ("rar", "zip")]
    metrics = [
        DemoStageMetric(
            label="Материалов зарегистрировано",
            value=str(len(documents)),
            hint="Полный подготовленный официальный пакет",
        ),
        DemoStageMetric(label="Доступно локально", value=str(completeness.locally_available_total)),
        DemoStageMetric(
            label="Разделов с материалами",
            value=f"{completeness.sections_with_materials} из {completeness.sections_total}",
        ),
        DemoStageMetric(label="Архивов", value=str(len(archives))),
        DemoStageMetric(
            label="Нет локальной копии",
            value=str(completeness.official_only_total),
            hint="Зарегистрированы на официальном портале",
        ),
    ]
    if completeness.user_supplied_total > 0:
        metrics.append(
            DemoStageMetric(
                label="Файлов пользователя", value=str(completeness.user_supplied_total)
            )
        )
    warning = None
    if completeness.official_only_total > 0:
        warning = (
            "Не найдено в локальной копии:"
            f" {completeness.official_only_total} из {len(documents)} материалов"
            " зарегистрированы только в официальном источнике."
        )
    return DemoStage(
        stage_id="p0",
        pillar_id="P0",
        title="Приём и комплектность пакета",
        status_messages=list(_STATUS_MESSAGES["p0"]),
        headline=(
            f"Пакет принят: {len(documents)} материалов ·"
            f" разделы {completeness.sections_with_materials}/{completeness.sections_total}"
        ),
        inputs=[
            SECTION_BY_ID[section.definition.section_id].title_ru for section in dossier.sections
        ],
        operation=(
            "Регистрирует все материалы пакета, проверяет разделы, форматы и дубликаты,"
            " сверяет состав с официальным источником."
        ),
        metrics=metrics,
        warning=warning,
    )


def _stage_p0_5_prepare(dossier: DossierManifestResponse) -> DemoStage:
    documents = _all_documents(dossier)
    completeness = dossier.completeness
    archives = [d for d in documents if d.media_type in ("rar", "zip")]
    extracted_archives = [d for d in archives if d.archive_status == "extracted"]
    curated_documents = [d for d in documents if d.curated]
    total_pages = sum(d.page_count or 0 for d in curated_documents)
    classified = [d for d in documents if d.subtype]
    with_provenance = [d for d in documents if d.provenance_reference]
    metrics = [
        DemoStageMetric(
            label="Классифицировано",
            value=f"{len(classified)} из {len(documents)}",
            hint="Типы документов по разделам досье",
        ),
        DemoStageMetric(
            label="Архивы распакованы",
            value=f"{len(extracted_archives)} из {len(archives)}" if archives else "—",
        ),
        DemoStageMetric(
            label="Текст извлечён",
            value=f"{len(curated_documents)} док. · {total_pages} стр.",
        ),
        DemoStageMetric(
            label="Провенанс инициализирован",
            value=f"{len(with_provenance)} из {len(documents)}",
        ),
        DemoStageMetric(
            label="К глубокому анализу",
            value=str(completeness.analyzed_total),
            hint="Документы, подготовленные для P1–P4",
        ),
    ]
    return DemoStage(
        stage_id="p0_5",
        pillar_id="P0.5",
        title="Подготовка и провенанс",
        status_messages=list(_STATUS_MESSAGES["p0_5"]),
        headline=(
            f"К доказательному анализу подготовлено {completeness.analyzed_total} из"
            f" {len(documents)} материалов"
        ),
        inputs=["Зарегистрированный пакет P0"],
        input_note=(
            "Полная регистрация пакета не равна покрытию глубокого анализа:"
            " подтверждающие материалы остаются контекстом."
        ),
        operation=(
            "Классифицирует документы, фиксирует состояние архивов, извлекает текст и"
            " страницы, инициализирует провенанс для доказательных ссылок."
        ),
        metrics=metrics,
    )


def _analyzed_input_labels(dossier: DossierManifestResponse) -> tuple[list[str], str]:
    documents = _all_documents(dossier)
    analyzed = [d for d in documents if d.reconciled_status == "analyzed"]
    labels = [d.safe_display_name for d in analyzed]
    note = (
        f"Только документы детального анализа ({len(analyzed)} из {len(documents)}"
        " материалов пакета)."
    )
    return labels, note


def _stage_pillar(
    store: ArtifactStore, project_id: str, key: str, dossier: DossierManifestResponse
) -> DemoStage | None:
    pillar = store.pillars.get(key)
    if pillar is None:
        return None
    summary = build_pillar_summary(store, pillar, project_id)
    metrics = [DemoStageMetric(label=m.label, value=m.value, hint=m.hint) for m in summary.metrics]
    if summary.score is not None:
        metrics.insert(
            0,
            DemoStageMetric(
                label=summary.score_label or "Приоритет проверки",
                value=f"{summary.score}/{summary.score_max}",
            ),
        )
    inputs, input_note = _analyzed_input_labels(dossier)
    if key == "p2":
        inputs = [*inputs, "Демонстрационный нормативный корпус"]
    if key == "p3":
        inputs = [f"Числовые утверждения: {label}" for label in inputs]
    if key == "p4":
        inputs = [f"Утверждения и сущности: {label}" for label in inputs]
    return DemoStage(
        stage_id=key,
        pillar_id=summary.pillar_id,
        title=summary.title,
        status_messages=list(_STATUS_MESSAGES[key]),
        headline=summary.headline,
        inputs=inputs,
        input_note=input_note,
        operation=_PILLAR_OPERATIONS.get(key),
        metrics=metrics,
        warning=summary.warning,
        empty_state=summary.empty_state,
        limitations=summary.limitations,
    )


def _stage_meta(store: ArtifactStore, project_id: str) -> DemoStage | None:
    meta = build_meta_assessment(store, project_id)
    if meta is None:
        return None
    top_factors = meta.top_positive_factors[:3]
    level_ru = priority_level_ru(meta.review_priority_level)
    metrics = [
        DemoStageMetric(label="Приоритет проверки", value=f"{meta.review_priority_score:g}/100"),
        DemoStageMetric(label="Уровень", value=level_ru, technical_id=meta.review_priority_level),
        DemoStageMetric(label="Покрытие доказательств", value=f"{meta.evidence_coverage:.0%}"),
        DemoStageMetric(label="Уверенность оценки", value=f"{meta.assessment_confidence:.0%}"),
    ]
    for factor in top_factors:
        metrics.append(
            DemoStageMetric(
                label=feature_title_ru(factor.feature_name),
                value=f"+{factor.contribution:g}",
                hint=factor.explanation or None,
                technical_id=f"{factor.pillar_id} · {factor.feature_name}",
            )
        )
    return DemoStage(
        stage_id="meta",
        pillar_id="META",
        title="Интегральная приоритетность проверки",
        status_messages=list(_STATUS_MESSAGES["meta"]),
        headline=f"Приоритет {meta.review_priority_score:g}/100 · уровень {level_ru}",
        inputs=["Сигналы P1–P4", "Покрытие доказательств", "Уверенность пилларов"],
        operation=_META_OPERATION,
        metrics=metrics,
        warning=meta.review_notice,
        limitations="; ".join(meta.limitations) if meta.limitations else None,
    )


def build_demo_stages(
    store: ArtifactStore, project: dict[str, Any], dossier: DossierManifestResponse
) -> list[DemoStage]:
    project_id = str(project["project_id"])
    stages = [
        _stage_p0_intake(dossier),
        _stage_p0_5_prepare(dossier),
    ]
    for key in ("p1", "p2", "p3", "p4"):
        stage = _stage_pillar(store, project_id, key, dossier)
        if stage is not None:
            stages.append(stage)
    meta_stage = _stage_meta(store, project_id)
    if meta_stage is not None:
        stages.append(meta_stage)
    return stages


# --- authenticated ephemeral job store --------------------------------------

_DEMO_JOB_TTL_SECONDS = int(os.environ.get("DALEL_DEMO_JOB_TTL_SECONDS", "1800"))
_DEMO_MAX_RETAINED_JOBS = int(os.environ.get("DALEL_DEMO_MAX_RETAINED_JOBS", "128"))
_DEMO_JOBS: SecureJobStore[DemoJobResponse] = SecureJobStore(
    prefix="demo",
    ttl_seconds=_DEMO_JOB_TTL_SECONDS,
    max_records=_DEMO_MAX_RETAINED_JOBS,
)


def reset_demo_jobs() -> None:
    """Testing hook: clear all authenticated replay snapshots."""
    _DEMO_JOBS.clear()


def force_demo_job_cleanup() -> int:
    """Deterministic testing/maintenance hook for TTL cleanup."""
    return _DEMO_JOBS.sweep_expired()


def build_demo_manifest_response(store: ArtifactStore) -> DossierManifestResponse:
    project = _resolve_demo_project(store, None)
    return build_dossier_manifest_response(store, str(project["project_id"]))


def create_demo_job(store: ArtifactStore, request: DemoJobRequest) -> DemoJobCreatedResponse:
    # Validating the model is the immutability gate; it carries no document
    # selection, reassignment, removal, or upload metadata.
    if request.mode != "prepared_replay":  # pragma: no cover - Literal validates first
        raise ApiError(422, "invalid_demo_mode", "Некорректный режим демонстрации.")
    project = _resolve_demo_project(store, None)
    project_id = str(project["project_id"])
    dossier = build_dossier_manifest_response(store, project_id)
    stages = build_demo_stages(store, project, dossier)
    limitations = list(dossier.limitations)

    def factory(job_id: str) -> DemoJobResponse:
        return DemoJobResponse(
            job_id=job_id,
            project_id=project_id,
            project_name=project_display_name(project_id),
            dossier=dossier,
            registered_source_count=dossier.completeness.official_registered_total,
            locally_available_count=dossier.completeness.locally_available_total,
            analyzed_count=dossier.completeness.analyzed_total,
            uploaded_file_count=0,
            uploaded_total_size_label="0 КБ",
            stages=stages,
            limitations=limitations,
            result_url=f"/projects/{project_id}",
        )

    try:
        job, credentials = _DEMO_JOBS.create(factory)
    except JobCapacityError as exc:
        raise ApiError(
            503,
            "demo_job_capacity_reached",
            "Хранилище временных демонстрационных запусков заполнено.",
        ) from exc
    return DemoJobCreatedResponse(
        **job.model_dump(mode="python"), access_token=credentials.access_token
    )


def get_demo_job(job_id: str, access_token: str) -> DemoJobResponse:
    try:
        return _DEMO_JOBS.get(job_id, access_token)
    except JobNotFoundError as exc:
        # Wrong tokens and absent/expired jobs are intentionally indistinguishable.
        raise ApiError(404, "demo_job_not_found", "Демонстрационный запуск не найден.") from exc
