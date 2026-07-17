# DÁLEL Eco — Phase 0: Local Document Ingestion

Evidence-first мультимодальная система предварительной проверки экологической документации.
Эта фаза реализует **только** локальный ingestion уже проверенного датасета: чтение
canonical manifest, валидацию исходных документов, извлечение структурированного
содержимого PDF/DOCX и сохранение provenance.

Phase 0 **не** включает: frontend, FastAPI, БД, LLM-агентов, embeddings, RAG,
risk scoring, knowledge graph, web scraping и обучение моделей.

## Назначение

- Прочитать immutable manifest `data/manifests/projects.jsonl` (источник истины после
  dataset pre-flight audit) как **allowlist** документов.
- Проверить SHA-256 каждого документа до и после обработки — `data/raw/` неизменяем.
- Извлечь: page-level текст, секции (заголовки), таблицы, изображения, page dimensions,
  bounding boxes (когда парсер реально их даёт) и полный provenance.
- Разделить выходы model inputs и label sources физически разными директориями —
  защита от leakage.

## Демо-сайт в Docker (одна команда)

Полный демо-стек (read-only FastAPI + Next.js frontend) поднимается одной
командой из корня репозитория. Нужен установленный и запущенный
[Docker Desktop](https://www.docker.com/products/docker-desktop/):

```bash
docker compose up --build
```

- Frontend: http://localhost:3000 (`/analyze` — два раздельных режима:
  неизменяемая демонстрация Bayterek и фактический анализ нового проекта)
- API: http://localhost:8000 (health: `/api/health`, docs: `/api/docs`)

Управление стеком:

```bash
docker compose down        # остановить и удалить контейнеры
docker compose logs -f     # следить за логами обоих сервисов
docker compose ps          # статус и health сервисов
docker compose up --build  # пересборка после изменения кода
```

Данные: нужны локальные каталоги `data/curated/`, `data/results/` и
`data/annotations/` с принятыми артефактами. Они монтируются в контейнер
API **только для чтения** и никогда не копируются в образ (private
PDF/DOCX из `docs/` и `data/raw/` в образы не попадают —
см. `.dockerignore`). `data/annotations` нужен Meta replay-валидации: без
него интегральная оценка (META) недоступна.

Если порт 3000 или 8000 занят, Compose не стартует. Порты фиксированы
(фронтенд собран под `http://localhost:8000`) — найдите и остановите
занимающий процесс:

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Режимы `/analyze` строго разделены. «Демонстрация Bayterek» — неизменяемый
replay: она ничего не загружает и воспроизводит только принятые артефакты
подготовленного проекта. «Анализ нового проекта» принимает реальные байты
файлов в изолированное временное задание (случайный идентификатор + токен
доступа в заголовке `X-Dalel-Job-Token`), выполняет фактические P0/P0.5 и
принятые P1–P4/Meta на этом пакете и честно помечает недоступные проверки —
никогда не подставляя результаты Bayterek. Временные файлы живут только в
`DALEL_LIVE_JOB_DIR` (tmpfs контейнера) и удаляются по TTL или отмене.
Подробности: `docs/DEMO_WEBSITE.md`.

## Setup (uv)

```bash
# однократно: установить uv (https://docs.astral.sh/uv/)
brew install uv

# из корня репозитория: создать .venv на Python 3.12 и поставить зависимости
uv sync --dev
```

### Первая загрузка моделей Docling

При **первом** запуске `dalel ingest` Docling скачивает модели layout-анализа и
TableFormer (~500 МБ) с HuggingFace в `~/.cache`, а EasyOCR — модели распознавания
(~100 МБ, языки ru+en) в `~/.EasyOCR`. Это происходит один раз; unit-тесты
(`uv run pytest`) моделей **не** загружают и сети не требуют. CLI печатает
предупреждение перед первым использованием Docling.

## Команды

```bash
# 1. Валидация манифеста (без Docling, без моделей)
uv run dalel validate-manifest --manifest data/manifests/projects.jsonl

# 2. Обзор датасета: проекты, документы, роли, форматы, OCR-кандидаты
uv run dalel inspect --manifest data/manifests/projects.jsonl

# 3. Ingest одного проекта
uv run dalel ingest --manifest data/manifests/projects.jsonl \
  --project-id project_001_bereke --ocr auto

# 4. Ingest одного документа (повторно — с --force)
uv run dalel ingest --manifest data/manifests/projects.jsonl \
  --document-id project_001_bereke__ndv__001 --ocr auto --force

# 5. Технический parsing label sources (только для будущих labels)
uv run dalel ingest --manifest data/manifests/projects.jsonl --include-label-sources
```

## OCR modes

| Режим | Поведение |
|---|---|
| `--ocr auto` (default) | Сначала оценивается доля страниц с usable embedded text; OCR запускается только для страниц без текста. Цифровые страницы повторно не OCR-ятся. |
| `--ocr always` | Полный OCR всех страниц (force full page OCR). |
| `--ocr never` | OCR отключён; сканированные страницы получают warning и статус `partial`. |

OCR-движок — EasyOCR (через Docling), языки `ru`+`en`. Если движок недоступен,
pipeline не падает: используется PyMuPDF fallback, документ получает статус
`partial` и warning `ocr_engine_unavailable`. Отчёт фиксирует движок, версию,
OCR-страницы и elapsed time. Утверждение «OCR выполнен» появляется только если
движок реально запускался.

Примечание: EasyOCR не поддерживает казахский язык; для kk-документов OCR идёт
в режиме ru+en с warning (актуально только для label sources).

## Model inputs vs label sources (leakage boundary)

По умолчанию обрабатываются **только** документы с
`role == "model_input"`, `use_as_model_feature == true`, `label_timing == "pre_review"`.

- Hearing protocols, motivated refusal и прочие post-review документы **не** обрабатываются
  без явного флага `--include-label-sources` и даже с ним пишутся в отдельное дерево.
- RAR-архив всегда регистрируется как skipped auxiliary archive и никогда не распаковывается.
- Выход label sources никогда не смешивается с model inputs:

```text
data/processed/model_inputs/{project_id}/{document_id}/   # признаки для будущих моделей
data/processed/label_sources/{project_id}/{document_id}/  # только для будущего формирования labels
```

## Структура выхода

```text
data/processed/model_inputs/{project_id}/{document_id}/
├── document.json          # сводка документа: parser, режим PDF, OCR metadata, статус
├── pages.jsonl            # page-level текст + размеры страниц + provenance
├── sections.jsonl         # секции по заголовкам
├── tables.jsonl           # таблицы (grid ячеек, bbox если есть)
├── images.jsonl           # метаданные изображений
├── images/                # PNG-файлы изображений
└── ingestion_report.json  # parser attempts, fallback, hashes, cache key, ошибки

data/processed/model_inputs/{project_id}/project.json      # сводка по проекту
```

Статусы: `success`, `partial`, `failed`, `skipped`, `skipped_cached`.

## Cache / идемпотентность

Cache key = SHA-256 от (source SHA-256, имена и версии парсеров, OCR mode,
ingestion schema version). Повторный запуск с тем же ключом даёт
`skipped_cached` и не переписывает результаты. `--force` переобрабатывает.
Запись атомарна: сначала temporary directory рядом с целевой, затем rename —
частично записанный output никогда не выглядит успешным.

## Data safety

- `data/raw/` — immutable: никакие PDF/DOCX/RAR не изменяются, не переименовываются
  и не перемещаются; annotations в raw не добавляются.
- SHA-256 исходника проверяется до и после parsing; изменение хеша — ошибка
  данного документа (batch продолжается).
- Ошибка одного документа не останавливает batch.
- Label sources никогда не используются как model features.

## Как обработать только один документ

```bash
uv run dalel ingest --manifest data/manifests/projects.jsonl \
  --document-id project_001_bereke__nontechnical_summary__001 --ocr auto
```

`--document-id` берётся из манифеста (`document_id`), список — через `dalel inspect`.

## Как не допустить leakage

1. Не запускайте ingestion по `data/raw` напрямую — только через manifest.
2. Не переносите файлы из `data/processed/label_sources/` в model inputs.
3. Не используйте `--include-label-sources` при построении признаков.
4. Не выводите поля `hearing_protocol` / `motivated_refusal` в будущие фичи.
5. Split любых будущих моделей — только по `project_id`.

## Тесты и quality gates

```bash
uv run pytest                  # unit-тесты: без сети, без загрузки моделей
uv run pytest -m integration   # интеграционные: реальный Docling/OCR (медленно)
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python3 scripts/validate_dataset_foundation.py   # должен остаться READY
```

## Ограничения Phase 0

- RAR не распаковывается (protocol-PDF уже извлечены и учтены манифестом отдельно).
- DOCX не имеет page-разметки: page_number = null с warning, provenance ведётся
  по параграфам/таблицам.
- bbox сохраняются только когда парсер реально их даёт; координаты не выдумываются.
- Confidence сохраняется только parser-provided (Docling confidence report);
  фиктивных значений нет — иначе `null`.
- EasyOCR без поддержки казахского; kk label sources получают warning.
- Классификация изображений не включена (поле `classification` = null).

## Troubleshooting (macOS)

| Проблема | Решение |
|---|---|
| `uv: command not found` | `brew install uv`, перезапустить shell |
| Медленная первая конвертация | Идёт загрузка моделей Docling/EasyOCR — см. выше; повторные запуски быстрые |
| `ocr_engine_unavailable` в warnings | EasyOCR не установился/не импортируется; `uv sync --dev` заново; проверьте `uv run python -c "import easyocr"` |
| Ошибки сборки PyMuPDF | Обновите Xcode CLT: `xcode-select --install` (обычно ставится wheel, сборка не нужна) |
| MPS/torch предупреждения | Безопасны; Docling сам выбирает accelerator |
| Права на `data/processed` | Директория создаётся автоматически; не запускайте из чужого CWD — пути в манифесте относительны корня репозитория |

## Что дальше

См. `NEXT_STEPS.md`. Phase 1 (multi-pillar анализ) не начинается без явного решения.
