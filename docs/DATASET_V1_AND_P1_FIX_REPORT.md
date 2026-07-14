# Dataset v1 + P1 — Fix Report (после независимой верификации)

Дата: 2026-07-14
Вход: `docs/DATASET_V1_AND_P1_VERIFICATION.md` (VERIFICATION FAILED — DATASET V1 NOT ACCEPTED).
Исправлены все 7 подтверждённых blockers (A–H задачи / 1–7 вердикта). Git commit/push
не выполнялись; `data/raw`, `data/processed`, манифесты, weak findings и сам
verification report не изменялись. P3 не начинался.

## Root causes

| # | Blocker | Первопричина |
|---|---|---|
| A | 0 физических изображений в датасете | Builder ссылался на processed-файлы (`source_image_path`), не копируя байты; checksums покрывали только 13 корневых файлов |
| B | Early-failure перезаписывал `build_report.json` | `_write_failed_report()` писал в production-директорию до atomic swap |
| C | Неполный `schema.json` | Для passthrough-файлов писались только текстовые descriptions |
| D | Byte-idempotency не доказана | Wall-clock timestamps в build report/card → каскад в checksums; тест исключал эти файлы |
| E | Ложный fuzzy «шумовое воздействие»→«Тепловое воздействие» | Fuzzy принимал ratio ≥0.82 без семантического ограничения; общий generic-суффикс «воздействие» давал 0.821 |
| F | 17 substring-совпадений названы exact | Одна ветка кода классифицировала equality и substring одинаково |
| G | Evidence успешных matches не сохранялся | `matched_title` жил только в памяти; сериализовались лишь агрегаты |
| H | 111 vs 110 FP candidates | Число в основном отчёте писалось вручную, без единого источника |

## A. Физические curated images

`data/curated/v1/images/<project_id>/<document_id>/<file>.png` — **460 файлов
скопировано детерминированно** (сортировка по curated-пути). Каждая запись
`images.jsonl` теперь содержит: `curated_image_path` (dataset-относительный,
проверка компонентов пути от traversal), `image_sha256`, `image_size_bytes`,
`source_image_path` (processed-provenance) + прежний `record_ref`. Label-source
изображения не копируются (в `images/` только 2 model-input document-id на
проект-фикстуре и 19 на production). Проверено: records=460, physical=460,
unique paths=460, checksum mismatches=0, traversal=0. `checksums.jsonl` теперь
покрывает **473** файла, включая все 460 изображений.

## B. Атомарность

`_write_failed_report` удалён. Порядок: полный build во временной sibling-директории
(JSON/JSONL + изображения + schema + card + report) → `validate_curated_dataset(tmp)`
→ `write_checksums(tmp)` → повторная `verify_checksums(tmp)` → только затем atomic
swap (rename старого в trash → rename tmp → удаление trash с восстановлением при
сбое). При любой ошибке: tmp удаляется, production не тронут, ошибки — в
stderr/результат, никакого файла в output. Production-проверка: неуспешный запуск
поверх существующего датасета — exit 1, **474/474 файлов: 0 изменённых байт и
mtime, 0 tmp-остатков**. Regression: `test_failed_build_preserves_existing_dataset_bytes_and_mtimes`.

## C. Schema completeness

Новые production-модели: `CuratedPageRecord/CuratedSectionRecord/CuratedTableRecord/
CuratedImageRecord` (наследники ingestion-моделей + curated-поля), `BuildReportModel`,
`DatasetStatisticsModel`. `schema.json` содержит полные `model_json_schema()` для всех
**10** типов записей (properties, required, types, nullable (anyOf/null), `$defs` c
вложенными Provenance/BBox/RecordRef, enums/constraints где есть). Builder валидирует
каждую запись через эти модели при сборке; `validate-curated` — повторно при проверке
и дополнительно требует machine-readable схему для каждого файла
(`test_validator_rejects_incomplete_schema`).

## D. Byte idempotency

Timestamps исключены из versioned-артефактов: идентичность = `input_fingerprint`.
Сериализация: фиксированный порядок полей моделей, отсортированные records/checksums,
`\n`, без абсолютных путей. Integration-тест `test_two_builds_byte_identical`
сравнивает все файлы без исключений.

**Примечание (следующая итерация):** первоначальный алгоритм fingerprint (v1,
`7f9fde0f…`) хешировал annotations-директорию целиком и захватывал downstream
`p1_review_template.jsonl`; после запуска P1 он переставал воспроизводиться —
подтверждено повторной верификацией. Заменён на `dalel-input-inventory/v2`
(явный inventory 584 upstream-файлов, `input_manifest.jsonl` в датасете,
fingerprint `772694f4…` стабилен до/после P1; 475/475 файлов IDENTICAL) — см.
`docs/DATASET_V1_SCHEMA_AND_FINGERPRINT_FIX_REPORT.md`.

## E–F. Matching: методы до/после

| До (2 метода в отчётности) | После (4 метода) |
|---|---|
| exact = 33 (равенство И подстрока) | **exact_equality = 16** |
| — | **normalized_substring = 17** |
| token = 4 | token_overlap = 4 |
| fuzzy = 1 (ложный) | fuzzy = 0, **rejected_fuzzy_candidates = 2** |

Разбиение 16/17 в точности совпало с независимым пересчётом верификатора.
Fuzzy теперь требует discriminative evidence: общий не-generic токен (точный или
per-token ratio ≥0.85); generic-токены («воздействие», «раздел», «мероприятия»,
«охрана», «оценка», «сведения»… — полный список в config_snapshot) не считаются
evidence. Regression: «шумовое воздействие» ↛ «Тепловое воздействие» (кандидат
записан отклонённым с причиной и ratio 0.821); positive fuzzy сохранён
(«Введени» → «введение», per-token 0.93). Порог 0.82 не менялся — ужесточение
через evidence, не отключение fuzzy.

## G. section_matches.jsonl

**37 записей** — evidence каждого accepted match: match_id, project/document,
rule_id, canonical_section, matched_alias, observed_heading, normalized_heading,
page_number, method, match_score, discriminative_tokens, limitations. Ablation
воспроизводима из артефактов без повторного исполнения кода. Отклонённые fuzzy —
в `metrics.json → rejected_fuzzy_examples`.

## Эффект на findings/scores

Ложный fuzzy подавлял missing-finding ROOS-S05 для Bayterek ROOS. После исправления:
**142 findings** (было 141): +1 low `missing_expected_section` (ROOS-S05, Bayterek;
Sintez ROOS имел его и раньше). Severity: medium 21, low 34, info 87.
Bayterek ROOS score 65 → **70** (+5 за low). Диапазон 10–82 сохранился;
остальные скоры не изменились. Finding-id теперь content-stable
(SHA-256 от project|document|type|rule|title) — безопасны для merge шаблона.

## H. FP candidates

Единственный источник — `is_false_positive_review_candidate()` в pipeline;
metrics-поле `false_positive_review_candidate_count`, список id, report.md и
основной отчёт используют только его. Фактическое значение после исправления
matching: **111** (87 duplicate_heading + 5 appendix + 19 low missing-sections;
восстановленная ROOS-S05-находка — low → вошла в кандидаты). Совпадение с прежним
неверным «111» — арифметическое совпадение после +1 находки, а не подгонка:
поле, список и отчёты равны по построению.

## Review template preservation

`_merge_review_template`: существующие человеческие решения сохраняются по
(content-stable) finding_id; новые findings добавляются пустыми строками; строки
исчезнувших findings уходят в `data/results/p1/v1/review_template_stale.jsonl`
(не создан — stale строк нет); экспертные поля никогда не перетираются пустыми.
Старый template (141 строка, 0 заполненных) регенерирован под стабильные id.
Regression: `test_review_template_preserves_human_decisions` (заполненное
`expert_decision='confirmed'` переживает повторный запуск).

## Tests

**123 passed** (было 107): +16 новых регрессий по списку задачи — curated (physical
copy+checksums, missing image blocks build, checksum mismatch, label-image leakage,
traversal, absolute paths, schema completeness ×2, byte-identical builds,
failed-build byte/mtime preservation) и P1 (equality, substring отдельно, false
fuzzy rejected+recorded, valid fuzzy accepted, generic-only rejected, match
evidence serialized, missing-after-rejected, deterministic scoring, FP single
source, template preservation, stable ids). Только synthetic fixtures.

## Quality gates (все exit 0)

ruff check · ruff format --check · mypy (46 файлов) · pytest 123 ·
validate_dataset_foundation READY · verify_corpus_ingestion PASS ·
validate-curated VALID (460/460 изображений, checksums, схемы, FK, leakage,
traversal, absolute paths).

## Созданные/изменённые файлы

Изменены: `src/dalel/curation/{schemas,builder,validation,reports,checksums}.py`,
`src/dalel/pillars/document_integrity/{config,section_matcher,document_completeness,
pipeline,reports}.py`, `tests/unit/{test_curation,test_p1}.py`,
`docs/DATASET_V1_AND_P1_REPORT.md`. Созданы: `docs/DATASET_V1_IDEMPOTENCY_AUDIT.json`,
этот отчёт. Пересобраны production CLI: `data/curated/v1/**` (474 файла),
`data/results/p1/v1/**` (+`section_matches.jsonl`), `data/annotations/p1_review_template.jsonl`.

## Remaining limitations

1. 24/34 taxonomy-правил без kk-алиасов (coverage, не schema-нарушение).
2. 87 info duplicate_heading остаются шумными до экспертной калибровки.
3. Matcher допускает переиспользование одного заголовка несколькими правилами
   (фактических повторов 0).
4. Sintez portal-vs-local период недетектируем локально (без portal-адаптера).
5. Weak labels — один проект/тип; финальный split невозможен (4 проекта).
6. `.gitignore` не покрывает `data/curated`/`data/results` (файл вне разрешённых
   путей записи).

## Статус

**READY FOR INDEPENDENT DATASET V1 AND P1 RE-VERIFICATION**

Статусы VERIFIED/ACCEPTED присваивает только независимый верификатор.
