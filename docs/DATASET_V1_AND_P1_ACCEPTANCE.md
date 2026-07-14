# VERIFIED — DATASET V1 AND P1 ACCEPTED

Дата независимой проверки: 2026-07-14.

Проверка выполнена read-only относительно кода, Dataset v1, P1 artifacts и
исходного корпуса. `curate`, `run-p1`, ingestion, commit/push и P3 не
запускались. Единственный созданный файл — этот acceptance report.

## Git diff и проверенный scope

Команда `git diff --` для следующих путей не выводит diff, поскольку все четыре
пути имеют статус `??` и ещё не известны Git:

- `src/dalel/curation/schema_contract.py`;
- `tests/unit/test_schema_contract.py`;
- `data/curated/v1/schema.json`;
- `data/curated/v1/checksums.jsonl`.

Их текущее содержимое проверено напрямую. Дополнительно schema contract,
сгенерированный в памяти из текущего production-кода, в точности совпал со
всеми 11 file schemas в распространяемом `data/curated/v1/schema.json`:
`exact_contract_match=True`, different files = 0.

## Schema verdict

Standalone image schema является валидной JSON Schema Draft 2020-12. Для
materialized image, то есть при строковом `image_path`, условие `then.required`
обязывает присутствовать одновременно:

- `curated_image_path` — непустая безопасная относительная строка;
- `image_sha256` — lowercase SHA-256 из 64 hex-символов;
- `image_size_bytes` — integer не меньше 1.

Проверка выполнена напрямую через `jsonschema.Draft202012Validator` по
распространяемому `schema.json`, без Pydantic runtime.

Synthetic results:

| Case | Result |
|---|---|
| omit `curated_image_path` | rejected |
| omit `image_sha256` | rejected |
| omit `image_size_bytes` | rejected |
| `curated_image_path = null` | rejected |
| `image_sha256 = null` | rejected |
| `image_size_bytes = null` | rejected |
| `image_size_bytes = 0` | rejected |
| invalid SHA | rejected |
| absolute image path | rejected |
| отдельный path segment `..` | rejected |
| легальное имя с `гг..` внутри filename | accepted |

Все 11 распространяемых file schemas прошли `check_schema`. Через них отдельно
проверены 4,657 production records/payloads: **production schema errors = 0**.

## Dataset v1 artifacts

- Recomputed input fingerprint из отсортированного manifest на 584 upstream
  files совпал с `build_report.json` и ожидаемым значением:
  `772694f42bbf22dd5d649c7eb0d79e8cc73b9e8c2e9b0eae8790633c9dd57051`.
- Все 584 текущих upstream files существуют; hash mismatches = 0; downstream
  artifacts в input inventory = 0.
- Checksums: 474/474 уникальных записей покрывают ровно все 474 dataset files,
  кроме самого `checksums.jsonl`; SHA mismatches = 0, size mismatches = 0,
  record-count mismatches = 0.
- Images: 460 records, 460 уникальных record paths, 460 физических файлов;
  record/file set совпадает; SHA/size/missing/orphan violations = 0.
- Tables: 632/632 upstream records валидны, включая 623/623 curated records;
  invalid tables = 0.
- Leakage: 19 model inputs и 4 label sources размещены раздельно; curated
  feature provenance содержит только `model_input`; violations = 0.

## P1 no-regression

Независимый пересчёт из P1 JSONL artifacts дал:

- findings: 142;
- severity: high 0, medium 21, low 34, info 87;
- document scores: 10–82, score recomputation mismatches = 0;
- section matches: 37;
- matching: 16 `exact_equality`, 17 `normalized_substring`, 4
  `token_overlap`, 0 `fuzzy`;
- false-positive review candidates: 111.

Пересчитанные значения согласованы с `metrics.json`, включая порядок и состав
111 FP candidate IDs.

## Quality gates

| Command | Result |
|---|---|
| `uv run ruff check .` | PASS — all checks passed |
| `uv run ruff format --check .` | PASS — 68 files already formatted |
| `uv run mypy src` | PASS — 47 source files, 0 issues |
| `uv run pytest` | PASS — 155 passed, 3 deselected |
| `python3 scripts/validate_dataset_foundation.py` | PASS — READY, errors 0 |
| `uv run python scripts/verify_corpus_ingestion.py` | PASS — blocking errors 0, invalid tables 0, leakage 0 |
| `uv run dalel validate-curated --dataset data/curated/v1` | PASS — VALID, errors 0 |

Foundation validator сообщил две неблокирующие warnings об ignored OS artifact
`data/raw/.DS_Store`. Pytest сообщил пять dependency deprecation warnings. Ни
одна warning не является Dataset v1/P1 blocker.

## Acceptance

Blockers: **нет**.

P3: **разрешён**, но в рамках этой проверки не запускался и не начинался.

**VERIFIED — DATASET V1 AND P1 ACCEPTED**
