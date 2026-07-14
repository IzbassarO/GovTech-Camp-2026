# Independent Dataset v1 and P1 Re-verification

Дата проверки: 2026-07-14  
Режим: независимая read-only проверка production code и generated artifacts. `curate`, `run-p1`, ingestion и P3 не запускались. Единственный созданный файл — этот отчёт.

## Executive verdict

**VERIFICATION FAILED — DATASET V1 NOT ACCEPTED**

Большая часть заявленных исправлений подтверждена непосредственно с диска:

- physical curated images исправлены полностью: 460 records, 460 files, 460 unique paths, 0 checksum mismatches;
- checksum inventory покрывает все 473 dataset files, кроме самого `checksums.jsonl`;
- early-failure/atomic-swap control flow исправлен, соответствующие byte/mtime regression tests проходят;
- logical Dataset v1 counts, table validity и leakage isolation корректны;
- P1 matching, match evidence, findings, scoring, FP candidate count и review template согласованы.

Dataset v1 всё же не принимается из-за двух независимо подтверждённых blockers:

1. **Текущий input fingerprint не воспроизводит production dataset/audit.** Независимо пересчитанный fingerprint тех же 630 declared input files равен `92e98e6b3ebfecb6e039dc1d4ea0a3c6f741436121692a156fcd825be2974f01`, тогда как production `build_report.json` и `DATASET_V1_IDEMPOTENCY_AUDIT.json` содержат `7f9fde0fc897a864589a176097f80ccda0f22793c501bdc83c2474a763f4fe90`. Код fingerprint ошибочно включает generated `data/annotations/p1_review_template.jsonl`, который P1 изменяет после curated build, хотя curation этот файл не читает как input record. Audit относится к прежним bytes и не подтверждает воспроизводимость текущего состояния.
2. **`schema.json` существует для всех 10 типов, но не является полным standalone semantic contract.** Все production records проходят schema validation, однако schemas не кодируют ряд фактически обязательных constraints. Synthetic records без table dimensions/cells, image materialization metadata, с `role=label_source` в feature document и с `build_report.status=banana` принимаются distributed JSON Schema. Во всех 10 schemas отсутствуют enums. Runtime validator ловит часть этих случаев отдельным imperative code, но это опровергает заявление, что distributed schema и validation contract полностью совпадают.

P1 fixes по проверенному production output принимаются. Итоговый статус остаётся Dataset-level failure, поэтому переход к P3 не разрешён.

## Git diff review

Начальный `git status --short`:

- modified tracked files: `pyproject.toml`, `scripts/validate_dataset_foundation.py`, `src/dalel/cli.py`;
- untracked generated/implementation trees: `data/curated/`, `data/results/`, `data/annotations/p1_review_template.jsonl`, `src/dalel/curation/`, `src/dalel/pillars/`, curation/P1 tests, fix/report/audit documents.

Tracked `git diff --stat` остался:

- 3 files changed;
- 146 insertions;
- 10 deletions.

Финальный Git audit после всех read-only checks отличается только появлением разрешённого `docs/DATASET_V1_AND_P1_REVERIFICATION.md`; tracked diff stat и защищённые data paths остались неизменными.

`git diff -- data/raw data/processed data/manifests data/annotations` пуст. Tracked raw, processed, manifests и original weak findings не изменены. Foundation/corpus validators дополнительно подтвердили canonical hashes, paths и provenance. Generated review template является untracked отдельным artifact; original `*/weak_findings.json` не изменён.

Изменение `validate_dataset_foundation.py` по-прежнему ограниченно исключает derived `processed/curated/results` и точный review-template path из raw inventory comparison. Raw files, canonical manifest/inventory и original annotations остаются под проверкой.

## Independently recomputed Dataset v1

Counts пересчитаны прямым чтением JSONL; `build_report.json` и `dataset_statistics.json` не использовались как источник истины.

| Object | Recomputed |
|---|---:|
| Projects | 4 |
| Documents | 19 |
| Pages | 1044 |
| Sections | 1912 |
| Tables | 623 |
| Image records | 460 |
| Physical curated images | 460 |
| Weak findings | 5 |
| Document groups | 4 |

Duplicate IDs во всех восьми JSONL layers: 0. Orphan page/section/table/image records: 0. Все 4039 feature `record_ref` разрешаются в original processed JSONL и после удаления curated-only fields дают 0 content mismatches.

Strict table validation для всех 623 curated tables:

- positive rows/columns;
- rectangular non-empty cells grid;
- хотя бы одна non-blank cell;
- unique table ID;
- valid project/document provenance.

Invalid tables: **0**.

Leakage checks:

- label-source IDs в feature documents/records: 0;
- feature records с non-model-input role: 0;
- label-source images внутри curated physical layer: 0;
- weak findings с invalid source role/use-as-feature/expert flag: 0.

Leakage violations: **0**.

## Physical images and checksums

Независимая проверка каждой image record и каждого physical file:

| Check | Result |
|---|---:|
| `images.jsonl` records | 460 |
| Physical files under `data/curated/v1/images` | 460 |
| Unique `curated_image_path` | 460 |
| Duplicate paths | 0 |
| Missing record files | 0 |
| Orphan physical files | 0 |
| Empty files | 0 |
| `image_size_bytes` mismatches | 0 |
| `image_sha256` mismatches | 0 |
| Absolute/traversal paths | 0 |
| Label-source images | 0 |

`checksums.jsonl`:

- records: 473;
- actual files excluding checksum inventory: 473;
- image paths covered: 460/460;
- duplicate paths: 0;
- missing/extra coverage: 0/0;
- SHA-256 mismatches: 0;
- size mismatches: 0;
- unsafe paths: 0.

Physical image blocker из предыдущей verification устранён.

## Atomic build verification

Static control-flow review подтверждает:

- existing output без `--force` отклоняется до fingerprint/build writes (`builder.py:200-203`);
- early accumulated errors возвращают failed `BuildResult` без записи в output (`builder.py:282-294`);
- все JSON/JSONL, schemas, report/card, images и checksums сначала создаются в sibling temp directory (`builder.py:620-673`);
- temp dataset полностью проходит `validate_curated_dataset` и повторный checksum verification до swap (`builder.py:675-688`);
- existing dataset переименовывается только после успешной validation (`builder.py:690-692`);
- exception path восстанавливает старый dataset и удаляет temp (`builder.py:693-697`).

Tests подтверждают:

- ранний invalid-table rebuild сохраняет bytes и `mtime_ns` каждого старого файла;
- exception во время temp build сохраняет старый snapshot;
- temp directories после failure отсутствуют;
- build без `--force` отклоняется.

`uv run pytest` прошёл эти tests. Production rebuild не выполнялся согласно ограничению. Atomicity verdict: **PASS**.

## Machine-readable schema verification

`schema.json` содержит ровно 10 заявленных schema entries:

1. project;
2. document;
3. page;
4. section;
5. table;
6. image;
7. weak finding;
8. document group;
9. build report;
10. dataset statistics.

Все entries являются Draft 2020-12-compatible object schemas, имеют `properties`, `required` и `additionalProperties=false`. Nested `$defs`, nullable `anyOf/null` и числовые minimum constraints присутствуют там, где их генерируют Pydantic models. Все 4073 production records/payloads прошли независимую `jsonschema` validation с 0 errors.

Однако проверка полноты semantic contract дала:

- enum nodes во всех 10 schemas: **0**;
- `documents.role`, extraction/status-like fields, weak severity/confidence/review status и build status являются unconstrained strings;
- `tables.jsonl.required` не включает `num_rows`, `num_cols`, `cells`;
- table non-empty/rectangular/content contract описан в notes и Pydantic model validator, но не выражен JSON Schema constraints;
- image schema не выражает условие: если `image_path` non-null, то `curated_image_path`, `image_sha256`, `image_size_bytes` обязательны и согласованы;
- `weak_findings.expert_verified` не required и не constrained константой `false`.

Negative standalone-schema probes:

| Synthetic payload | Distributed JSON Schema |
|---|---|
| Table без `num_rows`, `num_cols`, `cells` | **accepted** |
| Image с bytes, но без curated path/hash/size | **accepted** |
| Feature document с `role=label_source` | **accepted** |
| Build report с `status=banana` | **accepted** |

Pydantic rejects the invalid table because of an imperative model validator, but Pydantic accepts the incomplete image record; `validate-curated` rejects it only через отдельные checks. Current schema tests (`test_curation.py:187-211`) проверяют наличие top-level `properties/type/required` и description-only regression, но не эти semantic mutants.

Schema verdict: **FAIL** для требования полноценного standalone machine-readable contract. Description-only blocker исправлен, но contract остаётся неполным.

## Byte-idempotency and input fingerprint

`docs/DATASET_V1_IDEMPOTENCY_AUDIT.json` валиден и внутренне заявляет:

- build A files: 474;
- build B files: 474;
- compared files: 474;
- paths only in A/B: 0/0;
- SHA-256 mismatches: 0;
- production matches temp builds: true;
- final result: IDENTICAL.

Production dataset сейчас действительно содержит 474 files: 14 root files + 460 images. Absolute repo paths в versioned text artifacts не найдены. Wall-clock build timestamps удалены из build report/card; timestamps, остающиеся в pages/sections/tables/images, являются verbatim input provenance и детерминированы входом.

Но ключевое поле audit не воспроизводится:

| Fingerprint source | Files | SHA-256 |
|---|---:|---|
| Audit JSON | 630 | `7f9fde0f…fe90` |
| Production build report | 630 | `7f9fde0f…fe90` |
| Independent current recomputation | 630 | `92e98e6b…4f01` |
| `compute_input_fingerprint()` on current disk | 630 | `92e98e6b…4f01` |

Root cause: `compute_input_fingerprint` recursively hashes the entire `annotations_root` (`builder.py:161-166`), включая generated `p1_review_template.jsonl`. Curation фактически читает only `annotations_root/*/weak_findings.json`, но subsequent P1 updates the root review template from 141 to 142 stable IDs. Count remains 630, while bytes and fingerprint change.

Следствия:

- production/audit describe pre-P1-update input bytes;
- текущий repository state не воспроизводит stored dataset fingerprint;
- повторный build на текущем диске изменил бы at least build report/card/schema checksums due new fingerprint, даже если semantic curation inputs unchanged;
- curation identity зависит от downstream P1 artifact, создавая circular phase coupling.

Audit JSON содержит только summary, без per-build relative-path/hash manifests, поэтому independently подтвердить historic 474/474 comparison без запрещённого rebuild невозможно. Synthetic `test_two_builds_byte_identical` проходит, но использует fixture, где downstream template не изменяется между phases.

Idempotency verdict: **FAIL for current production reproducibility**.

## P1 matching verification

`section_matches.jsonl` и независимый matcher recomputation совпали полностью и в том же порядке:

| Method | Recomputed accepted |
|---|---:|
| exact_equality | 16 |
| normalized_substring | 17 |
| token_overlap | 4 |
| fuzzy | 0 |
| Total | 37 |

Rules evaluated: 75. Unmatched required/recommended: 19/19.

False-fuzzy regression:

- `шумовое воздействие` vs `Тепловое воздействие`: rejected;
- `шумовое воздействие` vs `Вредное воздействие`: rejected;
- generic-only evidence `воздействие` не позволяет fuzzy acceptance;
- genuine OCR candidate `Введени` → `введение`: accepted fuzzy, score 0.933, token evidence `введение~введени`.

Production metrics содержат 2 rejected fuzzy records, но оба являются дубликатом одного observed heading/alias pair: alias `шумовое воздействие` дважды присутствует как explicit alias и canonical section. Это не меняет accepted findings, но count означает evaluations, а не unique candidates.

P1 matching verdict: **PASS**, с non-blocking duplicate-rejected-evidence limitation.

## `section_matches.jsonl`

Проверено 37 records:

- unique `match_id`: 37/37;
- valid project/document/rule FKs: 37/37;
- rule соответствует document type: 37/37;
- `observed_heading` и `page_number` существуют в curated sections: 37/37;
- `matched_alias` входит в rule aliases/canonical section: 37/37;
- normalized heading, method и score независимо пересчитаны: 37/37;
- `discriminative_tokens` и limitations присутствуют: 37/37;
- invalid methods/score mismatches: 0.

Bayterek ROOS теперь имеет low `missing_expected_section` finding ROOS-S05. Его explanation фиксирует отклонённый thermal fuzzy candidate. False match больше не подавляет finding.

## P1 findings and scoring

Независимый пересчёт production outputs:

| Metric | Actual |
|---|---:|
| Findings | 142 |
| High | 0 |
| Medium | 21 |
| Low | 34 |
| Info | 87 |
| Unique finding IDs | 142 |
| Pending review | 142 |
| Null confidence | 142 |
| Document scores | 19 |
| Project scores | 4 |
| Document score range | 10–82 |

Findings by type: 38 missing expected sections, 87 duplicate headings, 8 empty pages, 5 missing appendix references, 2 high OCR dependency, 1 low text coverage, 1 suspicious document length.

Все Finding/DocumentScore/ProjectScore records прошли Pydantic validation. Stable finding IDs независимо пересчитаны из content basis; mismatches: 0.

Scoring arithmetic:

- contribution mismatches: 0;
- document sum/cap mismatches: 0;
- project mean/package aggregation mismatches: 0;
- Bayterek ROOS: **70** = independently summed 70;
- Sintez working_project_note: **82**, остаётся top;
- project scores: Bereke 27, AZM 30, Bayterek 42, Sintez 32.

Scoring verdict: **PASS**.

## FP candidates

Единая функция `is_false_positive_review_candidate` независимо применена к 142 FindingRecord objects:

- independently recomputed: **111**;
- `metrics.false_positive_review_candidate_count`: 111;
- metrics ID list length: 111;
- independent IDs == metrics IDs: yes;
- P1 `report.md`: 111;
- `DATASET_V1_AND_P1_REPORT.md`: 111;
- candidate IDs present in review template: 111/111.

FP candidate verdict: **PASS**.

## Review template

`data/annotations/p1_review_template.jsonl`:

- rows: 142;
- unique finding IDs: 142;
- IDs/order совпадают с current findings: 142/142;
- expert decision/severity/comment/reviewed_at/reviewer fields: все null;
- automatically confirmed records: 0;
- stale file in current P1 output: absent, что согласовано с 0 current stale rows.

Implementation merges existing rows by content-stable finding ID, preserves non-null human fields, adds new findings as empty rows and writes disappeared IDs separately to `review_template_stale.jsonl`. Regression test confirms preservation of a populated human decision across rerun. Separate stale-row branch существует, но direct stale-row regression test отсутствует; current dataset has no stale IDs.

Review template verdict: **PASS**, с non-blocking test-coverage limitation для stale branch.

## Quality gates

| Command | Final exit code | Result |
|---|---:|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run ruff format --check .` | 0 | 65 files already formatted |
| `uv run mypy src` | 0 | no issues in 46 source files |
| `uv run pytest` | 0 | 123 passed, 3 deselected, 5 warnings |
| `python3 scripts/validate_dataset_foundation.py` | 0 | READY, 0 errors, 2 `.DS_Store` warnings |
| `uv run python scripts/verify_corpus_ingestion.py` | 0 final | PASS, leakage/errors 0 |
| `uv run dalel validate-curated --dataset data/curated/v1` | 0 | VALID, 460 physical images, errors 0 |

Первый sandboxed corpus-verifier attempt получил exit 2 из-за запрета доступа к `~/.cache/uv`. Тот же read-only command с разрешённым доступом к existing cache завершился exit 0; final gate status — PASS.

Текущий `validate-curated` не сверяет `build_report.input_fingerprint` с current inputs и проверяет schema completeness только по наличию top-level schema structure. Поэтому его exit 0 не опровергает два blockers выше.

## Blocking issues

1. **Stale/non-reproducible input fingerprint.** Current 630-file fingerprint `92e98e…` не совпадает с production/audit `7f9fde…`, потому что downstream generated review template ошибочно включён в curation fingerprint.
2. **Incomplete standalone JSON Schema semantics.** All 10 schema entries существуют, но обязательные table/image coupling constraints и categorical enums отсутствуют; invalid synthetic payloads принимаются distributed schemas.

## Non-blocking limitations

- Historic two-build audit не содержит per-file hash manifests и не может быть независимо replayed без запрещённого production rebuild.
- Rejected fuzzy metric содержит две идентичные evaluations одного thermal/alias pair.
- Direct stale-review-row regression test отсутствует, хотя implementation branch существует и current stale count равен 0.
- 24/34 taxonomy rules не имеют Kazakh aliases.
- 87 info duplicate-heading findings остаются шумными до expert calibration.
- Matcher теоретически позволяет одному heading удовлетворить нескольким rules; actual reuse groups = 0.
- Корпус содержит только 4 проекта; reliable ML evaluation/final split невозможны.
- Sintez portal-vs-local period discrepancy остаётся недетектируемым без external metadata adapter.
- Foundation validator выдаёт две ожидаемые `.DS_Store` warnings.

## Final decision

**VERIFICATION FAILED — DATASET V1 NOT ACCEPTED**

Physical images, checksums, atomic build path и P1 fixes подтверждены. Dataset v1 всё ещё не удовлетворяет требованиям воспроизводимого current input fingerprint и полноценного standalone machine-readable schema contract.

**Переход к P3 Quantitative Consistency не разрешён. P3 не запускался.**
