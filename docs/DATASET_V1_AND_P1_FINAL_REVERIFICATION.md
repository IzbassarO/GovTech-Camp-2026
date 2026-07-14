# Final Independent Dataset v1 and P1 Re-verification

Дата проверки: 2026-07-14  
Режим: независимая read-only проверка production artifacts, кода и тестов с диска.
Production `curate`, `run-p1`, ingestion и P3 не запускались. Два curated build и
synthetic mutations выполнялись только в `/private/tmp`; временные деревья удалены.
Единственный созданный в repository файл — этот отчёт.

## Executive verdict

**VERIFICATION FAILED — DATASET V1 NOT ACCEPTED**

Fingerprint blocker устранён полностью: upstream inventory воспроизводим, не зависит
от downstream P1/review artifacts, два независимых temporary build и production
побайтно совпадают (475/475 files, 0 mismatches).

Standalone schema улучшена и отклоняет все 14 прямо заданных negative payloads, а все
4073 production records десяти обязательных типов проходят Draft 2020-12 с 0 errors.
Однако прежний Dataset-level blocker устранён не полностью: заявленное image
materialization `if/then` coupling не требует наличия четырёх materialization fields.
Стандартный `jsonschema.Draft202012Validator` принимает image record с non-null
`image_path`, если `curated_image_path`, `image_sha256`, `image_size_bytes` и
`source_image_path` полностью удалены. Он также принимает обратное несогласованное
состояние: `image_path=null` при оставшихся materialization fields.

Это дефект распространяемого standalone contract, а не production data: текущие 460
image records и files корректны, и imperative/Pydantic validation ловит часть таких
mutations. Но требование состояло именно в самостоятельном Draft 2020-12 contract без
подмены Pydantic validation. Поэтому Dataset v1 не принимается. P1 no-regression
подтверждён, но переход к P3 не разрешён.

## Git diff review

Начальный и предфинальный `git status --short` совпадают, кроме разрешённого появления
этого отчёта после записи. До отчёта:

- modified tracked: `pyproject.toml`, `scripts/validate_dataset_foundation.py`,
  `src/dalel/cli.py`, `uv.lock`;
- untracked implementation/generated trees: `src/dalel/curation/`,
  `src/dalel/pillars/`, профильные tests, `data/curated/`, `data/results/`,
  `data/annotations/p1_review_template.jsonl` и заявленные reports;
- tracked diff stat: 4 files, 151 insertions, 10 deletions.

`git diff` не показывает изменений `data/raw`, `data/processed`, `data/manifests` или
original annotations. Foundation validator подтвердил canonical dataset foundation:
0 errors; corpus verifier подтвердил 23 processed documents, hashes/provenance и
leakage с 0 violations. Изменение foundation validator по-прежнему исключает только
derived `processed/curated/results` и точный generated review-template path; raw,
manifest, file inventory, source metadata и original weak findings не исключены.

Verifier не менял ни один protected input, source, test, script или существующий
report.

## Standalone JSON Schema contract

`data/curated/v1/schema.json` — валидный Draft 2020-12 документ. Он содержит 11 schema
entries: все 10 обязательных типов (`project`, `document`, `page`, `section`, `table`,
`image`, `weak finding`, `document group`, `build report`, `dataset statistics`) плюс
контракт для `input_manifest.jsonl`.

Независимый recursive audit обнаружил в distributed schemas:

| Constraint node | Count |
|---|---:|
| `required` | 27 |
| `enum` | 26 |
| `pattern` | 56 |
| `minimum` / `maximum` | 41 / 2 |
| `minItems` | 1 |
| `uniqueItems` | 16 |
| `contains` | 2 |
| `if` / `then` | 1 / 1 |

Nullable fields, nested `$defs`, provenance, arrays/items, role/status Literals,
SHA-256/version/path patterns, table non-empty-content rule и OCR nested contract
присутствуют. Legal filename `НДВ 2026-2035гг..pdf` принимается; настоящий segment
`data/raw/../secrets.pdf` отклоняется.

Blocker находится в `src/dalel/curation/schema_contract.py:181-197` и отражён в
distributed `schema.json:1860-1893`: `then` содержит только `properties`, но не
`required`. В JSON Schema отсутствующее property не валидируется схемой из
`properties`; поэтому coupling не является обязательным.

Также standalone schema не выражает обратную ветвь `image_path=null` → materialization
fields должны быть null/absent. Runtime validator имеет эту imperative проверку, но она
не исправляет distributed standalone contract.

## Synthetic invalid-payload tests

Проверка выполнена непосредственно `jsonschema.Draft202012Validator`, без Pydantic.

| Required synthetic case | Result |
|---|---|
| Table `num_rows=0` | rejected |
| Table `num_cols=0` | rejected |
| Table `cells=[]` | rejected |
| Table all cells blank after trim | rejected |
| Table without provenance | rejected |
| Image `image_size_bytes=0` | rejected |
| Image invalid SHA-256 | rejected |
| Image absolute path | rejected |
| Image path with `..` segment | rejected |
| Invalid feature role | rejected |
| Invalid `extraction_status=banana` | rejected |
| Invalid `label_timing` | rejected as forbidden extra property |
| Missing required ID | rejected |
| Unsafe traversal-like ID | rejected |

Итого по прямо заданному списку: **14/14 rejected**. Positive consecutive-dot case:
accepted.

Дополнительные semantic probes, необходимые для проверки заявленного coupling:

| Additional case | Standalone result | Expected |
|---|---|---|
| `image_path` non-null, materialization keys fully absent | **accepted** | rejected |
| `image_path=null`, materialization values still present | **accepted** | rejected |
| Table numeric dimensions inconsistent with grid | accepted | runtime validator rejects |

Первые два cases являются blocker: они прямо опровергают заявленный image
materialization contract. Третий — non-blocking limitation Draft schema; production и
runtime table validation имеют 0 ошибок.

Почему 17 новых schema tests не нашли дефект: `test_image_without_materialization_rejected`
в `tests/unit/test_schema_contract.py:147-153` оставляет поля в record и присваивает им
`null`. `then.properties` отклоняет присутствующий `null`, но test не удаляет keys и
не проверяет обратную ветвь.

## Production schema validation

Все records проверены schemas именно из распространяемого `schema.json`:

| Layer | Records | Draft 2020-12 errors |
|---|---:|---:|
| 8 core JSONL feature/label/group layers | 4071 | 0 |
| `build_report.json` + `dataset_statistics.json` | 2 | 0 |
| **10 required types total** | **4073** | **0** |
| Additional `input_manifest.jsonl` | 584 | 0 |

`validate-curated` действительно вызывает distributed-schema validation через
`validate_records_with_jsonschema` (`validation.py:248-252`). Независимый temporary
test заменил schema-only `documents.role` на impossible `const`, не меняя Pydantic
models: validator вернул 19 explicit `standalone schema violation` errors. Production
`uv run dalel validate-curated` завершился exit 0.

## Input inventory verification

`data/curated/v1/input_manifest.jsonl` независимо reconciled с canonical manifest,
processed JSONL image references и original weak-findings locations.

| Check | Result |
|---|---:|
| Entries | 584 |
| Unique paths | 584 |
| Deterministically sorted | yes |
| Invalid SHA strings | 0 |
| Unsafe/absolute/traversal paths | 0 |
| Missing physical upstream files | 0 |
| SHA mismatches | 0 |
| Missing expected upstream paths | 0 |
| Unexpected inventory paths | 0 |
| Role mismatches | 0 |

Role distribution: canonical manifest 1; source metadata 4; processed document
records/files 114; processed model-input images 460; label-source table gates 4;
original weak findings 1. Exact independently derived expected set = actual set.

Inventory содержит 0 paths из `data/curated/**`, `data/results/**`, review template,
P1 outputs или generated reports. Label sources вносят только четыре `tables.jsonl`
для table gate; post-review feature bytes не входят.

## Independent fingerprint recomputation

Fingerprint независимо пересчитан из sorted inventory как SHA-256 над header
`dalel-input-inventory/v2|dataset=v1|curation=1.0.0\n` и последовательностью
`relative_path NUL sha256 NUL input_role LF`.

| Source | Fingerprint |
|---|---|
| Independent recomputation | `772694f42bbf22dd5d649c7eb0d79e8cc73b9e8c2e9b0eae8790633c9dd57051` |
| Production `build_report.json` | same |
| Idempotency audit | same |
| Temp build A / B | same / same |
| Relocated temporary repo | same |

`dataset_statistics.json` не содержит fingerprint; проверка для него неприменима.
Production fingerprint полностью воспроизводится с текущего диска.

## Downstream independence

В relocation temp tree были сохранены все 584 upstream files и затем созданы/дважды
изменены synthetic:

- `data/annotations/p1_review_template.jsonl`;
- `data/results/p1/v1/findings.jsonl`;
- `data/curated/downstream/noise.json`.

Fingerprint до/после обеих downstream mutations остался полностью одинаковым:
`772694f4…7051`; `downstream mutation changes fingerprint = false`. Изменение одного
реального upstream file в той же temporary copy изменило fingerprint. Relocation в
другой absolute root fingerprint не изменила; filesystem ordering нейтрализован
sorting. Ни absolute repo path, ни temp path в versioned output artifacts не найдены.

Downstream-independence verdict: **PASS**.

## Temporary two-build idempotency

Выполнены два независимых build из production upstream inputs в разные directories
под `/private/tmp`, без записи в production.

| Check | Result |
|---|---:|
| Build A / B status | success / success |
| Files A / B | 475 / 475 |
| Relative paths only in one build | 0 |
| SHA-256 mismatches A vs B | 0 |
| Mismatches vs production | 0 |
| Image files / image mismatches | 460 / 0 |
| `checksums.jsonl` identical | yes |
| `schema.json` identical | yes |
| `input_manifest.jsonl` identical | yes |
| dataset card identical | yes |
| build report identical | yes |

Byte-identical verdict: **PASS**.

`docs/DATASET_V1_IDEMPOTENCY_AUDIT.json` согласован: algorithm v2, inventory 584,
roles, fingerprints A/B/before-after P1, 475 compared files, empty mismatch/path-diff
lists и `IDENTICAL`. Audit содержит summary и mismatch lists, но не полный per-file
hash manifest каждого historic temp build; independent rerun выше устраняет эту
evidence limitation для текущего состояния.

## Checksum coverage

Production Dataset v1:

| Check | Result |
|---|---:|
| Total files | 475 |
| `checksums.jsonl` entries | 474 |
| Duplicate paths | 0 |
| Missing coverage | 0 |
| Extra paths | 0 |
| SHA/size mismatches | 0 |
| Image records / physical images | 460 / 460 |
| Valid image SHA and size | 460 |
| Image path/traversal errors | 0 |

Checksum verdict: **PASS**.

## Dataset counts

Counts пересчитаны прямым чтением layers, не из report/statistics:

| Object | Recomputed |
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
| Invalid tables | 0 |
| Leakage violations | 0 |

Все physical images принадлежат model-input provenance; label-source document IDs и
roles в feature/image layers отсутствуют. Image materialization не внесла leakage.

## Atomicity

Static control flow по-прежнему строит весь dataset в sibling `.tmp__*`, записывает
checksums, выполняет full validation/checksum verification и только затем делает
swap; exception path восстанавливает старый dataset и удаляет temp directory.

Независимый temporary test:

- существующий valid dataset: 475 files;
- один upstream table изменён в temporary copy на invalid;
- forced rebuild status: failed, 1 table-contract error;
- changed bytes/mtimes existing dataset: **0/475**;
- leftover `.tmp__*`: **0**.

Atomicity verdict: **PASS**.

## P1 no-regression

Полный P1 не запускался. Current outputs, prior verified invariants, targeted code/tests
и full test suite показывают:

| Metric | Recomputed |
|---|---:|
| Findings | 142 |
| High / medium / low / info | 0 / 21 / 34 / 87 |
| Document score range | 10–82 |
| Bayterek ROOS | 70 |
| Sintez working project note | 82 |
| exact equality | 16 |
| normalized substring | 17 |
| token overlap | 4 |
| fuzzy accepted | 0 |
| Accepted section matches | 37 |
| FP candidates | 111 |

Accepted thermal/noise false fuzzy matches: 0. `section_matches.jsonl` содержит 37
records. Review template содержит 142 unique current finding IDs, exact ID set match,
0 автоматически заполненных expert decisions. Regression test сохранения existing
human decisions входит в passing suite.

P1 no-regression verdict: **PASS**.

## Quality gates

| Command | Final exit | Result |
|---|---:|---|
| `uv run ruff check .` | 0 | all checks passed |
| `uv run ruff format --check .` | 0 | 68 files formatted |
| `uv run mypy src` | 0 | 47 source files, 0 issues |
| `uv run pytest` | 0 | 149 passed, 3 deselected, 5 warnings |
| `python3 scripts/validate_dataset_foundation.py` | 0 | READY, 0 errors, 2 `.DS_Store` warnings |
| `uv run python scripts/verify_corpus_ingestion.py` | 0 final | PASS, 0 blockers/leakage |
| `uv run dalel validate-curated --dataset data/curated/v1` | 0 | VALID, 0 errors |
| `uv run pytest tests/unit/test_schema_contract.py -q` | 0 | 17 passed |
| Independent Draft 2020-12 production validation | 0 | 4073 required records + 584 inventory, 0 errors |

Первый sandboxed corpus-verifier attempt имел exit 2 только из-за запрета доступа к
existing `~/.cache/uv`; неизменённая read-only команда с разрешённым cache access дала
final exit 0. Quality gates не исправлялись.

## Blocking issues

1. **Standalone image materialization coupling incomplete.**
   `schema_contract.py:189-196` задаёт только `then.properties`, не `then.required`.
   Distributed Draft 2020-12 schema принимает byte-bearing image record при полном
   отсутствии materialization keys и принимает materialization fields для
   `image_path=null`. Это именно оставшийся blocker самостоятельного semantic contract.

## Non-blocking limitations

- Full per-file historic temp-build manifests отсутствуют в audit JSON; текущие два
  независимых builds дали machine-recomputed 475/475 equality.
- Standalone JSON Schema не выражает numeric table dimensions ↔ dynamic grid-length
  equality; production runtime contract проверяет её, invalid production tables = 0.
- Fix report утверждает Literal `label_timing`, но curated document schema такого поля
  не распространяет; invalid value отклоняется как additional property. Feature role
  всё же жёстко равен `model_input`; report wording требует уточнения.
- 24/34 taxonomy rules без Kazakh aliases; 87 info duplicate-heading findings остаются
  шумными до expert calibration.
- Корпус содержит 4 проекта; statistically reliable final ML split/evaluation
  невозможны. Sintez portal-vs-local period остаётся вне локального P1.
- Foundation validator имеет две ожидаемые `.DS_Store` warnings.

## Final decision

**VERIFICATION FAILED — DATASET V1 NOT ACCEPTED**

Fingerprint, inventory, byte-idempotency, checksums, counts, leakage, atomicity и P1
no-regression подтверждены. Но distributed `schema.json` всё ещё не является полным
standalone semantic contract для image materialization, поэтому Dataset v1 не может
быть принят в рамках заданного критерия.

**Переход к P3 Quantitative Consistency не разрешён. P3 не запускался.**
