# Corpus Ingestion Audit — Phase 0 (revision 2)

Audit date: 2026-07-14 (revision 2 — после исправления empty-table blocker)
Предыдущая ревизия этого отчёта содержала фактические ошибки, установленные
независимой верификацией (`docs/CORPUS_INGESTION_VERIFICATION.md`); все значения
ниже пересчитаны с диска после исправления и переобработки затронутых документов.
Pipeline: `dalel ingest` (docling 2.112.0, EasyOCR 1.7.2 ru+en, OCR mode `auto`,
ingestion schema **1.1.0** для переобработанных документов, 1.0.0 для остальных).

## 0. Что изменилось после независимой верификации

Подтверждённый blocker: 54 пустых Docling table items (0 строк, 0 столбцов,
`cells=[]`, без warning) сериализовались как полноценные table records
(Sintez Ural NDV — 3, ROOS — 51). Исправление (schema 1.1.0):

- **Table validity contract**: запись сериализуется только при `num_rows > 0`,
  `num_cols > 0`, непустом `cells` и хотя бы одной непустой ячейке после trim.
- Пустые items не теряются молча: каждый даёт warning
  `empty_table_item_skipped` (document_id, page или null, docling self_ref,
  extraction_method, сообщение) и счётчики в ingestion_report.json:
  `detected_table_items` / `serialized_table_count` / `skipped_empty_table_items`;
  `table_count` означает только сериализованные валидные таблицы.
- Схемная защита: `TableRecord` отклоняет невалидные записи (model validator);
  ошибка валидации одного item становится warning, не падением документа.
- Версионирование: `INGESTION_SCHEMA_VERSION` 1.0.0 → 1.1.0 входит в cache key —
  инвалидация воспроизводима и не зависит от ручного `--force`.
- Переобработаны **только** `project_004_sintez_ural__ndv__001` и
  `project_004_sintez_ural__roos__001` (`--force`, последовательно, с ожиданием
  финальных exit code 0).
- В `scripts/verify_corpus_ingestion.py` обновлена одна константа
  `EXPECTED_COUNTS["tables"]`: 686 → 632. Причина фактическая: 686 включало 54
  пустых артефакта; 632 — валидное число, установленное самим верификатором.
  Проверки качества записей не ослаблялись (пустая таблица без warning — ошибка).

## 1. Expected vs actual (verifier exit 0)

| Метрика | Expected | Actual | Статус |
|---|---:|---:|---|
| Model inputs | 19 | 19 | ✅ |
| Label sources | 4 | 4 | ✅ |
| Auxiliary archive | 1 skipped | 1 skipped, не распакован | ✅ |
| Ingestion reports | 23 | 23 | ✅ |
| Pages | 1075 | 1075 | ✅ |
| **Tables (валидные, сериализованные)** | **632** | **632** | ✅ |
| — model inputs | 623 | 623 | ✅ |
| — label sources | 9 | 9 | ✅ |
| **Skipped empty table items** | 54 | 54 (NDV 3 + ROOS 51) | ✅ |
| Images (records = files) | 481 | 481 | ✅ |
| OCR pages | 98 | 98 | ✅ |
| Invalid empty tables без warning | 0 | **0** | ✅ |
| Hash violations | 0 | 0 | ✅ |
| Provenance violations | 0 | 0 | ✅ |
| Leakage violations | 0 | 0 | ✅ |
| Failed documents | 0 | 0 | ✅ |

`uv run python scripts/verify_corpus_ingestion.py` → **exit 0, FINAL VERIFICATION STATUS: PASS**.

## 2. Результаты по проектам (model inputs)

| Проект | Док. | Статусы | Стр. | Валидных таблиц | Skipped empty | Изобр. | OCR-стр. |
|---|---:|---|---:|---:|---:|---:|---:|
| project_001_bereke | 5 | 5 success | 238 | 138 | 0 | 157 | 24 |
| project_002_azm | 5 | 4 success + 1 partial | 228 | 164 | 0 | 77 | 0 |
| project_003_bayterek | 2 | 1 success + 1 partial | 156 | 75 | 0 | 113 | 3 |
| project_004_sintez_ural | 7 | 5 success + 2 partial | 422 | **246** | **54** | 113 | 55 |
| **Итого model inputs** | **19** | 15 success + 4 partial | **1044** | **623** | **54** | **460** | **82** |

Label sources (отдельное дерево): 4 документа, 3 success + 1 partial, 31 стр.,
9 валидных таблиц, 21 изображение, 16 OCR-страниц.

Статусы корпуса: **18 success + 5 partial** — не изменились после переобработки
(Sintez ROOS был и остался `success`: пропуск пустых таблиц по политике — warning,
не смена статуса; Sintez NDV остался `partial` из-за прежних OCR-policy страниц).

## 3. Переобработанные документы (до/после)

| Документ | Raw table items | Было записей | Стало валидных | Skipped | Статус | Hash |
|---|---:|---:|---:|---:|---|---|
| sintez_ural NDV | 102 | 102 (3 пустых без warning) | **99** | 3 (стр. 71, 77, 87) | partial (не изменился) | unchanged ✅ |
| sintez_ural ROOS | 73 | 73 (51 пустой без warning) | **22** | 51 (стр. 39–57, 59, 60) | success (не изменился) | unchanged ✅ |

Каждый пропуск зафиксирован warning-ом вида
`empty_table_item_skipped: document_id=… page=… ref=#/tables/NN method=docling — …`.
Прочие counts переобработки детерминистично совпали с прежними
(NDV: 135 стр./76 изобр./53 OCR; ROOS: 60/4/0).

## 4. Warnings и errors (фактические значения)

- **Errors: 0** во всех 23 отчётах.
- **Document warnings: 65** (61 в model inputs, 4 в label sources):
  - 54 × `empty_table_item_skipped` (только два документа Sintez Ural);
  - 5 × `pages without text after OCR policy` (5 partial-документов);
  - 5 × `ocr_language_unsupported: kk` — AZM NDV, Bayterek ROOS, протокол AZM,
    оба протокола Bayterek. Warning выводится из метаданных языков проекта,
    поэтому стоит и на русском протоколе Bayterek — это не page-level
    language detection;
  - 1 × DOCX pseudo-page notice.
- Предыдущая ревизия занижала счёт (10 вместо тогдашних 11, kk 4 вместо 5) —
  исправлено.

## 5. Страницы без пригодного текста (раздельно)

OCR-кандидаты (страницы без embedded text), не давшие ≥32 симв. после OCR-политики:

- **model inputs: 10** из 92 кандидатов (82 приняты OCR);
- **label sources: 6** из 22 кандидатов (16 приняты OCR);
- корпус: 16 из 114. (Предыдущая ревизия ошибочно называла 16 «страницами
  model inputs» — это корпусное число.)

Все 5 partial-статусов объяснены и подтверждены независимой проверкой исходных
страниц (векторные карты/схемы, почти пустые страницы, растровые листы подписей).

## 6. DOCX (исправленное описание)

`project_002_azm__nontechnical_summary__001`: success, docling, `docx_flow`,
одна псевдо-страница (3194 симв., геометрия null с warnings), 1 секция,
**0 таблиц, 1 изображение**. Прямая инспекция DOCX: в источнике **нет** элементов
`<w:tbl>`, поэтому 0 таблиц — корректный результат, а не дефект. Утверждение
предыдущей ревизии об «извлечённой таблице» DOCX было ошибочным и снято.

## 7. Label-source таблицы: качество OCR

- Протокол AZM `tab_0007` (8×18): непустая, но OCR-шумная.
- **Bayterek RU протокол `tab_0001` (5×13): видимо OCR-повреждённая** — записана
  честно, но **не должна использоваться как надёжный structured label source без
  ручной проверки**. Ограничение шире, чем «только казахский»: русский скан
  также повреждён.
- Казахские сканы: EasyOCR не поддерживает kk; распознавание ru+en, качество
  ограничено по построению.

## 8. Hash integrity, provenance, leakage, идемпотентность

- Hash-цепочка (physical raw == manifest == document == report before/after,
  `hash_unchanged=true`) — 23/23, нарушений 0. `data/raw/**`, manifest,
  inventory, source_metadata, annotations не изменялись.
- Provenance: 4143 записи проверены верификатором, нарушений 0.
- Leakage: label sources только в `label_sources/`; в model_inputs project.json —
  только skip-записи; RAR не распакован; weak findings не затронуты. Нарушений 0.
- **Cache/idempotency (независимо воспроизводимый тест выполнен):** для
  переобработанного Sintez NDV сняты SHA-256 и наносекундные mtimes всех 82
  файлов output-директории и raw-файла; обычный `dalel ingest` без `--force`
  дал `skipped_cached` (exit 0); все 82 файла побайтно идентичны, mtimes
  нетронуты, raw hash/mtime без изменений.

## 9. Quality gates (все зелёные)

| Команда | Результат |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | OK |
| `uv run mypy src` | Success: no issues in 24 source files |
| `uv run pytest` | **76 passed** (3 integration deselected) |
| `python3 scripts/validate_dataset_foundation.py` | READY, Errors: 0 |
| `uv run python scripts/verify_corpus_ingestion.py` | **exit 0, PASS** |

Regression-тесты blocker-а: `tests/unit/test_table_validity.py` — пустой 0x0 item,
таблица со сплошь пустыми ячейками, валидная таблица, смешанный документ,
schema-отклонение, счётчики, изменение cache key при смене версии.

Notebook `notebooks/01_ingestion_audit.ipynb` перегенерирован (добавлен показ
`skipped_empty_table_items`) и исполнен без ошибок; executed-копия —
`notebooks/01_ingestion_audit_executed.ipynb` (623 валидных model-input таблицы,
54 пропущенных item — совпадает с данным отчётом).

## 10. Ограничения

1. **Смешанные версии схемы в корпусе**: 2 документа — schema 1.1.0, 21 — 1.0.0.
   Содержательно все 21 нетронутых документа уже удовлетворяют table-контракту
   (верификатор: 0 невалидных таблиц вне Sintez). Версия входит в cache key,
   поэтому любой будущий непринудительный прогон воспроизводимо переработает
   старые outputs под 1.1.0; в рамках данной задачи не выполнялось (запрещено
   без отдельного решения).
2. 54 пропущенных table items — артефакты layout-модели Docling на страницах
   с векторной графикой/картами (ROOS стр. 39–60) и иллюстрациями (NDV): item
   обнаружен, но TableFormer не нашёл ни одной ячейки. Не конвертируются в
   изображения автоматически (запрещено политикой) — кандидаты на ручную оценку.
3. Bayterek RU/KK протокольные таблицы OCR-повреждены (§7) — не использовать
   как structured labels без ручной проверки.
4. EasyOCR без kk; `ocr_language_unsupported` — метаданные проекта, не
   page-level детекция (§4).
5. 16 страниц корпуса (10 mi + 6 ls) без пригодного текста — свойство исходников.
6. DOCX псевдо-страница без геометрии; notebook без криптографического
   execution-provenance (известное ограничение артефакта).
7. Валидность таблиц не сверяет `num_rows/num_cols` с фактической формой grid
   (несоответствий в корпусе нет — проверено верификатором на всех записях).

## 11. Статус

**READY FOR INDEPENDENT RE-VERIFICATION**

Все известные blocker-ы устранены; verifier проходит с exit 0 локально. Решение
о READY FOR DATASET V1 принимает независимый верификатор. Dataset v1, P1–P3,
LLM/RAG, scoring, CML и frontend не начинались.
