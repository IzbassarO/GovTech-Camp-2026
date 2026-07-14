# Dataset v1 Image Schema Fix Report

Дата: 2026-07-14  
Scope: единственный подтверждённый blocker standalone image materialization schema.
P1 и P3 не изменялись и не запускались. Git commit/push не выполнялись.

## Root cause

В `src/dalel/curation/schema_contract.py` image-ветка Draft 2020-12 `then`
описывала `properties`, но не содержала `required`. В JSON Schema отсутствующий key
не проверяется правилом из `properties`; поэтому byte-bearing image record мог пройти
standalone validation без materialization keys.

Production `CuratedImageRecord` определяет coupling в
`src/dalel/curation/schemas.py:179-192`. При non-null `image_path` модель требует
ровно три поля:

1. `curated_image_path` — dataset-relative path физической копии;
2. `image_sha256` — SHA-256 физического image file;
3. `image_size_bytes` — положительный размер файла.

`source_image_path` остаётся optional в production model и поэтому намеренно не
добавлен в `then.required`.

## Exact schema change

В `src/dalel/curation/schema_contract.py:189-200` добавлено:

```json
"required": [
  "curated_image_path",
  "image_sha256",
  "image_size_bytes"
]
```

Существующие constraints не ослаблялись:

- `curated_image_path`: string, dataset-relative curated image pattern, запрет
  absolute paths и отдельного segment `..`;
- `image_sha256`: `^[0-9a-f]{64}$`;
- `image_size_bytes`: integer, minimum 1;
- legal consecutive dots внутри filename не считаются traversal.

Production `data/curated/v1/schema.json:1872-1896` после rebuild содержит тот же
`then.required` и прежние properties/pattern/minimum constraints.

## Regression tests

`tests/unit/test_schema_contract.py` дополнен standalone tests, использующими только
`jsonschema.Draft202012Validator`:

- production-valid image принимается;
- каждый из трёх materialization keys по отдельности удаляется через `del` и
  отклоняется;
- каждый из трёх keys со значением `null` отклоняется;
- invalid SHA отклоняется;
- `image_size_bytes=0` отклоняется;
- absolute curated path отклоняется;
- path с отдельным `..` segment отклоняется;
- legal filename с `гг..` внутри имени принимается.

Targeted result:

```text
uv run pytest tests/unit/test_schema_contract.py -q
23 passed
```

Full suite after formatting and production rebuild:

```text
155 passed, 3 deselected, 5 warnings
```

## Production rebuild

Dataset v1 пересобран production CLI:

```bash
uv run dalel curate \
  --input data/processed \
  --output data/curated/v1 \
  --manifest data/manifests/projects.jsonl \
  --force
```

Result: `Build status: success`. Generated `schema.json` и `checksums.jsonl`
обновлены; atomic build validation завершилась успешно.

## Standalone production validation

Все schemas прочитаны из распространяемого `data/curated/v1/schema.json` и
исполнены стандартным `Draft202012Validator`:

- schema entries: 11 (10 curated record/payload types + input manifest);
- production payloads checked: 4657;
- standalone schema errors: **0**.

Synthetic omitted/null results после production rebuild:

| Mutation | Result |
|---|---|
| remove `curated_image_path` | rejected |
| remove `image_sha256` | rejected |
| remove `image_size_bytes` | rejected |
| `curated_image_path=null` | rejected |
| `image_sha256=null` | rejected |
| `image_size_bytes=null` | rejected |

Blocker case «image record без materialization keys» теперь отклоняется standalone
schema без Pydantic runtime.

## Fingerprint and checksums

Independent inventory recomputation и production build report совпали:

```text
772694f42bbf22dd5d649c7eb0d79e8cc73b9e8c2e9b0eae8790633c9dd57051
```

Fingerprint semantics и 584-entry upstream inventory не изменялись.

Checksum verification:

- dataset files: 475;
- checksum entries: 474;
- missing/extra paths: 0/0;
- SHA/size mismatches: 0.

## Curated counts

| Object | Count |
|---|---:|
| Projects | 4 |
| Documents | 19 |
| Pages | 1044 |
| Sections | 1912 |
| Tables | 623 |
| Image records | 460 |
| Physical images | 460 |
| Weak findings | 5 |
| Document groups | 4 |

`validate-curated`: VALID, errors 0.

## P1 no-regression

P1 не перезапускался и его code/artifacts не изменялись. Current outputs:

- findings: 142;
- severity: high 0, medium 21, low 34, info 87;
- score range: 10–82;
- Bayterek ROOS: 70;
- Sintez working project note: 82;
- section matches: 37 (`exact_equality=16`, `normalized_substring=17`,
  `token_overlap=4`, `fuzzy=0`);
- FP candidates: 111;
- review template: 142 current IDs, 0 automatically populated expert rows.

P1 no-regression: **PASS**.

## Quality gates

| Command | Final exit | Result |
|---|---:|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run ruff format --check .` | 0 | 68 files already formatted |
| `uv run mypy src` | 0 | 47 source files, 0 issues |
| `uv run pytest` | 0 | 155 passed, 3 deselected, 5 warnings |
| `python3 scripts/validate_dataset_foundation.py` | 0 | READY, 0 errors, 2 `.DS_Store` warnings |
| `uv run python scripts/verify_corpus_ingestion.py` | 0 final | PASS, 0 blockers/leakage |
| `uv run dalel validate-curated --dataset data/curated/v1` | 0 | VALID, 0 errors |

Первый sandboxed corpus-verifier attempt получил exit 2 только из-за запрета доступа
к existing `~/.cache/uv`; та же read-only команда с разрешённым cache access дала
final exit 0. Первый format check обнаружил изменённый файл, formatter был применён,
после чего final format check завершился exit 0.

## Changed files

Изменены в рамках этого fix:

- `src/dalel/curation/schema_contract.py` — `then.required`;
- `tests/unit/test_schema_contract.py` — focused omitted/null/path regressions;
- `data/curated/v1/schema.json` — regenerated distributed contract;
- `data/curated/v1/checksums.jsonl` — regenerated checksum inventory;
- `docs/DATASET_V1_IMAGE_SCHEMA_FIX_REPORT.md` — этот отчёт.

Production CLI атомарно пересобрал Dataset v1; прочие versioned dataset payloads
остались детерминированными с прежними counts/fingerprint. Не изменялись
`data/raw/**`, `data/processed/**`, `data/manifests/**`, P1 matching/scoring,
independent verification reports или fingerprint semantics.

## Status

**READY FOR ONE-SHOT INDEPENDENT VERIFICATION**

Статус VERIFIED/ACCEPTED этим fix report не присваивается. P3 не начинался.
