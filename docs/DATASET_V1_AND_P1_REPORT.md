# Dataset v1 (Phase 0.5) + P1 Document Integrity (Phase 1A) — Report

Дата: 2026-07-14 (revision 2 — после устранения blockers независимой верификации;
детали исправлений: `docs/DATASET_V1_AND_P1_FIX_REPORT.md`).
Входной корпус: Phase 0 processed (независимо верифицирован: VERIFIED — READY FOR DATASET V1).
Не начаты: P2–P6, LLM/RAG, AlemLLM, XGBoost/SHAP, CML, frontend, FastAPI, PostgreSQL, LangGraph.
Git commit/push не выполнялись. `data/raw`, `data/processed`, манифесты, source_metadata,
исходные annotations не изменялись (запись только в разрешённые пути).

## 1. Curated dataset — архитектура

Пакет `src/dalel/curation/` (builder, validation, schemas, provenance, normalization,
splits, checksums, reports) + CLI `dalel curate` / `dalel validate-curated`.

- `data/processed` читается строго read-only; выход — `data/curated/v1/` (475 файлов:
  15 корневых, включая `input_manifest.jsonl`, + 460 изображений). **Датасет
  самодостаточен**: все image-байты скопированы внутрь
  (`images/<project>/<document>/…`) с `image_sha256`/`image_size_bytes` в записях;
  `checksums.jsonl` покрывает все 474 файла.
- **Полная атомарность**: build целиком в sibling tmp-директории → полная
  валидация tmp (`validate-curated` + повторная проверка checksums) → atomic
  swap. Любая ошибка (включая раннюю валидацию) не меняет ни байта
  существующего датасета; ошибки — в stderr. Повторный запуск без `--force`
  отклоняется до каких-либо записей.
- **Byte-idempotency и fingerprint semantics**: timestamps исключены из
  versioned-артефактов; идентичность сборки — `input_fingerprint` алгоритма
  `dalel-input-inventory/v2`: явный inventory **584 upstream-файлов**, которые
  builder реально читает (без directory-glob; downstream — data/curated,
  data/results, p1_review_template — исключены по построению; полный список —
  `input_manifest.jsonl` внутри датасета). Два независимых temporary build дали
  475/475 побайтно идентичных файла, fingerprint `772694f4…` одинаков до и
  **после запуска P1**; production совпадает с temp-builds
  (`docs/DATASET_V1_IDEMPOTENCY_AUDIT.json`, result IDENTICAL).
- **Standalone schema contract**: `schema.json` — самодостаточные JSON Schema
  Draft 2020-12 контракты 11 типов записей (enums ролей/статусов/типов,
  SHA/path-patterns, посегментный запрет `..`, table-правило непустого
  содержимого, if/then-coupling материализации изображений);
  `validate-curated` исполняет распространяемый schema.json стандартным
  jsonschema-валидатором по всем записям (0 ошибок), поверх Pydantic-проверки.
  Детали: `docs/DATASET_V1_SCHEMA_AND_FINGERPRINT_FIX_REPORT.md`.
- **Слои физически разделены**: feature-слой (documents/pages/sections/tables/images)
  собирается ТОЛЬКО из `model_inputs`; label-слой — `weak_findings.jsonl` (5 находок AZM
  с маппингом путей → document_id, `expert_verified=false`, «weak», не gold);
  текст post-review документов никуда не копируется; label-source изображения
  не материализуются.
- Каждая запись feature-слоя — verbatim-копия processed-записи + `record_ref{file,line}`,
  валидированная через production Pydantic-модели; provenance не пересинтезируется
  (расхождение project/document/sha256 блокирует build).
- `schema.json` — **полные machine-readable JSON Schemas** (`model_json_schema()`)
  для всех 10 типов записей (properties/required/nullable/`$defs`); те же модели
  используются `validate-curated` для реальной валидации записей.

## 2. Фактические counts (build → validate-curated → совпали)

| Метрика | Значение |
|---|---:|
| Проекты / группы | 4 / 4 |
| Документы (model inputs) | 19 |
| Pages / Sections | 1044 / 1912 |
| Tables (валидные) | 623 |
| Image records | 460 |
| **Физические curated images (внутри датасета)** | **460** (unique paths 460, checksum mismatches 0, traversal 0) |
| Weak findings | 5 |
| OCR pages | 82 |
| Skipped empty table items (из ingestion) | 54 |

## 3. Mixed-schema normalization (17 × 1.0.0, 2 × 1.1.0)

По требованию реверификатора legacy-counters НЕ берутся из Pydantic-defaults:
для 1.0.0 выводятся явно (`serialized = факт. записи tables.jsonl`, `detected = serialized`,
`skipped = 0`) с warning `legacy_report_counters_inferred`; native-counters 1.1.0
сохраняются как есть (тест подтверждает, что они не обнуляются). Каждая curated-запись
документа хранит source schema version, normalization version 1.0.0, applied
normalizations и warnings. Processed reports не переписывались.

## 4. Table validity contract (повторно применён builder-ом)

Все **632** serialized-записи обоих processed-деревьев (623 mi + 9 ls) проверены:
**632 valid, 0 invalid**. Любая invalid таблица останавливает build с exit 1 и
попадает в `build_report.json` (протестировано для обоих деревьев). Дополнительно:
уникальность table_id, provenance, page/bbox или null, прямоугольность grid,
консистентность dimensions.

## 5. Leakage checks

`validate-curated` (exit 0) подтверждает: в feature-слое только `role=model_input`;
label-source id отсутствуют среди documents/pages/sections/tables/images; weak findings
ссылаются на label-источники только по id/path/page с короткой цитатой; FK целостны;
orphan-записей и `.tmp__` нет; счётчики совпадают со statistics; checksums сходятся.

## 6. Ограничения датасета

4 проекта; регион/отрасль полностью конфаундятся с проектом; weak labels — один проект
(AZM), один тип документа; kk OCR не поддержан (EasyOCR); 16 страниц корпуса без
пригодного текста; протокольные таблицы Bayterek OCR-повреждены (не labels без ручной
проверки); **финальный train/test split не создан** — только proposal
(leave-one-project-out) с явным заявлением: статистически надёжное обучение risk-модели
пока невозможно; минимальная единица split — проект.

## 7. P1 — архитектура

Пакет `src/dalel/pillars/document_integrity/` (config, schemas, taxonomy, normalization,
section_matcher, package_completeness, document_completeness, quality, scoring, pipeline,
reports) + CLI `dalel run-p1 [--project-id] [--document-id]`. Детерминированный baseline:
**LLM и embeddings не используются** (embeddings допустимы в будущем только как optional
экспериментальный режим). Matching: NFKC → casefold → ё→е → срез нумерации → пунктуация →
пробелы; RU/KK алиасы; exact → token overlap (Jaccard ≥ 0.6 / подмножество токенов) →
fuzzy (SequenceMatcher ≥ 0.82).

## 8. Taxonomy

`TAXONOMY_VERSION 1.0.0`: 34 правила «**expected structural section**» (формулировка
намеренно НЕ «legal requirement»; юридическая обязательность не утверждается без
нормативной ссылки) для 9 типов: ndv(7), pek(5), puo(4), ovvos(4), roos(5),
action_plan(2), nontechnical_summary(2), explanatory_note(2), working_project_note(3);
каждое правило: rule_id, canonical_section, aliases_ru/kk, required|recommended,
severity, rationale, limitations. Плюс 2 package-профиля (permit_package,
construction_eia). Полный snapshot — в `config_snapshot.json`.

## 9. Findings (реальный корпус)

Всего **142** (medium 21, low 34, info 87); 0 high — все ожидаемые документы пакетов
на месте. +1 low против прежней ревизии: устранение ложного fuzzy-совпадения
(«шумовое воздействие» ↛ «Тепловое воздействие») восстановило подавленную находку
ROOS-S05 для Bayterek ROOS:

| Тип | Кол-во | Комментарий |
|---|---:|---|
| duplicate_heading | 87 | info; повторы ≥3 — в основном колонтитулы/оглавления больших документов |
| missing_expected_section | 38 | 19 required (medium) + 19 recommended (low); в т.ч. восстановленная ROOS-S05 |
| empty_page | 8 | страницы-карты/схемы без текста (известные из Phase 0) |
| missing_appendix_reference | 5 | ссылки на приложения без заголовков приложений — кандидаты |
| high_ocr_dependency | 2 | bereke action_plan, bayterek roos |
| low_text_coverage | 1 | bereke action_plan (CamScanner) |
| suspicious_document_length | 1 | bereke action_plan (2 стр. — скан плана) |
| date_range_inconsistency | 0 | см. ниже |
| missing_document / metadata_inconsistency / structural_anomaly | 0 | пакеты полны; метаданные согласованы; секции есть везде |

Finding-id теперь content-stable (hash от project|document|type|rule|title) —
устойчивы между запусками и безопасны для merge review-шаблона.

**Date-range пример из ТЗ (Sintez Ural 2025–2034 vs 2026–2035):** локально ВСЕ документы
Sintez согласованно указывают 2026–2035 — расхождение существует только против
*портальной карточки*, отсутствующей в локальном корпусе, и локальным детерминированным
baseline честно не детектируется (зафиксировано в limitations правила). Проверка
сравнивает доминирующие периоды между документами пакета (внутридокументные исторические
периоды не флагуются): Bereke 2025–2034 ×5 согласован, AZM/Sintez 2026–2035 согласованы →
0 находок, что корректно для локальных данных.

## 10. Score distribution (`document_integrity_priority_score`, 0–100)

Приоритет ручной проверки структуры, НЕ вероятность нарушения. Детерминированный,
монотонный (тестируется), версионированный (`SCORING_CONFIG_VERSION 1.0.0`), каждый
вклад объясним (contributions в document_scores.jsonl), confidence=null у всех findings,
отсутствие данных само по себе очков не добавляет.

- Диапазон: 10–82, среднее 31.6.
- Топ: sintez working_project_note 82 (159 стр., много повторов заголовков + пропуски
  recommended-секций), bayterek roos 70 (после восстановления ROOS-S05), bereke ndv 56,
  azm ndv 49.
- Проектные скоры агрегируются из документных + package-findings.

## 11. Manual review и false-positive кандидаты

`data/annotations/p1_review_template.jsonl`: 142 строки (finding_id + пустые
expert_decision/corrected_severity/expert_comment/reviewed_at/reviewer_id) — экспертные
решения НЕ заполнялись автоматически; при повторном запуске человеческие решения
сохраняются по стабильным finding_id, исчезнувшие findings уходят в stale-audit
(`review_template_stale.jsonl`), не теряясь. **111 findings** — кандидаты на false
positive; число берётся из единственного источника
(`is_false_positive_review_candidate`): metrics-поле = список id = report.md = этот
отчёт. Ablation (4 метода раздельно): из 75 правил сопоставлено 37 —
**exact_equality 16, normalized_substring 17, token_overlap 4, fuzzy 0**; отклонено
2 fuzzy-кандидата без discriminative evidence (оба «Тепловое воздействие», ratio 0.821).
Evidence каждого accepted match — `data/results/p1/v1/section_matches.jsonl`
(37 записей: rule, alias, observed/normalized heading, page, method, score,
discriminative_tokens, limitations).

## 12. Тесты и quality gates

Тестов: **123 passed** (3 integration deselected): curated (mixed-schema, strict table
gate обоих деревьев, физическое копирование изображений с checksums, отсутствующее/
повреждённое изображение, label-image leakage, path traversal, absolute paths,
полнота machine-readable схем, byte-идентичность двух build, сохранение байт и mtime
существующего датасета при failed build, provenance-tamper, checksums, FK, malformed
records, legacy counters) и P1 (normalization, RU/KK алиасы, equality/substring
раздельно, false-fuzzy regression, positive fuzzy, generic-only отклонение, match
evidence, missing-после-rejected, required/recommended, качество страниц, date ranges,
package completeness, детерминизм и монотонность скоринга, null confidence, единый
FP-источник, сохранение экспертных решений шаблона, стабильные id, CLI smoke).
Только synthetic fixtures.

Gates (все exit 0): ruff check; ruff format --check; mypy (46 файлов); pytest;
validate_dataset_foundation (READY); verify_corpus_ingestion (PASS);
validate-curated (VALID).

## 13. Созданные/изменённые файлы

Создано: `src/dalel/curation/*` (9), `src/dalel/pillars/document_integrity/*` (12),
`tests/unit/test_curation.py`, `tests/unit/test_p1.py`, `tests/fixtures/curation_builders.py`,
`data/curated/v1/*` (475 файлов: 15 корневых + 460 изображений),
`data/results/p1/v1/*` (7, включая section_matches.jsonl),
`data/annotations/p1_review_template.jsonl`, `docs/DATASET_V1_IDEMPOTENCY_AUDIT.json`,
`docs/DATASET_V1_AND_P1_FIX_REPORT.md`, этот отчёт.
Изменено: `src/dalel/cli.py` (+curate, +validate-curated, +run-p1), `pyproject.toml`
(RUF001-003 ignore для русских строк), `scripts/validate_dataset_foundation.py`
(расширение: производные пути data/curated, data/results и review-шаблон вне области
аудированного инвентаря; проверки raw/manifests/annotations не ослаблены).

## 14. Известные ограничения

1. Sintez portal-vs-local period discrepancy недетектируем локально (нужен будущий
   portal-metadata источник).
2. duplicate_heading шумный (87 info) — порог/колонтитул-фильтр — кандидат на настройку
   после экспертного review.
3. Приложения, свёрстанные в тот же PDF без заголовков, дают missing_appendix_reference
   кандидатов (5 шт.).
4. Таксономия построена по практике корпуса из 4 проектов, без нормативных ссылок —
   намеренно «expected structural section».
5. `data/curated/` и `data/results/` не покрыты `.gitignore` (файл не входит в список
   разрешённых для записи путей этой задачи) — рекомендуется добавить отдельно.
6. Метрики P1 — coverage/распределения; accuracy на 4 проектах не заявляется.

## 15. Следующая рекомендуемая фаза

Экспертный review 142 findings через `p1_review_template.jsonl` (в первую очередь 111
FP-кандидатов) → калибровка таксономии/порогов (v1.1) → после этого решение о P2
Regulatory Compliance (требует Atomic Requirement Registry). Самостоятельно не начинаю.

## Статус

**READY FOR INDEPENDENT DATASET V1 AND P1 RE-VERIFICATION**

Статусы VERIFIED/ACCEPTED присваивает только независимый верификатор.
