# NEXT STEPS после Phase 0

Phase 0 (local document ingestion) реализована. Ниже — рекомендованный порядок
дальнейших шагов. **Phase 1 не начинается без явного решения.**

## Сразу после Phase 0

1. **Обработать оставшиеся проекты** (после просмотра smoke-отчёта):
   ```bash
   uv run dalel ingest --manifest data/manifests/projects.jsonl --project-id project_002_azm --ocr auto
   uv run dalel ingest --manifest data/manifests/projects.jsonl --project-id project_003_bayterek --ocr auto
   uv run dalel ingest --manifest data/manifests/projects.jsonl --project-id project_004_sintez_ural --ocr auto
   ```
2. **Просмотреть notebook** `notebooks/01_ingestion_audit.ipynb`: coverage,
   OCR usage, warnings, документы с плохим extraction.
3. **Ручная проверка качества русского OCR** на `project_001_bereke__action_plan__001`
   (EasyOCR ru+en): сравнить распознанный текст с оригиналом.
4. **Label sources (по необходимости, для будущих labels)**:
   `--include-label-sources` пишет их в отдельное дерево `data/processed/label_sources/`.
   Казахский протокол Bayterek: EasyOCR не поддерживает kk — ожидаем warning
   `ocr_language_unsupported`; рассмотреть Tesseract (`kaz` traineddata) или Apple Vision
   (ocrmac) для казахских сканов.

## Технический долг Phase 0 (кандидаты)

- Оценить качество таблиц Docling TableFormer на реальных НДВ-таблицах
  (большие многостраничные таблицы — известный слабый случай; в blueprint
  предусмотрен Table Transformer fallback).
- Расширить `sections.jsonl` иерархией заголовков (сейчас плоский список).
- Добавить language detection на уровне страниц (blueprint 5.6 "смешанные языки").
- Рассмотреть continuation detector для таблиц, разбитых на страницы.
- Bench: время обработки больших PDF (НДВ 174 стр.) и, при необходимости,
  батчинг/параллелизм по документам.

## Phase 1 (НЕ НАЧИНАТЬ без решения)

По blueprint: P1 Document Integrity Pillar — rule-based checklist полноты пакета,
section classifier, completeness scorer. Вход — canonical evidence layer,
созданный этой фазой (`data/processed/model_inputs/`).

## Напоминания о data safety

- `data/raw/` immutable; canonical manifest не пересоздавать.
- Split будущих моделей — только по `project_id`.
- Post-review документы и weak findings никогда не попадают в model features.
