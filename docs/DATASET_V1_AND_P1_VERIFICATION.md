# Independent Dataset v1 and P1 Verification

Дата независимой проверки: 2026-07-14  
Проверяемые фазы: Phase 0.5 Curated Dataset v1 и Phase 1A P1 Document Integrity  
Режим проверки: read-only для production data/code; временные synthetic artifacts создавались только в системном temp directory.

## Executive verdict

**VERIFICATION FAILED — DATASET V1 NOT ACCEPTED**

Логический feature inventory пересчитан независимо и совпадает с заявленным:

- projects: **4**;
- documents: **19**;
- pages: **1044**;
- sections: **1912**;
- tables: **623**;
- images records: **460**;
- weak findings: **5**;
- document groups: **4**.

Anti-join между `data/processed/model_inputs` и curated feature records не выявил потерь: 0 documents, 0 pages, 0 sections, 0 valid tables и 0 image records. Leakage violations: **0**. Invalid production tables: **0**.

Dataset v1, однако, не принимается по следующим подтверждённым причинам:

1. В `data/curated/v1` нет ни одного физического image-файла: **0 physical curated images при 460 image records**. Записи ссылаются на `data/processed`, а `checksums.jsonl` не покрывает эти 460 image bytes. Условие `image records = physical curated image files = 460` не выполнено; dataset не является самодостаточным и checksummed на уровне изображений.
2. Early validation failure сборщика не атомарен. Ветка `errors` вызывает `_write_failed_report()` прямо в существующий output и перезаписывает его `build_report.json` до atomic swap. Synthetic temp test подтвердил изменение bytes и смену `status: success` на `status: failed` при сохранении остальных старых файлов, то есть существующий валидный dataset становится внутренне несогласованным.
3. `schema.json` не содержит машинно-проверяемых JSON Schema contracts для `pages.jsonl`, `sections.jsonl`, `tables.jsonl` и `images.jsonl`: для них записано только поле `description`. Заявление отчёта о machine-readable schemas для всего curated dataset шире фактической реализации.
4. Полная byte-idempotency не доказана и фактически не является целью текущего теста: test исключает `build_report.json`, `dataset_card.md` и `checksums.jsonl`, тогда как timestamps в build report меняют эти bytes и вслед за ними checksum inventory.

P1 inventory и scoring арифметически согласованы: **141 findings** = medium 21, low 33, info 87; document score range 10–82; независимо пересчитанные document/project scores совпали. Но P1 также требует исправлений: единственный fuzzy match является содержательно ложным (`шумовое воздействие` → `Тепловое воздействие`, 0.821), 17 из 33 результатов, названных `exact`, на самом деле substring matches, а generated outputs не сохраняют observed heading для успешных section matches. Кроме того, основной отчёт заявляет 111 FP candidates, тогда как `metrics.json`, P1 `report.md` и независимый пересчёт дают **110**.

Переход к P3 Quantitative Consistency: **не разрешён до исправления dataset blockers и повторной независимой проверки**. P3 в ходе этой работы не запускался.

## Git diff review

Начальный `git status --short` показал:

- modified: `pyproject.toml`, `scripts/validate_dataset_foundation.py`, `src/dalel/cli.py`;
- untracked: `src/dalel/curation/`, `src/dalel/pillars/`, curation/P1 tests and fixtures, `data/curated/`, `data/results/`, `data/annotations/p1_review_template.jsonl`, `docs/DATASET_V1_AND_P1_REPORT.md` и несколько source documents в `docs/`.

Tracked diff: 3 files, 146 insertions, 10 deletions. Изменений tracked-файлов в `data/raw`, `data/processed`, `data/manifests`, canonical `source_metadata.json` или исходных annotations не обнаружено. Production foundation/corpus validators дополнительно подтвердили raw hashes, manifest paths/hashes и processed provenance.

Финальный `git status --short` отличается от начального только появлением разрешённого verifier output `docs/DATASET_V1_AND_P1_VERIFICATION.md`. Финальный `git diff --stat` для tracked files остался 3 files / 146 insertions / 10 deletions; verifier не изменял существующий code, tests, scripts или data artifacts.

Изменение `scripts/validate_dataset_foundation.py` проверено построчно. Исключение из physical inventory comparison добавлено только для:

- `data/processed/**`;
- `data/curated/**`;
- `data/results/**`;
- точного пути `data/annotations/p1_review_template.jsonl`.

Проверки raw source metadata, canonical manifest, manifest SHA-256, inventory-listed files и raw directory structure сохранены. Synthetic temp test дал:

| Scenario | Errors | Result |
|---|---:|---|
| Valid raw + generated processed/curated/results/review files | 0 | generated files корректно исключены |
| Existing raw file changed | 2 | size и SHA-256 mismatch |
| Unexpected raw artifact added | 1 | missing from inventory |
| Inventory-listed raw file removed | 2 | missing file и inventory/disk mismatch |

Следовательно, конкретное изменение validator не маскирует unexpected raw artifacts и не ослабляет raw comparison шире необходимого. Canonical manifest и inventory сами не изменены в текущем diff. Произвольная согласованная правка manifest/inventory остаётся обнаружимой через Git review; inventory намеренно не содержит нестабильную self-reference.

Изменение `pyproject.toml` отключает `RUF001/RUF002/RUF003` глобально для кириллических строк. Это расширение lint policy, но не ослабление dataset validators. `src/dalel/cli.py` добавляет `curate`, `validate-curated` и `run-p1` команды.

## Dataset inventory

Ни `build_report.json`, ни `dataset_statistics.json` не использовались как источник counts. Все JSONL были прочитаны напрямую и пересчитаны независимо.

| Required file | Exists/non-empty | Parse | Records / result | Duplicates | Orphans |
|---|---|---|---:|---:|---:|
| `projects.jsonl` | yes | valid JSONL | 4 | 0 | 0 |
| `documents.jsonl` | yes | valid JSONL | 19 | 0 | 0 |
| `pages.jsonl` | yes | valid JSONL | 1044 | 0 composite IDs | 0 |
| `sections.jsonl` | yes | valid JSONL | 1912 | 0 | 0 |
| `tables.jsonl` | yes | valid JSONL | 623 | 0 | 0 |
| `images.jsonl` | yes | valid JSONL | 460 | 0 | 0 |
| `weak_findings.jsonl` | yes | valid JSONL | 5 | 0 | 0 |
| `document_groups.jsonl` | yes | valid JSONL | 4 | 0 | 0 |
| `dataset_statistics.json` | yes | valid JSON | 1 object | n/a | n/a |
| `schema.json` | yes | valid JSON | incomplete contract; see blocker | n/a | n/a |
| `label_schema.json` | yes | valid JSON | 1 object | n/a | n/a |
| `checksums.jsonl` | yes | valid JSONL | 13 | 0 paths | 0 paths |
| `dataset_card.md` | yes | non-empty Markdown | n/a | n/a | n/a |
| `build_report.json` | yes | valid JSON | status=success | n/a | n/a |

Независимая Pydantic validation дала 0 schema errors для всех records. Для passthrough records перед validation удалялись только curated additions (`record_ref`, а для images также `source_image_path`); остальные поля проверялись исходными ingestion models. Это подтверждает фактические records, но не устраняет неполноту распространяемого `schema.json`.

## Corpus-to-curated reconciliation

Независимый полный processed inventory:

| Layer | Documents | Pages | Sections | Tables | Images |
|---|---:|---:|---:|---:|---:|
| Full processed corpus | 23 | 1075 | 1955 | 632 | 481 |
| Processed model inputs | 19 | 1044 | 1912 | 623 | 460 |
| Processed label sources | 4 | 31 | 43 | 9 | 21 |
| Curated feature layer | 19 | 1044 | 1912 | 623 | 460 |

Разница full corpus → curated в точности равна четырём label sources: 4 documents, 31 pages, 43 sections, 9 tables, 21 images.

Anti-join processed model inputs → curated:

- missing documents: 0; extra documents: 0;
- missing/extra pages: 0/0;
- missing/extra sections: 0/0;
- missing/extra valid tables: 0/0;
- missing/extra image records: 0/0;
- content mismatches после удаления curated-only additions: 0;
- invalid or unresolved `record_ref`: 0.

Unsupported model-input cases, потребовавшие исключения, отсутствуют.

## Mixed-schema normalization

По `documents.jsonl` и original processed `document.json`/`ingestion_report.json`:

- schema 1.0.0: **17 model-input documents**;
- schema 1.1.0: **2 model-input documents**.

Полный processed corpus содержит 21 documents schema 1.0.0 + 2 schema 1.1.0. Четыре исключённых label sources относятся к legacy schema, поэтому curated feature layer закономерно даёт `(21 - 4) + 2 = 17 + 2`.

Для всех 17 legacy documents подтверждено:

- `serialized_table_count == len(original tables.jsonl)`;
- `detected_table_items == serialized_table_count`;
- `skipped_empty_table_items == 0`;
- `applied_normalizations` содержит inference legacy counters;
- `normalization_warnings` содержит `legacy_report_counters_inferred`.

В processed legacy reports нет полей, доказывающих skipped parser artifacts, поэтому inferred zero явно маркирован warning и не выдан за native observation.

Для двух schema 1.1.0 documents native `detected/serialized/skipped` полностью совпадают с original processed reports. `skipped_empty_table_items` не обнулён normalizer-ом. Hash/provenance gates подтверждают, что processed files не переписывались.

## Table validation

Все **623** curated table records проверены независимо:

- `num_rows > 0`, `num_cols > 0`;
- `cells` является непустым grid;
- присутствует хотя бы одна non-blank cell;
- grid shape согласован с dimensions;
- unique `table_id`: 623/623;
- valid project/document FKs;
- `source_sha256` согласован с document/manifest;
- page reference существует либо честно `null`;
- bbox либо `null`, либо имеет корректную геометрию;
- original `record_ref` существует и указывает на идентичную processed record.

Production invalid table count: **0**.

Builder применяет `_table_contract_errors` ко всем 623 model-input tables и отдельно ко всем 9 label-source tables, включая legacy schema: processed gate total 632 valid, 0 invalid.

Synthetic invalid input test выполнялся только в `/tmp`:

- первая table record была заменена на `num_rows=0`, `num_cols=0`, `cells=[]`;
- `uv run dalel validate-curated --dataset <temp>` вернул **exit 1**;
- output явно содержал `tables:1: violates table validity contract`;
- checksum/size mismatch также был обнаружен;
- SHA-256 production `data/curated/v1/tables.jsonl` до и после: `f72f26c31b136adb9b898bc63bca6735960c3ebf0d698f659ede5c3d91ccba5d`.

## Image validation

Для 460 image records подтверждено:

- unique logical IDs: 460;
- valid project/document FKs;
- `source_image_path` не абсолютный, не содержит `..` и разрешается под `data/processed/model_inputs`;
- original processed image record существует;
- referenced processed physical file существует и имеет size > 0;
- label-source image IDs/paths отсутствуют;
- source image bytes успешно прочитаны и получили 460 вычисленных SHA-256.

Критическое расхождение:

| Measure | Expected | Actual |
|---|---:|---:|
| Image records | 460 | 460 |
| Referenced processed physical images | 460 | 460 |
| Physical files inside `data/curated/v1` | 460 | **0** |
| Curated checksum records for image bytes | 460 | **0** |

Image records не содержат independently stored expected image checksum. Поэтому можно подтвердить существование и вычислить hash processed bytes, но невозможно сравнить этот hash с committed curated expectation. `validate-curated` проверяет только существование `(repo_root / source_image_path)` и не проверяет path containment или byte checksum. На текущих records traversal не найден, но validator contract недостаточен.

## Leakage isolation

Программные проверки дали **0 leakage violations**:

- ни одна feature record не имеет label-source document ID, role или source path;
- hearing protocol text не найден в curated pages;
- motivated refusal text не найден в curated pages;
- label-source sections/tables/images отсутствуют;
- full post-review documents не встроены в `documents.jsonl`;
- full label page strings длиной ≥64 символов не обнаружены в feature text;
- weak findings содержат только короткие evidence excerpts: 60–71 characters, 7–10 words;
- все 5 `expert_verified=false`, `confidence=weak`, `review_status=not_expert_verified`;
- утверждений `gold label` или эквивалентного подтверждения нет.

Для каждого weak finding проверено: `source_document_id` существует в manifest, имеет `role=label_source`, `use_as_model_feature=false`, source page существует либо честно `null`, target documents являются model inputs. Нарушений: 0.

## Provenance and checksums

Provenance FKs, source hashes и 4039 feature `record_ref` (1044 + 1912 + 623 + 460) согласованы с original processed records. Document `record_ref` также разрешаются корректно.

`checksums.jsonl`:

- records: 13;
- покрывает все 13 files в корне dataset, кроме самого `checksums.jsonl`;
- duplicate paths: 0;
- missing/extra paths: 0/0;
- path traversal / paths outside dataset: 0;
- SHA-256 mismatches: 0;
- size mismatches: 0.

Алгоритм обозначен полем `sha256` и описан в `schema.json` как SHA-256; отдельного поля `algorithm` нет. Checksum inventory покрывает только 14-file metadata/record package и не покрывает 460 externally referenced image bytes.

Atomic writer в `_write_dataset` (`src/dalel/curation/builder.py:518-573`) использует temp + rename и восстанавливает предыдущий output при exception внутри этой функции. Но pre-write validation errors обрабатываются раньше:

- `builder.py:218-220` вызывает `_write_failed_report`;
- `builder.py:514-515` напрямую пишет `output_dir/build_report.json`;
- проверка existing output/`--force` находится позже, в `builder.py:528-532`.

Synthetic temp test прямого failure-report path:

- before SHA-256: `b1c54824b6533ca34b95633c36b512f19af0ebe02ba41baefb25b8870640d7b6`;
- after SHA-256: `493913802d4492241d4affac3a57ceab21ed486411811071c68106699ca25363`;
- existing `status=success` был заменён на `status=failed`.

Unit test `test_atomic_write_failure_leaves_previous_dataset` monkeypatch-ит `write_checksums` и покрывает только exception внутри `_write_dataset`. Early validation failure при уже существующем dataset не тестируется.

Deterministic ordering в writers присутствует там, где records сортируются upstream. Test повторного build сравнивает только non-volatile files и явно исключает `build_report.json`, `dataset_card.md`, `checksums.jsonl`. Machine-readable evidence реального повторного production build отсутствует, а запуск `curate` в ходе этой проверки не выполнялся.

## Dataset card and grouping

`dataset_card.md` содержит требуемые разделы:

- purpose, sources, composition и counts;
- languages, regions, industries;
- OCR и weak-label limitations;
- leakage policy и table-validity policy;
- mixed-schema normalization;
- known confounders;
- prohibited uses и ethical limitations;
- version и reproduction command.

Card честно говорит, что 4 проектов недостаточно для statistically reliable risk-model training/evaluation, и запрещает random page-level split.

`document_groups.jsonl` содержит ровно 4 project groups. Каждый из 19 documents входит ровно в свою project group; cross-project records нет. `leave-one-project-out` указан как proposal, а не как надёжный финальный evaluation split. Финальный split не создан.

## P1 output inventory

Все 6 ожидаемых files существуют и не пусты:

- `project_scores.jsonl`;
- `document_scores.jsonl`;
- `findings.jsonl`;
- `metrics.json`;
- `config_snapshot.json`;
- `report.md`.

Независимый пересчёт:

- project scores: **4**;
- document scores: **19**;
- findings: **141**;
- severity: high **0**, medium **21**, low **33**, info **87**;
- priority score range: **10–82**;
- unique finding IDs: 141/141;
- invalid project/document FKs: 0;
- invalid page/evidence references: 0;
- `review_status=pending`: 141/141;
- confidence: null 141/141;
- out-of-range priority scores: 0.

Findings by type:

| Type | Count |
|---|---:|
| duplicate_heading | 87 |
| missing_expected_section | 37 |
| empty_page | 8 |
| missing_appendix_reference | 5 |
| high_ocr_dependency | 2 |
| low_text_coverage | 1 |
| suspicious_document_length | 1 |

Остальные допустимые types имеют count 0; metrics согласованы с records. Severity не представляется как probability; outputs и report называют score manual-review priority и не заявляют доказанное legal violation.

## Taxonomy verification

`config_snapshot.json` независимо проверен:

- P1 version: 1.0.0;
- taxonomy version: 1.0.0;
- scoring config version: 1.0.0;
- document types: 9;
- section rules: 34;
- unique rule IDs: 34/34;
- package profiles: 2;
- у каждого rule присутствуют `aliases_ru`, `aliases_kk`, `required`, `severity`, `rationale`, `limitations`;
- severity согласована с required/recommended;
- wording: `expected structural section (not a legal requirement)`.

Неподтверждённых нормативных утверждений в taxonomy/findings не найдено. Ограничения явно говорят, что rules не являются legal requirements. `aliases_kk` непусты у 10 из 34 rules; у остальных 24 поле существует, но список пуст. Это coverage limitation, а не schema violation.

## Section-matching verification

Реализация подтверждает NFKC, casefold/lowercase, `ё→е`, удаление leading numbering, punctuation/whitespace normalization, RU/KK aliases, token overlap и SequenceMatcher fuzzy threshold. Thresholds сохранены в config snapshot: token 0.6, fuzzy 0.82.

Независимый recomputation:

| Metric | Recomputed |
|---|---:|
| Rules evaluated | 75 |
| Matched total | 38 |
| Method `exact` | 33 |
| Method token | 4 |
| Method fuzzy | 1 |
| Unmatched required | 19 |
| Unmatched recommended | 18 |

Внутри `exact=33` только 16 являются normalized equality; **17 являются alias substring matches**, потому что `section_matcher.py:40-43` классифицирует substring как `exact`. Поэтому формулировка `exact-only baseline = 33` семантически неточна.

Ручная проверка 10 matched rules:

| Document / rule | Method | Observed heading | Verdict |
|---|---|---|---|
| Bereke NDV / NDV-S01 | exact | `5. ВВЕДЕНИЕ.` | valid |
| Bereke NDV / NDV-S03 | exact/substring | `Источники выбросов загрязняющих веществ в атмосферу` | valid |
| Bereke NDV / NDV-S04 | exact/substring | `Предложения по нормативам допустимых выбросов...` | valid |
| Bereke NDV / NDV-S06 | token | `...в периоды НМУ` | valid |
| Bereke NDV / NDV-S07 | exact/substring | `КОНТРОЛЬ ЗА СОБЛЮДЕНИЕМ НОРМАТИВОВ...` | valid |
| Bereke PEK / PEK-S01 | exact | `ВВЕДЕНИЕ` | valid |
| Bereke PEK / PEK-S04 | exact/substring | `ПЛАН-ГРАФИК ВНУТРЕННИХ ПРОВЕРОК...` | valid structural match |
| Bereke PUO / PUO-S01 | exact | `ВВЕДЕНИЕ` | valid |
| Bereke PUO / PUO-S04 | exact/substring | `Вывоз, регенерация и утилизация отходов` | valid |
| Bereke NTS / NTS-S01 | exact | `Нетехническое резюме.` | valid |

Ручная проверка 10 missing-section findings подтвердила отсутствие normalized alias среди headings для: Bereke NDV NDV-S02/NDV-S05; Bereke PEK PEK-S02/PEK-S03/PEK-S05; Bereke PUO PUO-S02/PUO-S03; Bereke action plan AP-S01/AP-S02; Bereke NTS NTS-S02. Для каждого matcher также вернул `none` ниже threshold. Эти 10 missing findings обоснованы на доступных headings.

Единственный fuzzy match невалиден:

- document: `project_003_bayterek__roos__001`;
- rule: ROOS-S05 `шумовое воздействие`;
- observed heading: `Тепловое воздействие`;
- ratio: 0.821 при threshold 0.82.

Совпадение обусловлено общим suffix `воздействие`, но смысл противоположен taxonomy rule. Fuzzy stage не требует shared discriminative token или иной semantic constraint (`section_matcher.py:60-70`), поэтому missing ROOS-S05 finding ложно подавлен.

На production corpus один heading не удовлетворил нескольким rules: reused heading groups = 0. Однако implementation не обеспечивает one-to-one assignment и теоретически позволяет reuse.

`SectionMatch` содержит `matched_title`, но `_build_metrics` сохраняет только aggregate counters. Ни `findings.jsonl`, ни отдельный match artifact не сохраняют evidence/observed heading для 38 successful matches. Поэтому matching ablation нельзя воспроизвести только из generated P1 outputs без повторного исполнения code path.

## Finding-quality review

Все 141 findings прошли Pydantic schema validation и содержат обязательные поля: ID, pillar/project/document, type, severity, priority, confidence, rule, title, explanation, evidence, page references, observed/expected values, limitations и pending review status.

- semantic duplicate findings по document/type/rule/title/evidence/value: 0;
- non-empty evidence: 14 findings; все references существуют;
- package-level findings: 0, что согласовано с полной package composition;
- missing data не переводится автоматически в high risk;
- info contribution = 2, low = 5, medium = 12;
- 87 duplicate-heading findings шумны, но имеют info severity и не представляются как violation;
- legal violation claims: 0.

Finding types с нулевым count (`missing_document`, `missing_expected_tables`, `metadata_inconsistency`, `date_range_inconsistency`, `structural_anomaly`) не обязаны присутствовать и корректно отсутствуют в metrics.

P1 finding-quality blocker связан не со schema records, а с ложным fuzzy match, который не создаёт finding там, где expected section фактически отсутствует.

## Scoring verification

Scoring implementation:

- contributions неотрицательны и объяснимы;
- document score = `min(100, sum(points))`;
- project score = `min(100, round(mean(document scores)) + package points)`;
- severity и confidence разделены; confidence во всех baseline findings равен null;
- config version сохранена в score records;
- score является review priority, не probability.

Независимый пересчёт всех 19 document scores и 4 project scores дал 0 discrepancies. Выборочная сверка:

| Object | Output | Independently recomputed | Result |
|---|---:|---:|---|
| Sintez working_project_note | 82 | 82 | pass |
| Bayterek ROOS | 65 | 65 | pass |
| Bereke NDV | 56 | 56 | pass |
| Bereke project | 27 | 27 | pass |
| Bayterek project | 40 | 40 | pass |

Остальные project scores: AZM 30, Sintez Ural 32; также совпали.

Synthetic in-memory scoring:

- info only = 2;
- medium only = 12;
- high only = 25;
- info + low = 7;
- добавление medium: 7 → 19, score не уменьшился;
- удаление low: 7 → 2, score не увеличился;
- null confidence сохранён и не преобразован в probability.

Скоринг арифметически корректен для фактических findings. Однако Bayterek ROOS score основан на неполном наборе findings из-за false fuzzy match; после исправления matcher score закономерно может измениться.

## Date-range logic

Implementation сравнивает dominant period между documents и не создаёт finding для нескольких historical ranges внутри одного document. Unit test покрывает этот случай.

Независимый recomputation dominant ranges:

- Bereke: 2025–2034 в 5 documents, согласовано;
- AZM: 2026–2035 в 4 documents с распознанными ranges, согласовано;
- Bayterek: 2020–2021 только в ROOS; второго document с dominant range нет, поэтому cross-document finding отсутствует;
- Sintez Ural: 2026–2035 в 4 documents с ranges, согласовано.

В локальных Sintez pages `2025–2034` не найдено; это значение существует только во внешней portal card. P1 не читает web/portal data. Report и finding limitations честно описывают это ограничение и не заявляют, что portal-vs-local consistency решена полностью.

`package_completeness.py` модульно отделён, поэтому в будущем может принять external metadata как новый versioned input/check. Сейчас специализированного external-metadata adapter нет, что соответствует запрету на web access в deterministic P1 baseline.

## Package completeness

Два profiles выбираются `infer_package_profile()` по максимальному overlap фактических `document_type` с `trigger_types`; hardcoded project IDs отсутствуют.

| Project | Inferred profile | Basis | Missing required |
|---|---|---|---:|
| Bereke | permit_package | ndv + pek + puo | 0 |
| AZM | permit_package | ndv + pek + puo | 0 |
| Bayterek | construction_eia | explanatory_note + roos | 0 |
| Sintez Ural | permit_package | ndv + pek + puo | 0 |

Package profile output совпадает с независимым inference. `missing_document` findings обоснованно отсутствуют. Sintez также содержит construction-oriented documents, но permit profile имеет больший trigger overlap (3 против 1), поэтому выбор детерминирован и объясним.

## Review-template verification

`data/annotations/p1_review_template.jsonl`:

- rows: 141;
- finding IDs и порядок полностью совпадают с `findings.jsonl`;
- `expert_decision`: null 141/141;
- `corrected_severity`: null 141/141;
- `expert_comment`: null 141/141;
- `reviewed_at`: null 141/141;
- `reviewer_id`: null 141/141.

Ничего не подтверждено автоматически, template не называется gold labels. `_write_outputs` создаёт template только при отсутствии файла; существующий файл не открывается на запись. Unit test проверяет, что повторный run помечает `review_template_created=False`, хотя он не вставляет synthetic human decision перед повтором. Static control flow подтверждает сохранение существующего файла.

FP candidate criterion в `pipeline.py:225-231` прозрачен: все `duplicate_heading`, `missing_appendix_reference`, `date_range_inconsistency` плюс low-severity `missing_expected_section`. Независимый count:

- duplicate headings: 87;
- appendix references: 5;
- date ranges: 0;
- low missing sections: 18;
- total: **110**, а не 111.

`metrics.json` list имеет 110 IDs, P1 `report.md` пишет 110. Ошибка 111 находится в `docs/DATASET_V1_AND_P1_REPORT.md` и повторяется в его next-step recommendation.

## Report reconciliation

| Claim | Reported | Independently recomputed | Result |
|---|---:|---:|---|
| Curated projects | 4 | 4 | pass |
| Curated documents | 19 | 19 | pass |
| Curated pages | 1044 | 1044 | pass |
| Curated sections | 1912 | 1912 | pass |
| Curated tables | 623 | 623 | pass |
| Curated image records | 460 | 460 | pass as records only |
| Physical curated images | stated “physical files checked” | 0 inside curated; 460 external processed refs | **fail** |
| Model/label separation | 19 / 4 | 19 / 4, leakage 0 | pass |
| Legacy/native schema | 17 / 2 | 17 / 2 | pass |
| Processed table gate | 632 valid, 0 invalid | 632 valid, 0 invalid | pass |
| Weak findings | 5 | 5 | pass |
| Project groups | 4 | 4 | pass |
| Machine-readable schemas | claimed for schema files | 4 feature JSONL schemas are descriptions only | **fail** |
| Atomic write | claimed atomic | early error overwrites existing report | **fail** |
| Findings total | 141 | 141 | pass |
| Severity | 21 medium / 33 low / 87 info | same | pass |
| Score range | 10–82 | 10–82 | pass |
| Taxonomy rules | 34 | 34 | pass |
| Package profiles | 2 | 2 | pass |
| Matching ablation | 33 exact / 4 token / 1 fuzzy | same method labels; exact = 16 equality + 17 substring | qualified/fail wording |
| Fuzzy match quality | not identified as error | thermal heading matched to noise rule | **fail** |
| Review-template rows | 141 | 141 | pass |
| FP candidates | 111 | 110 | **fail** |
| Tests | 107 passed, 3 deselected | 107 passed, 3 deselected | pass |
| Quality gates | all exit 0 | all final runs exit 0 | pass |

## Quality gates

| Command | Exit code | Result |
|---|---:|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run ruff format --check .` | 0 | 65 files already formatted |
| `uv run mypy src` | 0 | no issues in 46 source files |
| `uv run pytest` | 0 | 107 passed, 3 deselected, 5 warnings |
| `python3 scripts/validate_dataset_foundation.py` | 0 | READY; 0 errors, 2 `.DS_Store` warnings |
| `uv run python scripts/verify_corpus_ingestion.py` | 0 final | PASS; 23 docs, 1075 pages, 632 tables, 481 images, leakage 0 |
| `uv run dalel validate-curated --dataset data/curated/v1` | 0 | VALID by current validator; counts match, 0 reported errors |

Первый sandboxed запуск corpus verifier завершился exit 2 только из-за `Operation not permitted` при инициализации `~/.cache/uv`. Read-only rerun с разрешённым доступом к существующему uv cache завершился exit 0; это infrastructure retry, а не failure verifier-а.

`validate-curated` exit 0 не опровергает blockers: current validator специально разрешает external `source_image_path`, не требует copied image bytes/checksums, не проверяет полноту generated JSON Schema и не исполняет builder failure path.

## Blocking issues

1. **No physical/checksummed images in curated dataset.** 460 records, 0 files inside dataset, 0 image-byte checksums. Это прямое невыполнение image acceptance contract.
2. **Early-failure path corrupts an existing valid dataset.** `builder.py:218-220` + `514-515` bypass atomic temp/swap and overwrite old `build_report.json`.
3. **Incomplete distributed schema.** `reports.py:44-57` emits description-only entries for pages/sections/tables/images, despite the report claiming machine-readable schemas.
4. **Whole-dataset byte idempotency is not met/demonstrated.** The test excludes timestamp-bearing report/card/checksum files; no production repeat-build machine evidence exists.
5. **P1 false fuzzy match suppresses a real missing-section candidate.** ROOS-S05 maps `шумовое воздействие` to `Тепловое воздействие` at 0.821.
6. **P1 match evidence is not persisted and ablation wording is inaccurate.** 17 substring matches are labelled exact; successful `matched_title` evidence exists only in memory.
7. **Authoritative report count mismatch.** 111 FP candidates reported versus 110 actual.

Issues 1–4 block Dataset v1 acceptance. Issues 5–7 independently require P1 fixes even after dataset remediation.

## Non-blocking limitations

- Corpus size remains four projects; no reliable ML evaluation or final split is possible.
- 24/34 taxonomy rules have empty Kazakh alias lists; field/schema exists, but language coverage is partial.
- 87 info duplicate-heading findings are noisy and need expert calibration.
- Current matcher implementation permits one heading to satisfy several rules, though actual reused groups are 0.
- Current checksum verifier builds a dict and would not explicitly report duplicate checksum paths; actual inventory has none.
- Current image validator does not enforce path containment; actual 460 paths are safe.
- Bayterek historical period and Sintez portal-card discrepancy remain documented limitations, not false claims.
- Foundation validator emits two expected `.DS_Store` warnings; no foundation errors.
- The independent verifier did not execute `curate` or `run-p1`, so no real production rebuild/idempotency run was performed.

## Final decision

**VERIFICATION FAILED — DATASET V1 NOT ACCEPTED**

Curated logical records, reconciliation, leakage isolation, table validity, mixed-schema normalization and current checksums are internally consistent. Это недостаточно для приёмки: physical image layer отсутствует, checksum boundary не включает image bytes, early failure не атомарен, а generated schema contract неполон.

P1 arithmetic and scoring are reproducible, но section matching содержит подтверждённый false positive и недостаточную audit evidence. После исправления blockers необходимы новый controlled build, повтор всех gates и независимая reverification.

**Переход к P3 Quantitative Consistency не разрешён. P3 не запускался.**
