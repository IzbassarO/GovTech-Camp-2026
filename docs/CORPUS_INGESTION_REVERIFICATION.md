# Independent Corpus Re-verification

Дата повторной проверки: 2026-07-14.

Проверка выполнена непосредственно по рабочему дереву, canonical manifest, raw-файлам
и `data/processed/**`. Ingestion, `--force`, изменение processed outputs, Dataset v1,
pillars, LLM/RAG, scoring и CML не запускались. Единственное созданное проверяющим
лицом содержимое — этот отчёт.

## Executive verdict

**VERIFIED — READY FOR DATASET V1**

Empty-table blocker устранён в коде и в двух затронутых output-директориях. Все
632 сериализованные таблицы независимо проверены и валидны; 54 пустых Docling item
не сериализованы, но отражены отдельными warning и согласованными счётчиками.
Hash, provenance и leakage нарушений не найдено. Все обязательные quality gates
завершились с exit code 0.

Смешанный корпус из schema 1.0.0 и 1.1.0 допустим для Curated Dataset v1 при
явной нормализации report counters, описанной ниже. Полный refresh 21 старого
документа перед Dataset v1 не требуется.

У текущего verifier есть две реальные, но не блокирующие для уже проверенного
корпуса слабости: warned-empty table record может пройти его table-check, а новые
три table counters им не сверяются. Поэтому Dataset builder не должен полагаться
только на текущий verifier и обязан сам применять строгий table contract.

## Git diff reviewed

Состояние рабочего дерева до создания этого отчёта:

- staged changes: 0;
- tracked diff: 11 файлов, 227 additions, 41 deletions;
- изменены:
  - `notebooks/01_ingestion_audit.ipynb`;
  - `scripts/verify_corpus_ingestion.py`;
  - `src/dalel/config.py`;
  - `src/dalel/ingestion/docling_parser.py`;
  - `src/dalel/ingestion/docx_fallback.py`;
  - `src/dalel/ingestion/parsed.py`;
  - `src/dalel/ingestion/pipeline.py`;
  - `src/dalel/ingestion/pymupdf_fallback.py`;
  - `src/dalel/ingestion/reports.py`;
  - `src/dalel/schemas/document.py`;
  - `src/dalel/schemas/table.py`.
- новые относящиеся к исправлению файлы:
  - `tests/unit/test_table_validity.py`;
  - `docs/CORPUS_INGESTION_AUDIT.md`;
  - `notebooks/01_ingestion_audit_executed.ipynb`.

В worktree также уже находились пять неотслеживаемых PDF/DOCX в `docs/`; они не
относятся к empty-table fix и не изменялись в ходе этой проверки.

Полный diff не ослабил прежние защитные границы:

- pre/post raw SHA-256 check и отказ от записи при изменении bytes остались в
  `src/dalel/ingestion/pipeline.py:252-315`;
- routing и разделение `model_inputs` / `label_sources` не менялись;
- построение provenance из manifest path/hash осталось в
  `src/dalel/ingestion/pipeline.py:559-579`;
- исключение одного документа по-прежнему перехватывается внутри batch loop,
  логируется и не останавливает следующие документы
  (`src/dalel/ingestion/pipeline.py:146-184`);
- verifier diff меняет только expected table count и поясняющий комментарий;
  hash, provenance, leakage и record-level checks из него не удалялись;
- cache key усилен schema version bump, а не ослаблен.

## Root cause confirmation

Root cause подтверждён сравнением текущего diff с `HEAD` до исправления:

1. Docling мог вернуть table item без grid: `num_rows=0`, `num_cols=0`,
   `cells=[]`.
2. Прежний `_build_tables` всё равно создавал `ParsedTable` для каждого item;
   исключение при чтении grid только добавляло warning, а `continue` отсутствовал.
3. Прежний `TableRecord` имел permissive defaults `0/0/[]` и не имел model
   validator.
4. Прежний pipeline без повторной проверки добавлял каждый `ParsedTable` в
   `tables.jsonl`.

Таким образом, первопричиной был не сам факт появления пустых Docling detections,
а отсутствие единого validity contract на parser, pipeline и schema boundaries.
Это точно объясняет ранее найденные 54 records: 3 в Sintez NDV и 51 в Sintez
ROOS. Предыдущий независимый отчёт фиксировал 686 total records, из которых 54
были 0×0, то есть 632 фактически пригодных.

## Table validity implementation

Текущий contract в `src/dalel/schemas/table.py:17-21` возвращает `true` только
если одновременно:

- `num_rows > 0`;
- `num_cols > 0`;
- `cells` не пуст;
- хотя бы одна ячейка непуста после `strip()`.

Защита реализована в трёх слоях:

1. Parser layer:
   - Docling фильтрует item и сохраняет `page_number`, `self_ref`, method и reason
     в `SkippedTableItem` (`docling_parser.py:180-244`);
   - PyMuPDF и python-docx fallback применяют тот же helper и также сохраняют
     skip metadata (`pymupdf_fallback.py:58-104`, `docx_fallback.py:108-150`).
2. Pipeline layer повторно применяет contract к каждому parser result, использует
   `continue` и нумерует только реально сериализованные таблицы
   (`pipeline.py:629-669`).
3. Schema layer отклоняет invalid `TableRecord` model validator-ом
   (`schemas/table.py:41-49`). `ValidationError` одного item перехватывается,
   превращается в skip и не завершает документ (`pipeline.py:670-678`).

`SkippedTableItem` является отдельным типом и не добавляется в `ParsedImage`.
Image loop работает только с `parsed.images`; пути автоматической конвертации
пустой таблицы в image в diff нет. Фактический image total после исправления
остался 481.

На каждый skip pipeline создаёт отдельный `empty_table_item_skipped` warning с
`document_id`, `page` или `null`, `ref` или `null`, extraction method и reason
(`pipeline.py:538-546`). Report записывает `detected_table_items`,
`serialized_table_count` и `skipped_empty_table_items`
(`pipeline.py:318-343`, `schemas/document.py:103-108`).

Contract намеренно не проверяет форму grid против dimensions. Это не входило в
заявленный минимальный contract; независимая дополнительная проверка всех
outputs всё равно установила 0 shape mismatches.

## Regression-test quality

`tests/unit/test_table_validity.py` содержит 7 содержательных тестов. Они
проверяют:

- helper на valid, 0×0, нулевую одну из dimensions, пустой grid и all-blank grid;
- смешанный документ с одной валидной, двумя pipeline-invalid и одной
  parser-pre-skipped таблицей;
- сохранение валидной таблицы и последовательного `tab_0001`;
- наличие skip warnings и report counters;
- продолжение batch и успешную обработку следующего DOCX;
- Pydantic rejection invalid records;
- превращение layer-3 `ValidationError` в skip, а не crash;
- различие cache keys для schema 1.0.0 и 1.1.0.

Качество assertions достаточно для регрессии центрального pipeline behavior,
но не исчерпывающее:

- реальный `docling_parser._build_tables` не тестируется напрямую: layer-1 skip
  имитируется готовым `SkippedTableItem`;
- fallback implementations не имеют отдельных direct tests в этом файле;
- warning test использует несколько `any(...)`, а не проверяет каждый warning
  на полный набор полей и reason;
- нет отдельного assertion, что skip не увеличивает images;
- report model не имеет собственного invariant
  `detected == serialized + skipped`;
- тесты не покрывают найденные ниже ограничения corpus verifier.

Эти пробелы не опровергают исправление: реальный corpus, все warnings и все
счётчики были дополнительно проверены независимо.

## Independently recomputed totals

Значения получены отдельным read-only обходом `data/processed/**`, без импорта
`EXPECTED_COUNTS`:

| Метрика | Фактическое значение |
|---|---:|
| Model inputs | 19 |
| Label sources | 4 |
| Ingestion reports | 23 |
| Pages | 1,075 |
| Sections | 1,955 |
| Serialized tables | 632 |
| Images records | 481 |
| Physical image files | 481 |
| OCR pages | 98 |
| Success | 18 |
| Partial | 5 |
| Failed | 0 |
| Report errors | 0 |
| Document warnings | 65 |
| `empty_table_item_skipped` | 54 |
| Parser/version | docling 2.112.0: 23/23 |
| Hash violations | 0 |
| Provenance violations | 0 |
| Leakage/routing violations | 0 |

Warnings независимо классифицированы как 54 empty-table skip, 5
`pages without text after OCR policy`, 5 `ocr_language_unsupported: kk` и 1
DOCX pseudo-page warning. Model inputs содержат 61 warning, label sources — 4.

Canonical manifest содержит ровно те же 19 model inputs и 4 label sources;
missing и unexpected output documents отсутствуют. Role, project_id,
document_type, `use_as_model_feature`, `label_timing`, source path и source hash
совпали для 23/23 документов. Физический SHA-256 каждого raw совпал с manifest,
`document.json`, `raw_hash_before` и `raw_hash_after`.

## Validation of 632 serialized tables

Все строки всех 23 `tables.jsonl` проверены независимо. Результат:

| Проверка | Нарушений |
|---|---:|
| `num_rows > 0` | 0 |
| `num_cols > 0` | 0 |
| `cells` не пуст | 0 |
| хотя бы одна non-blank cell | 0 |
| `len(cells) == num_rows` | 0 |
| длина каждой строки равна `num_cols` | 0 |
| уникальный `table_id` | 0; 632/632 уникальны |
| корректный project/document provenance | 0 |
| page number корректен либо null | 0; null page values: 0 |
| bbox object, orientation и page bounds корректны либо null | 0; null bbox values: 0 |
| source path/SHA-256 согласован | 0 |
| extraction method указан | 0 |
| parser name/version согласован | 0 |

Из них 511 records имеют schema 1.0.0, 121 — schema 1.1.0. Полный список
invalid records пуст: **invalid serialized tables = 0**.

## Validation of 54 skipped items

| Документ | Detected | Serialized | Skipped | Проверка |
|---|---:|---:|---:|---|
| `project_004_sintez_ural__ndv__001` | 102 | 99 | 3 | 102 = 99 + 3 |
| `project_004_sintez_ural__roos__001` | 73 | 22 | 51 | 73 = 22 + 51 |
| **Итого** | **175** | **121** | **54** | **175 = 121 + 54** |

NDV warnings ссылаются на `#/tables/44` (page 71), `#/tables/54` (page 77)
и `#/tables/78` (page 87). ROOS содержит 51 уникальный ref от
`#/tables/22` до `#/tables/72`, на pages 39–60. Для всех 54 warnings имеются
document_id, page, ref, method `docling`, понятный reason и явное сообщение, что
item не сериализован.

В `tables.jsonl` нет ни одной записи, нарушающей table contract; фактические
counts уменьшились ровно на 3 и 51. Однако parser-native `self_ref` не хранится в
`TableRecord`, поэтому выполнить прямой foreign-key anti-join каждого warning ref
к `tables.jsonl` невозможно. Отсутствие подтверждается согласованными counters,
нулём invalid records и последовательными IDs валидных таблиц, но schema не даёт
стабильного per-item linkage. Это non-blocking observability limitation.

## Verifier modification review

Diff `scripts/verify_corpus_ingestion.py` меняет только
`EXPECTED_COUNTS["tables"]` с 686 на 632 и добавляет поясняющий комментарий.
Никакие record-level table, shape, provenance, hash или leakage checks не удалены.

Изменение expected count корректно:

- предыдущая независимая проверка документировала 686 records и ровно 54
  invalid 0×0 artifacts;
- текущий независимый обход диска дал 632;
- 632 records прошли строгий contract;
- 632 + 54 = 686.

Таким образом, новая константа не маскирует текущую ошибку. Verifier также не
доверяет только aggregate constant: `validate_tables` проверяет IDs, page,
provenance, dimensions, grid shape, content и bbox.

Synthetic in-memory test выявил более узкую слабость в
`scripts/verify_corpus_ingestion.py:680-688`:

- 0×0 record с `warnings=[]` добавляется в `invalid_tables` и errors;
- тот же 0×0 record с любым непустым `warnings` не считается invalid и проходит
  этот check.

Это не соответствует новому правилу «invalid table никогда не сериализуется».
Кроме того, поиск и code review показали, что verifier не сверяет
`detected_table_items`, `serialized_table_count` и
`skipped_empty_table_items`. На текущем корпусе их согласованность установлена
отдельной проверкой, но verifier сам её не гарантирует.

Assessment: expected-count change принят; текущий PASS подтверждается независимым
более строгим scan, но verifier до его будущего усиления не должен быть
единственным table-quality gate.

## Cache-version review

`INGESTION_SCHEMA_VERSION = "1.1.0"` задан в `src/dalel/config.py:11-15`.
`compute_cache_key` включает `schema={schema_version}` вместе с source hash,
parser/OCR identities и OCR mode (`src/dalel/ingestion/storage.py:31-43`).
`is_cached` требует совпадающий key, success/partial status и все пять core
output files (`storage.py:70-82`).

Unit test прямо доказывает, что одинаковые inputs дают разные keys для 1.0.0 и
1.1.0. Дополнительная read-only проверка с фактическими parser identities
(`docling 2.112.0`, `pymupdf 1.28.0`, `python-docx 1.2.0`, EasyOCR 1.7.2,
Tesseract absent) показала:

- оба schema 1.1.0 report keys совпадают с текущим вычислением и оба
  `is_cached=True`;
- ни один из 21 schema 1.0.0 report keys не совпадает с текущим key и для них
  `is_cached=False`.

Следовательно, version bump действительно и воспроизводимо инвалидирует старый
cache. Ingestion для этой проверки не запускался.

## Mixed-schema analysis

Фактическое распределение документов: 21 × schema 1.0.0 и 2 × schema 1.1.0.
Внутри каждого document directory версии всех JSON/JSONL records согласованы.
Project summaries: 3 × 1.0.0 и 1 × 1.1.0.

Сравнение полных key sets установило:

- `document.json`, `pages.jsonl`, `sections.jsonl`, `tables.jsonl` и
  `images.jsonl` имеют одинаковую структуру в обеих версиях; отличается только
  значение `schema_version`;
- в `ingestion_report.json` schema 1.1.0 добавлены ровно три поля:
  `detected_table_items`, `serialized_table_count`,
  `skipped_empty_table_items`;
- все 511 таблиц из 21 старого документа проходят новый contract и shape checks;
- старый pipeline сериализовал каждый обнаруженный Docling table item, поэтому
  при отсутствии invalid records для этих конкретных outputs значения
  однозначно выводятся как:
  `serialized_table_count = table_count`,
  `detected_table_items = table_count`,
  `skipped_empty_table_items = 0`.

Решение: **A. Mixed schema допустима.** Curated builder должен ветвиться по
`schema_version` и явно применять указанную нормализацию для 1.0.0. Нельзя просто
загрузить старый report в текущую Pydantic model и принять defaults `0`, потому
что это ошибочно обнулит detected/serialized counters у документов с таблицами.

Полный refresh до 1.1.0 удобен для будущей унификации, но не является blocker
перед Dataset v1 и сейчас не требуется.

## Cache/idempotency evidence

`docs/CORPUS_INGESTION_AUDIT.md` утверждает, что для Sintez NDV были сняты SHA-256
и nanosecond mtimes 82 output-файлов и raw, затем обычный ingest вернул
`skipped_cached` с exit 0 без изменений.

На диске независимо подтверждаются:

- 82 текущих файла в NDV output directory;
- raw SHA-256
  `3944f6a4d37c3107392b2494bb276477b32f344a416d903f8c12fe27e17e2d22` совпадает
  с manifest и report before/after;
- текущий stored cache key совпадает с вычисленным 1.1.0 key;
- `is_cached` сейчас возвращает true;
- project summary был сгенерирован после document report, что совместимо с
  описанным cache run.

Но отдельный machine-readable pre/post snapshot checksums/mtimes или CLI log в
репозитории не сохранён. Поэтому исторический факт `skipped_cached` и равенство
pre/post mtimes нельзя независимо доказать только по текущему состоянию, а новый
ingestion запрещён условиями задачи. Это **неполностью подтверждённое,
non-blocking evidence limitation**: cache code, versioning, tests и текущая
cache eligibility независимо подтверждены.

## Report reconciliation

`docs/CORPUS_INGESTION_AUDIT.md` сверён с диском:

| Заявление | Независимая проверка |
|---|---|
| tables 632 | совпало |
| warnings 65 | совпало: 61 model + 4 label |
| `ocr_language_unsupported` 5 | совпало |
| unreadable model-input pages 10 | совпало |
| unreadable label-source pages 6 | совпало |
| DOCX tables 0 | совпало; в source `word/document.xml` найдено 0 `<w:tbl>` |
| 54 skipped tables | совпало: 3 + 51 |
| Bayterek RU table ненадёжна | корректно отмечено; фактическая 5×13 grid явно OCR-повреждена |
| hash/provenance/leakage 0 | совпало |
| cache test | только частично независимо доказуем, см. предыдущий раздел |

Фраза отчёта о том, что verifier считает ошибкой «пустую таблицу без warning»,
буквально верна, но слабее нового contract: warned-empty verifier пропускает.

## Notebook verification

`notebooks/01_ingestion_audit.ipynb` является source notebook без execution
counts. `notebooks/01_ingestion_audit_executed.ipynb` действительно исполнен:

- 10 code cells имеют последовательные execution counts 1–10;
- error outputs: 0;
- source всех 19 cells байтово-эквивалентен source notebook;
- output показывает 19 model inputs, 1,044 pages, 623 valid tables, 460 images и
  54 skipped items — все model-input counts совпадают с независимым обходом.

Notebook по замыслу читает только `model_inputs`, поэтому не является полным
corpus verifier для 4 label sources. Warning display также группирует только
первые 100 символов и показывает top 20, поэтому число 65 следует брать из
полного corpus scan/report, а не из этого notebook view. Эти ограничения честно
не меняют совпадение показанных counts.

## Quality gates

Все команды запущены после read-only проверок; код и outputs не исправлялись.

| Команда | Exit code | Результат |
|---|---:|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run ruff format --check .` | 0 | 40 files already formatted |
| `uv run mypy src` | 0 | no issues in 24 source files |
| `uv run pytest` | 0 | 76 passed, 3 deselected; 5 SWIG deprecation warnings |
| `python3 scripts/validate_dataset_foundation.py` | 0 | READY; 0 errors, 2 warnings о ignored `data/raw/.DS_Store` |
| `uv run python scripts/verify_corpus_ingestion.py` | 0 | PASS; 0 blocking errors, invalid tables 0 |

Verifier дополнительно сообщил 5 пустых JSONL-файлов, соответствующих честным
нулевым коллекциям; это информационный список, не blocking error.

## Blocking issues

**Нет.** Исправление, два обновлённых документа, total 632 и отсутствие invalid
serialized tables подтверждены независимо. Ни mixed schema, ни ограничения
cache evidence не требуют остановки Dataset v1.

## Non-blocking limitations

1. Corpus verifier пропускает empty record, если у него непустой `warnings`, и не
   проверяет новые три counters. До исправления на него нельзя полагаться как на
   единственный table gate.
2. Machine-readable pre/post evidence исторического cache/idempotency run не
   сохранён; повторный ingest в этой задаче был запрещён.
3. Parser `self_ref` skip item не сериализуется как отдельное структурированное
   поле, поэтому прямой per-item anti-join невозможен.
4. Regression tests качественно покрывают pipeline contract, но не вызывают
   реальный Docling layer-1 и оба fallback table extractors напрямую.
5. Curated builder обязан явно нормализовать schema 1.0.0 report counters и сам
   повторить строгий table validity check.
6. Bayterek RU/KK OCR tables нельзя считать надёжными structured labels без
   ручной проверки; EasyOCR не поддерживает kk.
7. 16 страниц (10 model inputs + 6 label sources) не дали пригодного текста после
   OCR policy; это ранее объяснённое свойство источников, не empty-table regression.

## Final decision

**VERIFIED — READY FOR DATASET V1**

Запуск Curated Dataset v1 разрешён с соблюдением leakage boundary и следующих
обязательных условий builder-а:

- строгий table contract применяется независимо от текущего verifier;
- schema 1.0.0 counters нормализуются как описано в mixed-schema разделе;
- label sources остаются отдельными от pre-review model features;
- OCR-повреждённые protocol tables не принимаются как надёжные structured labels
  без ручной проверки.

Dataset v1 и последующие фазы в ходе этой повторной проверки не запускались.
