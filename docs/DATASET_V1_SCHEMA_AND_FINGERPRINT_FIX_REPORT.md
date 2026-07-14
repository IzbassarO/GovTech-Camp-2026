# Dataset v1 — Schema Contract & Input Fingerprint Fix Report

Дата: 2026-07-14
Вход: `docs/DATASET_V1_AND_P1_REVERIFICATION.md` (VERIFICATION FAILED — два
оставшихся blocker Dataset v1; P1 fixes подтверждены). Исправлены оба.
`data/raw`, `data/processed`, манифесты, исходные weak findings и verification
reports не изменялись; git commit/push не выполнялись; P3 не начинался.

## 1. Root causes

**A. Schema contract.** `schema.json` генерировался чистым `model_json_schema()`:
Pydantic не кодирует model-validators и не имел Literal/pattern-ограничений на
ключевых полях. Стандартный Draft 2020-12 validator принимал таблицы без
dimensions/cells, изображения без materialization-метаданных,
`role=label_source` в feature-документе и `build_report.status=banana`.

**B. Fingerprint.** `compute_input_fingerprint` хешировал `annotations_root`
широким `rglob`, захватывая downstream-артефакт
`data/annotations/p1_review_template.jsonl`; запуск P1 менял template → прежний
fingerprint `7f9fde0f…` перестал воспроизводиться (пересчёт давал `92e98e6b…`).

## 2. Standalone schema contract (blocker A)

Двухслойное решение, единое для build/validate/distribution:

1. **Ужесточённые production-модели** (`curation/schemas.py`): Literal-enums
   (`role="model_input"`, `label_timing`, `extraction_status∈{success,partial}`,
   `file_format∈{pdf,docx}`, `parser_name`, `document_type` (16), weak-finding
   `confidence="weak"`/`expert_verified=false`/`review_status`,
   `build_report.status`, `fingerprint_algorithm`), SHA-256/версионные/ID
   patterns, `ge`-ограничения (`num_rows/num_cols>=1`, `cells minItems 1`,
   `image_size_bytes>=1`, `line>=1`, `page_count>=1`), coupling-validator
   материализации изображений, посегментный запрет `..`.
2. **Детерминированная аугментация** (`curation/schema_contract.py`) — то, что
   Pydantic не выражает: enum-ы Provenance (`role/document_type/parser_name/
   extraction_method`), SHA/path-patterns в `$defs`, `not`-паттерны traversal
   `(^|/)\.\.(/|$)` и абсолютных путей, table-правило «≥1 строка с непустой
   ячейкой» через `contains`, `if/then`-coupling изображений, полная схема OCR-
   метаданных с required-ключами, `uniqueItems`, целочисленные counts-объекты.

`validate-curated` теперь исполняет **распространяемый** `schema.json`
стандартным `jsonschema.Draft202012Validator` по всем записям (плюс прежняя
Pydantic-проверка) — контракт и валидация физически один артефакт. Зависимость
`jsonschema>=4.21` добавлена в project dependencies.

Regression-тесты (`tests/unit/test_schema_contract.py`, 17 шт., только
jsonschema, без Pydantic): 0×0 таблица, `cells=[]`, all-blank cells, отсутствие
dimensions, image size=0, невалидный SHA, абсолютный путь, `../`-traversal,
изображение без materialization, `role=label_source` (документ и provenance),
`status=banana`, невалидный `extraction_status`, отсутствие provenance/полей,
gold-claims weak findings, валидные записи всех 11 типов принимаются, все схемы
валидны по Draft 2020-12. Плюс регрессия реальных имён `…гг..pdf`:
последовательные точки в имени файла — не traversal (посегментная проверка),
`data/raw/../secrets.pdf` — отклоняется.

## 3. Explicit input inventory (blocker B)

`collect_input_inventory()` перечисляет входы **из canonical manifest, без
directory-glob**: manifest (1) + source_metadata (4) + 6 core-файлов на каждый
из 19 model inputs (114) + physical images (460) + label-source `tables.jsonl`
table-gate (4) + исходные `*/weak_findings.json` (1) = **584 файла**. Каждая
запись: `relative_path`, `sha256`, `input_role`. Fingerprint =
SHA-256(canonical serialization отсортированного inventory + заголовок
`dalel-input-inventory/v2|dataset=v1|curation=1.0.0`).

Inventory распространяется как **`input_manifest.jsonl`** внутри датасета
(15-й корневой файл, покрыт checksums и схемой); `build_report.json` содержит
`fingerprint_algorithm`, `input_files_hashed=584` и `input_roles`.
`validate-curated` пересчитывает fingerprint из inventory-записей, сверяет с
build_report и отклоняет любые downstream-пути (`data/curated/`,
`data/results/`, `p1_review_template`) в inventory.

Regression-тесты (`tests/unit/test_fingerprint.py`, 9 шт.): одинаковые входы →
одинаковый fingerprint; изменение review template / data/results / curated
output → fingerprint неизменен; изменение processed-файла / weak findings →
меняется; независимость от абсолютного пути репозитория (копия дерева в другой
root → тот же fingerprint); inventory содержит только разрешённые роли,
отсортирован, label sources дают только table-gate; build_report согласован с
inventory.

## 4. Fingerprints: старый / новый / до-после P1

| Значение | Fingerprint |
|---|---|
| Старый (алгоритм v1, включал template) | `7f9fde0fc897a864589a176097f80ccda0f22793c501bdc83c2474a763f4fe90` |
| Пересчёт верификатора после P1 (v1) | `92e98e6b3ebfecb6e039dc1d4ea0a3c6f741436121692a156fcd825be2974f01` (невоспроизводим) |
| **Новый (v2, upstream-only)** | `772694f42bbf22dd5d649c7eb0d79e8cc73b9e8c2e9b0eae8790633c9dd57051` |
| Build A / Build B (temporary) | тот же `772694f4…` |
| До P1 / **после P1** | тот же `772694f4…` — **P1 и review template не влияют** |

## 5. Two-build byte comparison

`docs/DATASET_V1_IDEMPOTENCY_AUDIT.json` (обновлён): algorithm v2, inventory
count 584 c ролями, fingerprints A/B/production/до/после P1 равны,
**475 = 475 файлов** (474 прежних + `input_manifest.jsonl`), compared 475,
mismatches **0**, production побайтно совпадает с temp-builds → **IDENTICAL**.

## 6. Physical images и no-regression P1

Пересобранный датасет: 460 records = 460 файлов = 460 unique paths, image
checksum errors 0. P1 перезапущен: findings **142** (21/34/87), matching
**16/17/4/0**, rejected fuzzy 2, FP candidates **111** (единый источник),
Bayterek ROOS **70**, Sintez working_project_note **82**, template 142 строки
(человеческие решения сохраняются — regression-тест). Production-проверка
атомарности: ранний отказ поверх существующего датасета — exit 1, 0 изменённых
байт/mtime.

## 7. Тесты и quality gates

**149 passed** (+26: 17 schema-contract + 9 fingerprint). Gates — все exit 0:
ruff check / format --check / mypy (47 файлов) / pytest / foundation READY /
corpus verifier PASS / validate-curated VALID / standalone JSON Schema
validation всех production-записей: **0 errors**.

## 8. Изменённые файлы

`pyproject.toml` (+jsonschema, mypy override), `src/dalel/curation/schemas.py`
(ужесточённые модели, `InputManifestEntry`, `FINGERPRINT_ALGORITHM`),
`src/dalel/curation/schema_contract.py` (новый), `src/dalel/curation/builder.py`
(explicit inventory, `input_manifest.jsonl`, model_validate c контрактными
ошибками), `src/dalel/curation/reports.py` (контрактный schema.json, карточка),
`src/dalel/curation/validation.py` (standalone jsonschema-проверка, inventory-
валидация, 15 required files), `tests/unit/test_schema_contract.py` и
`tests/unit/test_fingerprint.py` (новые), `docs/DATASET_V1_IDEMPOTENCY_AUDIT.json`,
`docs/DATASET_V1_AND_P1_{REPORT,FIX_REPORT}.md`, этот отчёт. Пересобраны через
production CLI: `data/curated/v1/**` (475 файлов), `data/results/p1/v1/**`.

## 9. Remaining limitations

1. Enum-ы аугментации (parser/extraction_method/OCR engines) отражают текущий
   pipeline; расширение парсеров потребует синхронного обновления
   schema_contract (покрыто тестом «valid records accepted»).
2. JSON Schema не выражает межзаписные инварианты (FK, соответствие файлов
   изображений) — они остаются в `validate-curated` поверх standalone-слоя.
3. Прежние non-blocking замечания сохраняются: kk-алиасы 24/34, шумность
   duplicate_heading, 4 проекта без final split, portal-vs-local период Sintez.

## Статус

**READY FOR FINAL INDEPENDENT DATASET V1 AND P1 RE-VERIFICATION**

VERIFIED/ACCEPTED присваивает только независимый верификатор. P3 не начинался.
