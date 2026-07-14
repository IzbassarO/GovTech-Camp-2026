"""Curated dataset writers: JSON/JSONL, machine-readable schemas, dataset card.

All writers are byte-deterministic: fixed key order (model field order),
``ensure_ascii=False``, ``\\n`` newlines, no wall-clock timestamps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dalel.curation import CURATION_VERSION, DATASET_VERSION
from dalel.curation.schemas import (
    BuildReportModel,
    CuratedDocument,
    CuratedImageRecord,
    CuratedPageRecord,
    CuratedProject,
    CuratedSectionRecord,
    CuratedTableRecord,
    DatasetStatisticsModel,
    DocumentGroup,
    InputManifestEntry,
    WeakFindingRecord,
)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl_dicts(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


# The single source of truth for the distributed schema contract: the same
# production models validate records during build and validate-curated.
RECORD_MODELS: dict[str, type[Any]] = {
    "projects.jsonl": CuratedProject,
    "documents.jsonl": CuratedDocument,
    "pages.jsonl": CuratedPageRecord,
    "sections.jsonl": CuratedSectionRecord,
    "tables.jsonl": CuratedTableRecord,
    "images.jsonl": CuratedImageRecord,
    "weak_findings.jsonl": WeakFindingRecord,
    "document_groups.jsonl": DocumentGroup,
    "input_manifest.jsonl": InputManifestEntry,
    "build_report.json": BuildReportModel,
    "dataset_statistics.json": DatasetStatisticsModel,
}


def write_schema_description(path: Path) -> None:
    """Standalone machine-readable JSON Schema contract for every curated
    record type: generated model schemas + deterministic semantic
    augmentations (enums, patterns, table content rule, image coupling)."""
    from dalel.curation.schema_contract import SCHEMA_DIALECT, build_schema_contract

    payload: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "curation_version": CURATION_VERSION,
        "schema_dialect": SCHEMA_DIALECT,
        "notes": {
            "standalone_contract": (
                "Every schema below is a self-sufficient JSON Schema Draft 2020-12"
                " contract: a standard validator must reject semantically invalid"
                " records (wrong roles/statuses, empty tables, unmaterialized"
                " images, traversal paths) without any Pydantic runtime code."
                " The same production models plus the deterministic augmentation"
                " layer are used by validate-curated, so the distributed and"
                " enforced contracts are identical."
            ),
            "tables_contract": (
                "tables.jsonl: num_rows>=1, num_cols>=1, cells minItems 1 and at"
                " least one row containing a cell with non-whitespace content."
            ),
            "images_contract": (
                "images.jsonl: records carrying bytes (image_path != null) must"
                " pin the physical curated copy: curated_image_path,"
                " image_sha256 (^[0-9a-f]{64}$) and image_size_bytes >= 1."
            ),
            "checksums": (
                "checksums.jsonl lines: {file, size_bytes, sha256[, records]} for"
                " every dataset file except checksums.jsonl itself; sha256 is"
                " SHA-256 over file bytes."
            ),
        },
        "files": build_schema_contract(),
    }
    write_json(path, payload)


def write_label_schema(path: Path) -> None:
    payload: dict[str, Any] = {
        "label_layer": "weak_findings.jsonl",
        "semantics": (
            "Weak supervision candidates derived from post-review documents"
            " (hearing protocols, motivated refusals). They are NOT gold labels:"
            " confidence is 'weak', expert_verified is false and review_status is"
            " not_expert_verified until an environmental expert reviews them."
        ),
        "leakage_policy": (
            "Post-review document text must never enter the feature layer"
            " (pages/sections/tables/images). Weak findings may reference"
            " post-review sources by document_id/path/page and carry short"
            " evidence quotes only."
        ),
        "known_quality_limitations": [
            "Bayterek RU/KK protocol tables are visibly OCR-corrupted and must not"
            " be used as reliable structured label sources without manual review",
            "EasyOCR does not support Kazakh; kk material was recognized ru+en",
        ],
        "schema": WeakFindingRecord.model_json_schema(),
    }
    write_json(path, payload)


def render_dataset_card(statistics: dict[str, Any], build_report: dict[str, Any]) -> str:
    counts = statistics["counts"]
    proposal = statistics["split_proposal"]
    fingerprint = str(build_report["input_fingerprint"])
    return f"""# DALEL Eco — Curated Dataset {DATASET_VERSION}

Curation version: {CURATION_VERSION} · Input fingerprint: `{fingerprint}`
(алгоритм `dalel-input-inventory/v2`: SHA-256 над явным inventory upstream-файлов,
которые builder реально читает — manifest, processed model inputs c изображениями,
label-source table-gate, исходные weak findings, source metadata; полный список —
`input_manifest.jsonl`. Downstream-артефакты — data/curated, data/results,
p1_review_template — в fingerprint не входят по построению, поэтому запуск P1 его
не меняет. Одинаковые входы ⇒ побайтно одинаковый датасет; timestamps в
versioned-артефакты не входят).

## Назначение

Evidence-первичный curated-слой для разработки детерминированных и ML-модулей
предварительной проверки экологической документации (Phase 1+). Источник —
проверенный Phase 0 ingestion corpus; предназначен для structural/quality
анализа документов, НЕ для обучения финальной risk-модели (см. ограничения).

## Источники

Публичные материалы карточек общественных слушаний Национального банка данных
экологии Казахстана (hearings.ndbecology.gov.kz), обработанные локальным
Phase 0 pipeline (Docling 2.112.0 + EasyOCR ru+en). Canonical manifest:
`data/manifests/projects.jsonl`. Исходные файлы неизменны (SHA-256 проверены).

## Состав

- Проектов: {counts["projects"]} · Документов (model inputs): {counts["documents"]}
- Страниц: {counts["pages"]} · Секций: {counts["sections"]}
- Таблиц (валидных): {counts["tables"]} · Изображений: {counts["images"]}
  (физических файлов внутри датасета: {counts["physical_images"]}, SHA-256 в записях)
- Weak findings: {counts["weak_findings"]} · OCR-страниц: {counts["ocr_pages"]}
- Пропущенных пустых table items (ingestion): {counts["skipped_empty_table_items"]}

Document types: {", ".join(f"{k}={v}" for k, v in statistics["by_document_type"].items())}
Языки: {", ".join(statistics["languages"])} · Регионы: {", ".join(statistics["regions"])}
Отрасли: {", ".join(statistics["industries"])}
Ingestion schemas: {
        ", ".join(f"{k}: {v} док." for k, v in statistics["by_ingestion_schema"].items())
    }

## Самодостаточность

Все image bytes скопированы внутрь датасета (`images/<project>/<document>/…`),
записи содержат `curated_image_path`, `image_sha256`, `image_size_bytes` и
provenance `source_image_path`; `checksums.jsonl` покрывает каждый файл датасета,
включая изображения. Датасет переносим без `data/processed`.

## Слои и leakage policy

- **Feature layer** (pages/sections/tables/images): только pre-review
  model inputs (`role=model_input`, `use_as_model_feature=true`).
- **Label layer** (weak_findings.jsonl): weak-кандидаты из post-review
  источников; текст post-review документов в feature layer не входит.
- Минимальная единица любого будущего split — проект (`document_groups.jsonl`).
- Weak labels НЕ являются gold labels (`expert_verified=false`).

## Mixed-schema normalization

Корпус содержит ingestion schemas 1.0.0 (без table counters) и 1.1.0.
Для 1.0.0 counters выведены явно: serialized = фактические записи tables.jsonl,
detected = serialized, skipped = 0, warning `legacy_report_counters_inferred`.
Processed reports не переписывались; каждая curated document record хранит
source schema version, normalization version и применённые нормализации.

## Table validity policy

Каждая таблица удовлетворяет контракту: num_rows>0, num_cols>0, непустые cells,
≥1 непустая ячейка после trim. Контракт повторно применён builder-ом ко всем
{statistics["table_validation"]["checked_records"]} serialized-записям обоих
processed-деревьев: invalid = {statistics["table_validation"]["invalid_records"]}.
Любая invalid таблица останавливает build (exit 1) до записи чего-либо.

## Schema contract

`schema.json` содержит полноценные JSON Schemas (Pydantic `model_json_schema()`)
для всех 10 типов записей; те же модели валидируют записи при build и в
`validate-curated`.

## OCR limitations

- EasyOCR не поддерживает казахский; kk-материалы распознаны ru+en.
- 16 страниц корпуса (10 в model inputs) без пригодного текста — векторные
  карты/схемы и почти пустые страницы; отражено в warnings и page-полях.
- OCR label-source таблиц (протоколы Bayterek) видимо повреждён — не
  использовать как надёжные structured labels без ручной проверки.

## Weak-label limitations

5 findings из одного проекта (AZM), выведены из признаний в протоколе слушаний;
не проверены экспертом; покрывают только один тип документа (НДВ). Нельзя
использовать как gold evaluation set.

## Known confounders

{chr(10).join("- " + c for c in proposal["known_confounders"])}

## Grouping / split

{proposal["reason"]}
Предложение: leave-one-project-out CV (см. dataset_statistics.json →
split_proposal). Финальный train/test split НЕ создан.

## Licenses / terms

Исходные документы — публичные материалы общественных слушаний; условия
повторного распространения порталом явно не зафиксированы (см.
DATASET_PREFLIGHT_AUDIT). До выяснения — только внутреннее использование,
raw/derived файлы не публиковать.

## Prohibited uses

- Обучение/оценка «модели нарушений» с заявленными метриками на 4 проектах.
- Использование weak findings как gold labels.
- Включение post-review текста в model features.
- Автоматические юридические выводы о нарушениях (структурные findings —
  только приоритизация ручной проверки).

## Ethical limitations

Документы содержат наименования компаний и ФИО должностных/физических лиц из
публичных источников; агрегаты и модели не должны использоваться для оценки
персон. Выводы системы — не юридическая оценка.

## Versioning

Dataset {DATASET_VERSION}; curation {CURATION_VERSION}; ingestion schemas
1.0.0/1.1.0 (см. by_ingestion_schema). Изменение contract/normalization
обязано инкрементировать curation version.

## Reproduction

```bash
uv run dalel curate --input data/processed --output data/curated/v1 --force
uv run dalel validate-curated --dataset data/curated/v1
```
"""
