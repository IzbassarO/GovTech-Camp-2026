---
title: "DÁLEL Eco"
subtitle: "Полный технический blueprint мультимодальной multi-pillar agentic системы доказательной экологической экспертизы"
author: "Проектный документ для GovTech Camp Kazakhstan 2026"
date: "13 июля 2026"
lang: ru-RU
toc: true
toc-depth: 3
numbersections: true
geometry: margin=20mm
fontsize: 10pt
mainfont: "DejaVu Sans"
monofont: "DejaVu Sans Mono"
colorlinks: true
linkcolor: "blue"
urlcolor: "blue"
header-includes:
  - |
    ```{=latex}
    \usepackage{longtable}
    \usepackage{booktabs}
    \usepackage{array}
    \usepackage{float}
    \usepackage{graphicx}
    \usepackage{xcolor}
    \setlength{\parskip}{0.35em}
    \setlength{\parindent}{0pt}
    ```
---

> **Статус документа:** архитектурный и исследовательский план. Документ предназначен одновременно для команды разработки, предметного эксперта, менторов и другой LLM, которой можно поручить реализацию отдельных модулей.
>
> **Ключевой принцип:** ни один AI-компонент не принимает окончательное юридическое или административное решение. Система формирует доказательства, оценивает приоритет проверки и передаёт решение экологическому эксперту.

# 1. Резюме проекта

## 1.1. Рекомендуемое название

**DÁLEL Eco**

Расшифровка бренда:

- **Dálel / Дәлел** - доказательство, основание;
- **Eco** - экологический контекст;
- основной слоган: **Evidence-first environmental intelligence**;
- русская формулировка: **Доказательная AI-проверка экологической документации**;
- казахская формулировка: **Экологиялық құжаттарды дәлелге негізделген AI-сараптау жүйесі**.

Почему это название сильнее EcoSarap:

1. Оно подчёркивает главный дифференциатор - каждый вывод связан с доказательством.
2. Оно не ограничивает продукт только "экспертизой документов": позже можно подключить мониторинг, карты, датчики и фотографии.
3. Название короткое, локальное и при этом пригодно для международного B2G/B2B-продукта.

Допустимые альтернативы бренда:

| Название | Сильная сторона | Ограничение |
|---|---|---|
| **DÁLEL Eco** | Доказательность, уникальность, локальная идентичность | Требуется одна строка объяснения значения слова |
| **TazaDálel** | Хорошо запоминается, "чистое доказательство" | Может восприниматься как антикоррупционный бренд |
| **EcoProof KZ** | Сразу понятно международной аудитории | Менее локально и менее уникально |
| **Qorgau AI** | "Защита", хорошо для госпродукта | Слишком широкое название |
| **Tabiǵat Review** | Прямо связано с природой | Менее технологичное звучание |

В этом документе используется название **DÁLEL Eco**.

## 1.2. Одно предложение о продукте

**DÁLEL Eco - мультимодальная multi-agent система поддержки экологической экспертизы, которая анализирует связанные PDF-документы, таблицы, карты, схемы, фотографии и внешний географический контекст, формирует отдельные pillar scores, проверяет устойчивость итогового risk scoring с помощью causal ML и показывает экологическому эксперту доказательства каждого вывода.**

## 1.3. Какая проблема решается

Экологическая документация может состоять из сотен страниц и нескольких связанных документов: проекта нормативов допустимых выбросов, программы производственного экологического контроля, программы управления отходами, плана природоохранных мероприятий, отчёта о возможных воздействиях, карт, генпланов, схем и приложений.

Эксперт должен вручную проверить:

- наличие обязательных разделов;
- согласованность реквизитов и периодов;
- перечень источников выбросов;
- перечень загрязняющих веществ;
- числовые итоги и единицы измерения;
- соответствие НДВ и ПЭК;
- обоснованность отходов в ПУО;
- наличие карт, координат и санитарно-защитных зон;
- выполнение нормативных требований;
- замечания общественности;
- достаточность доказательств.

Проблема не сводится к отсутствию электронной формы. Это задача понимания сложных документов, сопоставления сущностей, числовой валидации, анализа изображений и оценки неопределённости. Поэтому обычная автоматизация и поиск по ключевым словам недостаточны.

## 1.4. Цель

Создать работающий прототип, который:

1. принимает комплект экологических материалов;
2. автоматически извлекает структуру, текст, таблицы и изображения;
3. выполняет независимые проверки по нескольким pillars;
4. формирует приоритет проверки, но не решение о законности;
5. показывает страницу, таблицу, crop изображения и нормативное основание;
6. предоставляет интерфейс human-in-the-loop;
7. сохраняет решения эксперта как новые gold labels;
8. демонстрирует, что scoring не опирается на регион, логотип, имя предприятия или шаблон документа как на shortcuts.

## 1.5. Пользователи

### Основной B2G-пользователь

- государственный экологический эксперт;
- сотрудник территориального департамента экологии;
- аналитик Министерства экологии и природных ресурсов;
- специалист, рассматривающий материалы общественных слушаний или экологического разрешения.

### B2B-пользователь

- эколог предприятия;
- проектная организация, разрабатывающая НДВ, ПЭК, ПУО и ОВОС;
- независимый экологический консультант;
- оператор промышленного объекта;
- ESG и compliance-подразделение.

### Пользовательский сценарий

1. Проектировщик проверяет пакет до официальной подачи.
2. Государственный эксперт получает тот же пакет и видит структурированный pre-review.
3. Эксперт подтверждает или отклоняет findings.
4. Система не блокирует разрешение и не формирует штраф автоматически.

## 1.6. Ожидаемый score по рубрике GovTech Camp

Оценка ниже является целевой оценкой при качественной реализации, а не гарантированным результатом.

| Критерий | Максимум | Потенциал концепции | Реалистичная цель MVP | Что необходимо показать |
|---|---:|---:|---:|---|
| Понимание проблемы | 15 | 15 | 14-15 | Реальный пакет документов, конкретная ручная нагрузка |
| Ценность | 15 | 15 | 13-14 | Сокращение времени, меньше пропущенных противоречий |
| Работа с данными | 15 | 15 | 14-15 | НБД, нормативы, gold-разметка, dataset card, anti-leakage |
| AI/ML | 20 | 20 | 18-20 | Multi-pillar, VLM, entity resolution, calibrated scoring, CML |
| Explainability | 10 | 10 | 9-10 | Page-level evidence, SHAP, confidence, counterfactuals |
| Прототип | 15 | 14 | 12-14 | Docker Compose, end-to-end поток, сохранение решений |
| UX и демо | 5 | 5 | 5 | Side-by-side PDF/image evidence и кнопки эксперта |
| Документация | 5 | 5 | 5 | README, архитектура, ограничения, воспроизводимость |
| **Итого** | **100** | **99** | **90-97** | Зависит от глубины работающего прототипа |

**Честная оценка:**

- концептуальный потенциал: **96-99/100**;
- сильный, но ограниченный MVP: **92-95/100**;
- если команда попытается реализовать все pillars поверхностно: **84-89/100**.

Следовательно, стратегия должна быть не "сделать всё", а **полностью закрыть 3-4 pillars, показать каркас остальных и провести строгую оценку данных**.

## 1.7. Потенциал роста

### Горизонт 1: отборочный прототип

- НДВ + ПЭК + ПУО;
- русский язык с частичной поддержкой казахского;
- 20-30 требований;
- 3 типа cross-document противоречий;
- анализ 1-2 видов изображений;
- preliminary risk score;
- causal audit dashboard.

### Горизонт 2: 10-недельная программа

- расширение на ОВОС и экологические разрешения;
- двуязычный regulatory corpus;
- graph-based entity resolution;
- fine-tuning доменных extractor-моделей;
- active learning;
- интеграция с AlemLLM;
- geospatial context;
- экспертный benchmark.

### Горизонт 3: коммерческий оператор

- pre-submission SaaS для предприятий;
- кабинет государственного эксперта;
- API для НБД или ведомственной системы;
- постоянное обновление нормативов;
- мониторинг изменений документов;
- проверка отчётности ПЭК;
- сопоставление документов с данными автоматических датчиков;
- SLA на качество извлечения, полноту findings и время обработки.

### Горизонт 4: экспорт

Архитектура применима в других странах, если заменить:

- нормативный корпус;
- словарь экологических сущностей;
- локальные формы документов;
- источники пространственных и мониторинговых данных.

# 2. Почему это AI-проект, а не обычная автоматизация

Обычная система может проверить наличие файла и обязательного поля. DÁLEL Eco решает задачи, где структура и смысл заранее не фиксированы:

1. PDF может быть цифровым, сканированным или смешанным.
2. Один и тот же источник выбросов имеет разные названия в разных документах.
3. Таблица может продолжаться на нескольких страницах.
4. Нормативное требование может быть выполнено перефразированным текстом.
5. Генплан и таблица используют разные обозначения объектов.
6. Экологический риск зависит от контекста: отрасли, масштаба, расстояния до жилой зоны и полноты мониторинга.
7. Итоговый score должен быть калиброван, объясним и устойчив к confounding.

AI применяется там, где он оправдан:

- Document AI - понимание структуры страницы;
- NLP - классификация разделов и извлечение сущностей;
- retrieval и reranking - поиск нормативного основания;
- NLI/LLM - проверка, покрывает ли текст требование;
- VLM - анализ карт, схем и изображений;
- anomaly detection - поиск необычных числовых паттернов;
- graph reasoning - сопоставление сущностей между документами;
- supervised ML - risk scoring;
- causal ML - проверка устойчивости к измеренным confounders;
- human feedback - active learning.

AI **не применяется** для операций, где надёжнее код:

- сложение значений;
- преобразование единиц;
- проверка диапазонов;
- поиск точного идентификатора;
- контроль версий;
- проверка наличия страницы;
- применение формализованного правила.

# 3. Архитектурные принципы

## 3.1. Evidence-first

Каждый finding должен содержать:

- тип;
- severity;
- confidence;
- source document;
- page number;
- bounding box или координаты фрагмента;
- извлечённый текст/значение;
- нормативное основание;
- способ получения;
- ограничения.

**Нет доказательства - нет finding в основном интерфейсе.** Неподтверждённый вывод можно сохранить только как `candidate_finding`.

## 3.2. Отдельные модели для отдельных задач

Нельзя заставлять одну LLM:

- читать PDF;
- извлекать таблицы;
- считать итог;
- оценивать риск;
- выдавать юридический вывод.

Каждый компонент получает узкий контракт и измеряемую метрику.

## 3.3. Agentic orchestration, а не agentic хаос

Агент имеет право:

- выбирать инструмент;
- запрашивать дополнительный фрагмент;
- сравнивать гипотезы;
- повторять извлечение другим parser;
- формировать структурированный вывод.

Агент не имеет права:

- менять данные без журнала;
- принимать финальное решение;
- формировать score без модели;
- ссылаться на несуществующую норму;
- скрывать недостаточность данных.

## 3.4. Model-agnostic LLM layer

Сегодня система может использовать одну или несколько доступных LLM/VLM. Позже текстовые агенты переключаются на AlemLLM через provider adapter. Бизнес-логика, schemas и evaluation не должны зависеть от названия модели.

## 3.5. Reproducibility

Каждый analysis run сохраняет:

- версию данных;
- хэш файла;
- версию parser;
- версию prompt;
- название модели;
- temperature;
- seed, если поддерживается;
- версию risk model;
- timestamp;
- итоговые артефакты.

## 3.6. Human-in-the-loop

Статусы findings:

- `candidate`;
- `verified_by_critic`;
- `confirmed_by_expert`;
- `rejected_by_expert`;
- `clarification_requested`;
- `resolved`.

# 4. End-to-end архитектура

![Общая архитектура DÁLEL Eco](assets/architecture.png)

## 4.1. Основной поток

1. Пользователь создаёт проект.
2. Загружает связанные документы и изображения.
3. Ingestion layer создаёт page-level representation.
4. Document Router определяет тип каждого файла.
5. Pillar agents выполняются параллельно.
6. Evidence Critic проверяет findings.
7. Meta-model формирует приоритет проверки.
8. Causal Robustness layer показывает устойчивость модели.
9. Explanation Composer создаёт карточки.
10. Эксперт принимает решение.
11. Решение попадает в feedback dataset.

## 4.2. Рекомендуемая сервисная схема

```text
frontend-nextjs
    |
api-gateway-fastapi
    |
    +-- project-service
    +-- ingestion-worker
    +-- agent-orchestrator
    +-- scoring-service
    +-- causal-audit-service
    +-- report-service
    |
postgres + pgvector
object-storage (MinIO/S3)
redis queue
mlflow
```

Для MVP допускается объединить backend-сервисы в один FastAPI application и использовать FastAPI Background Tasks или RQ вместо полноценной распределённой очереди.

# 5. P0 - Ingestion, routing и canonical evidence layer

P0 не является risk pillar, но определяет качество всей системы.

## 5.1. Входы

- PDF;
- DOCX;
- XLSX/CSV;
- PNG/JPEG/TIFF;
- координаты;
- ZIP-пакет;
- URL публичной карточки НБД - только как metadata, если загрузка разрешена;
- optional: GeoJSON/KML.

## 5.2. Задачи

1. Проверка MIME и размера.
2. Вычисление SHA-256.
3. Определение цифрового/сканированного PDF.
4. Разбиение на страницы.
5. Извлечение текста, таблиц, изображений и layout blocks.
6. OCR только для нужных страниц.
7. Классификация типа документа.
8. Создание provenance links.
9. Сохранение исходного файла без изменений.

## 5.3. Технологии

- **Docling** как основной parser: layout, reading order, table structure, image classification, OCR и единый DoclingDocument [R08];
- PyMuPDF для страниц, координат и рендера;
- Table Transformer как fallback для таблиц;
- OCR: PaddleOCR или Tesseract как fallback;
- MinIO/S3 для файлов;
- PostgreSQL для metadata;
- pgvector для embeddings.

## 5.4. Canonical page schema

```json
{
  "project_id": "P-001",
  "document_id": "DOC-003",
  "page_number": 47,
  "page_width": 595,
  "page_height": 842,
  "document_type": "NDV",
  "blocks": [
    {
      "block_id": "B-47-12",
      "type": "table",
      "bbox": [72, 180, 520, 640],
      "text": "...",
      "ocr_confidence": 0.96
    }
  ],
  "images": [],
  "tables": [],
  "parser_version": "docling-x.y",
  "source_sha256": "..."
}
```

## 5.5. Метрики

- процент успешно обработанных страниц;
- OCR character error rate на gold subset;
- page classification accuracy;
- table detection AP/F1;
- доля entities с корректной page provenance;
- extraction latency;
- доля страниц, отправленных на fallback parser.

## 5.6. Failure modes

| Ошибка | Детектор | Действие |
|---|---|---|
| Скан низкого качества | OCR confidence | повторный рендер 300 DPI, другой OCR |
| Таблица разбита на страницы | continuation detector | объединить по заголовкам и колонкам |
| Неверный reading order | layout consistency | использовать page image + VLM verification |
| PDF защищён | parser error | сообщить пользователю, не обходить защиту |
| Смешанные языки | language detector | chunk-level language metadata |

# 6. P1 - Document Integrity Pillar

## 6.1. Цель

Оценить полноту и техническую пригодность пакета к экспертной проверке.

## 6.2. Что проверяется

- присутствуют ли все заявленные документы;
- совпадает ли тип файла с содержанием;
- есть ли обязательные разделы;
- отсутствуют ли страницы;
- читаются ли таблицы;
- есть ли пустые приложения;
- есть ли подписи, даты, версии;
- согласованы ли название предприятия, БИН и период;
- есть ли карты и приложения, на которые ссылается текст.

## 6.3. Модели

### MVP

- rule-based package checklist;
- multilingual section classifier;
- logistic regression completeness scorer;
- OCR quality model.

### Продвинутый путь

- fine-tuned LayoutLMv3/DiT/Docling layout model;
- sequence model для порядка разделов;
- document graph для ссылок "см. приложение 13".

## 6.4. Признаки

```text
missing_required_documents
missing_required_sections
empty_page_ratio
ocr_low_confidence_ratio
unresolved_internal_references
missing_signature_or_date
metadata_mismatch_count
duplicate_page_ratio
invalid_page_order_probability
```

## 6.5. Пример finding

```json
{
  "pillar": "P1_DOCUMENT_INTEGRITY",
  "finding_type": "unresolved_appendix_reference",
  "severity": "medium",
  "confidence": 0.94,
  "message": "В тексте НДВ имеется ссылка на Приложение 13, но соответствующее приложение не найдено в загруженном пакете.",
  "evidence": [
    {"document": "NDV.pdf", "page": 126, "bbox": [80, 300, 515, 350]}
  ],
  "recommended_action": "Проверить комплектность приложений."
}
```

## 6.6. Score

```text
P1_score = weighted_sum(
  missing_components,
  extraction_failures,
  metadata_conflicts,
  unresolved_references
)
```

Score должен отражать **риск неполноты**, а не экологический ущерб.

## 6.7. Метрики

- section detection macro-F1;
- missing section recall;
- false missing-section rate;
- exact match реквизитов;
- reviewer confirmation rate.

## 6.8. MVP scope

- НДВ, ПЭК, ПУО;
- 10 обязательных разделов;
- 5 типов package integrity findings;
- один обученный section classifier или zero/few-shot baseline с gold test set.

# 7. P2 - Regulatory Compliance Pillar

## 7.1. Цель

Определить, присутствует ли в документах достаточное доказательство выполнения конкретного нормативного требования.

## 7.2. Почему обычный RAG недостаточен

Обычный RAG отвечает на вопрос пользователя. Здесь требуется систематическая проверка набора требований:

```text
Requirement -> expected evidence -> retrieval -> entailment -> critic -> finding
```

## 7.3. Atomic Requirement Registry

Каждая норма преобразуется в атомарную карточку:

```yaml
requirement_id: PEK-MONITORING-001
source_document: "Правила разработки программы ПЭК"
source_section: "пункт ..."
language: ru
requirement_text: "Программа должна включать перечень контролируемых источников..."
applies_to:
  object_category: [I, II]
  document_type: [PEK]
expected_evidence:
  - source_id
  - pollutant
  - monitoring_frequency
  - measurement_method
severity_if_missing: high
```

## 7.4. Пайплайн

1. Applicability Agent определяет применимость требования.
2. Retriever получает top-k chunks.
3. Reranker сортирует доказательства.
4. NLI model выдаёт `entailed / partial / contradiction / unknown`.
5. LLM объясняет результат в JSON.
6. Critic проверяет ссылку и цитату.

## 7.5. Модели

### Retrieval

- multilingual dense embeddings;
- BM25 как обязательный baseline;
- hybrid retrieval;
- cross-encoder reranker.

### Entailment

- multilingual NLI model;
- текущая сильная LLM со structured output;
- в дальнейшем AlemLLM после доменной оценки.

### Альтернатива без большой LLM

- sentence-transformer retrieval;
- XLM-R NLI classifier;
- templates для explanation.

## 7.6. Пример

**Требование:** программа ПЭК должна содержать мониторинг эмиссий.

**Найденный фрагмент:** страница 38, таблица с источниками 0001-0012.

**Вывод:** `partially_covered`, поскольку частота контроля указана только для 8 из 12 источников.

```json
{
  "requirement_id": "PEK-MONITORING-001",
  "status": "partially_covered",
  "confidence": 0.88,
  "evidence": [
    {"document": "PEK.pdf", "page": 38, "table_id": "T-38-2"}
  ],
  "missing_elements": ["frequency for sources 0009-0012"],
  "legal_disclaimer": "Требуется подтверждение экологическим экспертом."
}
```

## 7.7. Grounding policy

Finding запрещается публиковать, если:

- `source_section` отсутствует;
- retrieval score ниже порога;
- цитата не найдена на странице;
- critic не подтвердил entailment;
- норма не применима к категории объекта;
- версия нормативного акта неизвестна.

## 7.8. Метрики

- Recall@5 нормативных chunks;
- MRR;
- NLI macro-F1;
- evidence page accuracy;
- unsupported citation rate;
- requirement coverage precision;
- экспертная подтверждаемость top-10.

## 7.9. MVP scope

- 20-30 atomic requirements;
- 3 документа;
- BM25 + multilingual embeddings + LLM/NLI;
- не более 5 типов findings;
- ручная проверка всех требований в demo project.

# 8. P3 - Quantitative Consistency Pillar

## 8.1. Цель

Найти числовые, единичные и статистические противоречия внутри и между документами.

## 8.2. Объекты анализа

- источники выбросов;
- вещества;
- г/с;
- т/год;
- часы работы;
- объёмы отходов;
- классы опасности;
- частота измерений;
- сроки;
- координаты;
- расстояния;
- площади;
- итоговые суммы.

## 8.3. Канонизация

До ML все величины приводятся к единой схеме:

```json
{
  "entity_type": "pollutant_emission",
  "source_id": "0003",
  "pollutant_code": "0301",
  "pollutant_name_normalized": "nitrogen_dioxide",
  "value": 2.4,
  "unit": "ton_per_year",
  "original_value": "2,4",
  "original_unit": "т/год",
  "page": 51
}
```

## 8.4. Уровни проверки

### Уровень A - deterministic

- сумма строк равна итогу;
- единица распознана;
- дата начала меньше даты окончания;
- source ID существует;
- значение не отрицательное;
- г/с и т/год согласованы с режимом работы в допустимом диапазоне.

### Уровень B - peer anomaly

Сравнение с группой похожих объектов:

- отрасль;
- мощность;
- тип оборудования;
- категория;
- количество источников.

Модели:

- Isolation Forest;
- Local Outlier Factor;
- Robust Z-score;
- autoencoder после накопления данных.

### Уровень C - supervised inconsistency classifier

Обучение на gold и counterfactual pairs:

- decimal shift;
- missing row;
- duplicated row;
- mismatched unit;
- wrong total;
- inconsistent year.

## 8.5. Пример 1 - decimal shift

```text
NDV table: 2.40 t/year
Summary table: 24.00 t/year
```

Система сообщает не "нарушение", а:

> Возможная ошибка разряда или несогласованность итоговой таблицы. Разница: 10x. Уверенность 0.97.

## 8.6. Пример 2 - режим работы

```text
0.084 g/s * 8,760 h/year = 2.65 t/year
Document states: 0.265 t/year
```

Finding должен учитывать, что источник может работать не весь год. Поэтому система запрашивает часы работы и показывает формулу.

## 8.7. Признаки pillar score

```text
hard_rule_violation_count
sum_mismatch_ratio
unit_conversion_error_count
source_coverage_ratio
pollutant_coverage_ratio
peer_anomaly_percentile
missing_numeric_evidence_ratio
cross_table_duplicate_count
```

## 8.8. Метрики

- cell extraction accuracy;
- exact numeric match;
- tolerance-aware numeric F1;
- anomaly precision@k;
- known planted anomaly recall;
- false positive rate на корректных counterfactual controls.

## 8.9. MVP scope

- источники выбросов;
- загрязняющие вещества;
- г/с и т/год;
- объёмы отходов;
- периоды;
- 5 deterministic checks;
- Isolation Forest на агрегатах;
- 100-300 counterfactual rows.

# 9. P4 - Cross-document Coherence Pillar

## 9.1. Цель

Проверить, описывают ли связанные документы один и тот же объект непротиворечиво.

## 9.2. Knowledge graph

Основные типы узлов:

```text
Company
Facility
ProductionProcess
EmissionSource
Pollutant
WasteType
MonitoringItem
MitigationMeasure
Document
Requirement
GeoObject
```

Основные связи:

```text
Company OPERATES Facility
Facility HAS_SOURCE EmissionSource
EmissionSource EMITS Pollutant
EmissionSource MONITORED_BY MonitoringItem
Facility GENERATES WasteType
MitigationMeasure REDUCES Pollutant
Document ASSERTS Entity
Finding SUPPORTED_BY Evidence
```

## 9.3. Entity resolution

Один источник может называться:

- источник №0003;
- ИЗА 0003;
- дымовая труба 180 м;
- труба котельной;
- основной организованный источник.

Resolution pipeline:

1. exact ID match;
2. normalized string match;
3. fuzzy match;
4. attribute match: высота, координаты, оборудование;
5. embedding similarity;
6. LLM adjudication только при конфликте;
7. expert confirmation для uncertain pairs.

## 9.4. Типы findings

- source exists in NDV but missing in PEK;
- pollutant exists in NDV but missing in monitoring plan;
- waste volume differs between summary and PUO;
- object category differs;
- validity periods differ;
- coordinates differ;
- mitigation plan does not address high-risk pollutant;
- facility name/BIN mismatch.

## 9.5. Пример

```json
{
  "finding_type": "source_missing_in_monitoring",
  "entity": "EmissionSource:0017",
  "ndv_evidence": {"page": 62, "row": 17},
  "pek_evidence": {"page": 31, "matched_sources": 16},
  "resolution_confidence": 0.93,
  "severity": "high"
}
```

## 9.6. Модели

### MVP

- NetworkX;
- rules over graph;
- string/fuzzy/embedding resolution;
- confidence-weighted matching.

### Продвинутый путь

- graph database Neo4j;
- graph embeddings;
- link prediction;
- graph neural network для поиска типовых схем несогласованности.

GNN не нужен для первого MVP: отсутствие достаточных размеченных графов делает его декоративным.

## 9.7. Метрики

- entity match precision/recall;
- graph edge accuracy;
- unresolved entity ratio;
- contradiction precision@k;
- expert confirmation rate.

# 10. P5 - Visual & Spatial Evidence Pillar

## 10.1. Цель

Использовать изображения как самостоятельный источник доказательств, а не как иллюстрацию к тексту.

## 10.2. Типы визуальных объектов

- генеральный план;
- карта санитарно-защитной зоны;
- схема источников;
- технологическая схема;
- карта территории воздействия;
- фотография промышленной площадки;
- фотография объявления;
- диаграмма и график;
- сканированная таблица;
- спутниковый crop.

## 10.3. Подзадачи

### A. Классификация изображения

```text
site_plan
sanitary_zone_map
process_diagram
emission_source_scheme
photo
chart
scanned_table
irrelevant_image
```

### B. Проверка обязательных элементов карты

- legend;
- scale;
- north arrow;
- coordinate grid;
- boundary;
- source labels;
- sanitary zone;
- residential areas.

### C. Visual-text consistency

- номера источников на карте против таблицы;
- количество объектов;
- координаты;
- подписи;
- расстояния.

### D. Photo evidence

Только осторожные candidate findings:

- объект, похожий на открытую площадку хранения;
- резервуар или труба, отсутствующие в схеме;
- отсутствие видимой маркировки;
- потенциальное несоответствие фотографии и генплана.

## 10.4. Модельная стратегия

### Текущий MVP

- Docling image extraction;
- Qwen2.5-VL или другая доступная VLM;
- object/label extraction в JSON;
- OCR поверх crop;
- deterministic comparison с таблицей.

Qwen2.5-VL описывает document parsing, chart/diagram understanding и structured extraction как одну из сильных областей [R11]. Модель должна быть заменяемой.

### Специализированная модель позже

- layout detector на DocLayNet;
- detector источников/подписей на собственном dataset;
- segmentation для границ зон;
- remote-sensing encoder для satellite images.

## 10.5. Пример VLM contract

```json
{
  "image_type": "emission_source_scheme",
  "detected_source_ids": ["0001", "0002", "0003", "0017"],
  "has_scale": true,
  "has_legend": true,
  "has_north_arrow": false,
  "uncertain_items": [
    {"label": "0017", "confidence": 0.62, "bbox": [322, 181, 365, 215]}
  ]
}
```

## 10.6. Пример finding

> На схеме обнаружена подпись источника 0017. В таблице инвентаризации источник 0017 не найден. Уверенность распознавания подписи 0.62, поэтому finding направлен как `clarification_required`, а не как подтверждённое несоответствие.

## 10.7. Метрики

- image type macro-F1;
- label OCR accuracy;
- source ID detection recall;
- map element detection F1;
- visual-text consistency precision;
- unsupported visual claim rate.

## 10.8. Ограничения

- Sentinel-2 с разрешением 10-60 м не предназначен для уверенного распознавания мелкого оборудования;
- фото не доказывает юридическое нарушение;
- VLM может ошибаться на мелких подписях;
- каждое visual finding должно содержать crop и confidence.

# 11. P6 - Contextual Environmental Risk Pillar

## 11.1. Цель

Добавить контекст, которого нет в документах, чтобы приоритизировать экспертную проверку.

## 11.2. Источники

- OpenStreetMap;
- Copernicus Sentinel-1/2;
- Kazhydromet;
- OpenAQ;
- открытые административные и статистические данные;
- рельеф и land cover;
- данные ближайших чувствительных объектов.

## 11.3. Признаки

```text
distance_to_residential_area
distance_to_school
distance_to_hospital
distance_to_water_body
distance_to_protected_area
population_density_buffer
industrial_facility_density
land_cover_distribution
ndvi_change
ndwi_change
built_up_change
nearby_air_monitoring_anomaly
wind_direction_exposure
```

## 11.4. Пример Overpass use case

По координатам объекта получить в радиусе 3 км:

- школы;
- больницы;
- жилые здания;
- реки и водоёмы;
- промышленные объекты.

Пример логики:

```text
if nearest_school < 500 m and high_emission_source_count > threshold:
    increase review priority
```

Это не означает наличие нарушения. Признак используется для **приоритета проверки**, а не для обвинения.

## 11.5. Satellite pipeline

1. Получить Sentinel-2 Level-2A до и после даты проекта.
2. Фильтровать облачность.
3. Вычислить NDVI, NDWI, NDBI.
4. Создать buffer вокруг объекта.
5. Оценить land-cover composition и change score.
6. Сохранить дату, tile ID и processing parameters.

## 11.6. Модели

### MVP

- geospatial feature engineering;
- rule-based context flags;
- simple gradient boosting context score.

### Full

- pretrained encoder BigEarthNet/SEN12MS;
- fine-tuning на казахстанских территориях;
- time-series change detection;
- multimodal fusion Sentinel-1 + Sentinel-2.

## 11.7. Метрики

- geocoding success rate;
- distance calculation validation;
- land-cover classification F1;
- change-detection precision;
- stability across seasons;
- missing context coverage.

## 11.8. Почему P6 можно отложить

P6 сильный для роста, но для короткого MVP может отвлекать от основной ценности: проверки документов. Его можно реализовать только как один geo-demo и не включать в обученный итоговый score до появления валидированных labels.

# 12. Meta Risk Scoring

## 12.1. Что означает score

**Environmental Review Priority Score** - вероятность или калиброванный приоритет того, что пакет требует исправления, дополнительного запроса или углублённой проверки.

Score **не означает**:

- вероятность экологического преступления;
- вероятность штрафа;
- вероятность вреда здоровью;
- юридическую виновность;
- автоматический отказ.

## 12.2. Targets

### Основной target

```text
expert_action_required:
0 - можно продолжить стандартную проверку;
1 - требуется исправление, запрос или углублённая проверка.
```

### Дополнительные targets

- severity;
- finding_type;
- confirmed_findings_count;
- resubmission_required;
- review_minutes;
- top-k expert priority.

## 12.3. Features

Используются агрегаты pillars, а не сырые названия предприятия:

```text
P1_score, P1_confidence
P2_score, P2_confidence
P3_score, P3_confidence
P4_score, P4_confidence
P5_score, P5_confidence
P6_score, P6_confidence
critical_findings_count
high_findings_count
evidence_quality_mean
missing_data_ratio
agent_disagreement
ocr_quality
package_complexity
object_category
industry_group
```

## 12.4. Модели

### Baseline 1

Rule-based weighted score.

### Baseline 2

Logistic Regression.

### Основная модель

Calibrated XGBoost:

- эффективен на табличных признаках;
- поддерживает missing values;
- объясняется SHAP;
- поддерживает monotonic constraints [R23];
- поддерживает interaction constraints, уменьшающие риск нелогичных взаимодействий [R24].

### Альтернативы

- CatBoost для категориальных признаков;
- LightGBM;
- Explainable Boosting Machine;
- Bayesian logistic regression для малых данных;
- ordinal model для severity.

## 12.5. Monotonic constraints

Примеры ожидаемой монотонности:

- больше подтверждённых critical findings не должно снижать risk;
- выше missing evidence ratio не должно снижать uncertainty;
- выше evidence quality не должна снижать confidence;
- больше negative controls не должно повышать environmental risk.

## 12.6. Калибровка

Использовать:

- sigmoid calibration;
- isotonic calibration при достаточных данных;
- calibration curve;
- Expected Calibration Error;
- Brier score [R26];
- calibration отдельно для отраслей.

Калибратор обучается на отдельном validation fold.

## 12.7. Работа с отсутствующими modalities

Если нет карт или фотографий:

- P5 не считается нулём;
- создаётся `P5_missing = 1`;
- score использует available pillars;
- confidence снижается;
- UI сообщает, какие данные отсутствуют.

## 12.8. Explainability

Для каждого проекта показываются:

1. pillar score breakdown;
2. SHAP waterfall;
3. top evidence findings;
4. counterfactual explanation;
5. uncertainty;
6. ограничения.

Пример:

```text
Review Priority: 0.78

+0.21: 4 источника из НДВ отсутствуют в ПЭК
+0.16: 3 нормативных требования не подтверждены
+0.10: числовая сумма по NO2 отличается в 10 раз
+0.06: отсутствует приложение, на которое есть ссылка
-0.04: высокая полнота исходного пакета
```

# 13. P7 - Causal Robustness & Dataset Audit

![Пример причинного графа](assets/causal_graph.png)

## 13.1. Назначение

P7 не ищет нарушения и не должен напрямую увеличивать risk. Он отвечает на вопрос:

> Реагирует ли модель на содержательные несоответствия или использует shortcuts: регион, имя компании, логотип, шаблон, год и качество сканирования?

## 13.2. Что можно и нельзя утверждать

Корректно:

> Модель устойчива к измеренным confounders на проведённых тестах; placebo и negative-control effects близки к нулю; качество сохраняется на unseen domains.

Некорректно:

> Мы доказали полное отсутствие confounding.

Ненаблюдаемое confounding полностью исключить невозможно без сильных допущений или рандомизированного дизайна.

## 13.3. Causal questions

### Q1. Эффект реального несоответствия

```text
T = наличие numeric mismatch
Y = risk score или expert_action_required
C = отрасль, регион, масштаб, год, разработчик, OCR quality
```

### Q2. Эффект отсутствующего нормативного доказательства

```text
T = удалён обязательный фрагмент
Y = P2 score / final risk
```

### Q3. Эффект визуального противоречия

```text
T = источник присутствует на схеме, но удалён из таблицы
Y = P5/P4 score
```

### Q4. Полезность AI для эксперта

```text
T = работа с AI или без AI
Y1 = время проверки
Y2 = recall подтверждённых findings
Y3 = false positive count
```

## 13.4. Treatments

Не использовать один расплывчатый treatment. Создать отдельные:

```text
T_numeric_mismatch
T_missing_required_section
T_missing_monitoring_source
T_pollutant_list_mismatch
T_visual_table_mismatch
T_coordinate_mismatch
T_missing_emergency_plan
```

## 13.5. Потенциальные confounders

- отрасль;
- регион;
- категория объекта;
- масштаб;
- год;
- разработчик документа;
- шаблон;
- тип файла;
- количество страниц;
- OCR quality;
- scanned/digital;
- количество таблиц;
- наличие изображений;
- сложность проекта.

## 13.6. Counterfactual pair generator

Создавать контролируемые пары, где меняется только один фактор.

### Pair A - numeric mismatch

```text
Original: 2.4 t/year -> 2.4 t/year
Counterfactual: 2.4 t/year -> 24.0 t/year
```

### Pair B - missing source

```text
Original: source 0012 in NDV and PEK
Counterfactual: source 0012 removed from PEK
```

### Pair C - missing requirement

```text
Original: emergency plan section present
Counterfactual: section removed, metadata unchanged
```

### Pair D - visual mismatch

```text
Original: source IDs 0001-0015 in plan and table
Counterfactual: source 0016 inserted only in plan
```

## 13.7. Negative controls

Изменения, которые не должны существенно менять score:

- логотип;
- название компании;
- БИН;
- имя файла;
- шрифт;
- положение титульного блока;
- регион, если он не является легитимным фактором конкретного finding;
- случайный placebo feature.

## 13.8. CML методы

### DoWhy

Использовать для:

- явного causal graph;
- identification;
- estimation wrapper;
- placebo treatment refuter;
- random common cause;
- data subset refuter;
- sensitivity analysis.

DoWhy специально поддерживает refutation и falsification causal assumptions [R17].

### EconML

Рекомендуемые estimators:

- LinearDML - основной понятный estimator;
- CausalForestDML - heterogeneous effects;
- DRLearner - robustness при корректности одной из nuisance models.

EconML предоставляет ML-оценку heterogeneous treatment effects и Double Machine Learning [R18].

### Простые обязательные baselines

- difference in means на рандомизированных synthetic pairs;
- paired t-test или bootstrap CI;
- regression adjustment;
- propensity weighting для observational subset.

## 13.9. Causal audit dashboard

### Dataset composition

- проекты по регионам;
- отрасли;
- годы;
- разработчики;
- positive/negative labels;
- scanned/digital;
- availability modalities.

### Overlap

Показать propensity score distributions treatment/control.

### Covariate balance

Показать standardized mean difference до и после adjustment.

### Forest plot

```text
Missing regulatory evidence    +0.41 [0.34, 0.48]
Numeric mismatch               +0.36 [0.29, 0.43]
Source missing in PEK          +0.33 [0.25, 0.40]
Logo change                    +0.01 [-0.02, 0.03]
Company-name change            -0.01 [-0.03, 0.02]
Random placebo                  0.00 [-0.03, 0.02]
```

### Counterfactual Direction Accuracy

Доля meaningful interventions, после которых score изменился в ожидаемую сторону.

### Negative Control Stability

Доля irrelevant interventions с `abs(delta_score) < epsilon`.

### Domain generalization

- unseen company;
- unseen developer;
- unseen region;
- unseen year;
- unseen industry.

## 13.10. Nuisance-only model

Обучить отдельную модель только на:

```text
region, company, developer, year, filename, page_count, OCR quality, template
```

Желаемый результат:

```text
Full content model AUROC: 0.86
Content-only model:       0.83
Nuisance-only model:      0.55-0.60
```

Если nuisance-only model показывает высокий результат, scoring нельзя считать надёжным.

## 13.11. Adversarial source validation

Target:

```text
dataset_source / region / developer
```

Если classifier легко определяет источник датасета по model features, необходимо:

- harmonization;
- masking;
- balancing;
- source-aware splits;
- domain adaptation;
- удаление shortcut features.

## 13.12. Causal experiment с экспертами

Рекомендуемый crossover design:

| Группа | Пакет A | Пакет B |
|---|---|---|
| Эксперты 1 | с AI | без AI |
| Эксперты 2 | без AI | с AI |

Измерять:

- минуты;
- найденные gold findings;
- false positives;
- confidence эксперта;
- agreement между экспертами.

Даже небольшой pilot лучше необоснованного заявления о сокращении времени.

# 14. Agentic и LLM часть

![Контролируемый agent flow](assets/agent_flow.png)

## 14.1. Почему multi-agent

Разные задачи требуют разных инструментов и контекста:

- regulatory agent работает с нормами;
- quantitative agent работает с таблицами и кодом;
- vision agent работает с crops;
- graph agent работает с entities;
- critic agent проверяет provenance.

Один универсальный агент будет:

- получать слишком большой контекст;
- путать роли;
- хуже тестироваться;
- создавать больше hallucinations;
- усложнять повторяемость.

## 14.2. Оркестратор

Рекомендуется LangGraph или собственная state machine. LangGraph предоставляет persistence и human-in-the-loop для stateful workflows [R09].

### Состояние

```python
class ProjectState(TypedDict):
    project_id: str
    document_ids: list[str]
    ingestion_status: dict
    pillar_results: dict
    candidate_findings: list[dict]
    verified_findings: list[dict]
    meta_score: dict | None
    causal_audit: dict | None
    human_decisions: list[dict]
    errors: list[dict]
```

## 14.3. Agents

### Document Router Agent

- классифицирует документ;
- выбирает parser;
- не формирует risk.

### Regulatory Agent

- выбирает применимые requirements;
- вызывает retrieval;
- формирует structured coverage result.

### Quantitative Agent

- выбирает таблицы;
- вызывает Python tools;
- не выполняет арифметику текстом.

### Graph Agent

- создаёт candidate entity matches;
- разрешает ambiguous matches;
- сохраняет confidence.

### Vision Agent

- выбирает crops;
- вызывает VLM;
- возвращает объекты и bbox.

### Geo Agent

- вызывает OSM/Sentinel/Kazhydromet tools;
- возвращает feature table.

### Evidence Critic

Проверяет:

- существует ли документ;
- существует ли страница;
- совпадает ли quote;
- есть ли bbox;
- применима ли норма;
- не конфликтуют ли два agents;
- достаточно ли confidence.

### Explanation Composer

- не создаёт новые факты;
- переводит verified structured findings в понятный текст;
- перечисляет ограничения.

## 14.4. Structured outputs

Все агенты обязаны возвращать Pydantic/JSON schema. Свободный текст используется только в поле `explanation`.

```python
class Finding(BaseModel):
    finding_id: str
    pillar: str
    finding_type: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float
    title: str
    explanation: str
    evidence: list[Evidence]
    requirement_id: str | None
    status: Literal["candidate", "verified", "suppressed"]
    limitations: list[str]
```

## 14.5. Prompting policy

Каждый system prompt должен включать:

1. роль;
2. разрешённые инструменты;
3. запрет на финальное решение;
4. требование evidence;
5. JSON schema;
6. действия при недостатке данных;
7. два положительных и два отрицательных примера.

### Пример system prompt для Regulatory Agent

```text
Ты проверяешь только покрытие переданного requirement_id.
Не делай общий юридический вывод.
Используй только предоставленные chunks.
Если доказательства недостаточны, верни insufficient_evidence.
Не придумывай номер страницы или нормативный пункт.
Ответ должен соответствовать RegulatoryFindingSchema.
```

## 14.6. LLM provider abstraction

```python
class TextLLMProvider(Protocol):
    async def structured_generate(
        self,
        messages: list[dict],
        schema: type[BaseModel],
        model_options: dict,
    ) -> BaseModel: ...

class VisionLLMProvider(Protocol):
    async def analyze(
        self,
        image_uri: str,
        prompt: str,
        schema: type[BaseModel],
    ) -> BaseModel: ...

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

## 14.7. Текущие модели и миграция на AlemLLM

### Сейчас

Использовать доступную LLM, которая поддерживает:

- русский язык;
- structured output;
- tool use;
- длинный контекст;
- стабильные ответы.

Для vision - отдельная VLM, например Qwen2.5-VL.

### Позже

AlemLLM использовать для:

- казахского/русского regulatory reasoning;
- bilingual explanations;
- entity extraction;
- critic agent;
- summarization;
- генерации вопросов для уточнения.

Официальная model card AlemLLM указывает MoE-архитектуру, 247B total и 22B activated parameters, а также пример OpenAI-compatible serving через vLLM [R10]. Это означает:

- модель тяжёлая для локального ноутбука;
- provider abstraction обязателен;
- для production нужен серверный inference;
- vision остаётся отдельной моделью;
- числовые проверки остаются кодом.

## 14.8. Fine-tuning strategy

### Не делать на первом этапе

Не fine-tune большую LLM на десятках документов. Это создаст иллюзию прогресса без достаточной оценки.

### Сначала

- prompt + RAG baseline;
- gold evaluation set;
- error taxonomy;
- structured outputs;
- retrieval evaluation.

### Затем

- LoRA/QLoRA для extraction/classification;
- instruction dataset `requirement + evidence -> status`;
- казахско-русские пары;
- hard negatives;
- abstention examples;
- critic training.

## 14.9. LLM evaluation

Отдельно измерять:

- schema validity;
- factual grounding;
- page citation accuracy;
- requirement ID accuracy;
- abstention quality;
- hallucination rate;
- RU/KZ consistency;
- latency;
- token cost;
- inter-run stability.

## 14.10. LLM security

Документы являются недоверенным вводом. Возможен prompt injection внутри PDF.

Меры:

- документный текст никогда не становится system prompt;
- инструменты разрешены по allowlist;
- agents не выполняют команды из документа;
- ссылки и вложения не открываются автоматически;
- вывод проходит schema validation;
- все tool calls логируются;
- опасные действия требуют human approval.

# 15. Датасет: полная стратегия

![Слои данных](assets/data_layers.png)

## 15.1. Главный принцип

Не смешивать разные назначения данных:

- general pretraining datasets учат базовой способности;
- Kazakhstan corpus даёт доменный язык и структуру;
- gold dataset даёт проверенную истину;
- counterfactual dataset проверяет причинную реакцию;
- risk table обучает meta-scorer;
- unseen-domain test оценивает generalization.

## 15.2. Layer A - Казахстанский экологический корпус

### Основной источник

Национальный банк данных о состоянии окружающей среды и природных ресурсов:

- портал общественных слушаний;
- карточки содержат metadata;
- могут содержать НДВ, ПУО, ПЭК, план мероприятий, нетехническое резюме, фотографии и протокол.

В публичной карточке проекта ИП КХ "Береке" опубликованы связанные файлы НДВ, ПУО, ПЭК, план мероприятий, резюме, фотографии и протокол [R02]. Это хороший seed project.

В карточке Усть-Каменогорской ТЭЦ опубликованы вопросы общественности и ответы, включая замечания к срокам, санитарной зоне, отходам и обоснованию материалов [R03]. Это источник weak labels и real-world reasoning examples.

### Как искать вручную

1. Открыть календарь/список опубликованных слушаний.
2. Фильтровать по типу проекта и периоду.
3. Ищите названия:
   - "проект нормативов допустимых выбросов";
   - "программа производственного экологического контроля";
   - "программа управления отходами";
   - "материалы на получение экологического разрешения";
   - "отчёт о возможных воздействиях".
4. Открыть карточку.
5. Проверить наличие раздела "Электронная версия проекта".
6. Скачать документы вручную для исследовательского корпуса.
7. Сохранить metadata и URL карточки.
8. Скачать протокол и зафиксировать замечания.
9. Проверить условия использования и не собирать лишние персональные данные.

### Как искать программно

Рекомендуемый безопасный путь:

- сначала проверить robots.txt и пользовательские условия;
- использовать низкую частоту запросов;
- сохранять только публичные ссылки и необходимые документы;
- не обходить авторизацию;
- реализовать resumable manifest;
- лучше запросить официальный dataset/API у организаторов или ведомства.

Пример manifest:

```csv
project_id,hearing_id,project_title,region,year,company_bin,document_type,url,sha256
P001,23981,"ИП КХ Береке",Abai,2025,...,NDV,...,...
```

### Минимальный размер MVP

- 15-30 проектов;
- 50-120 PDF;
- 500-2,000 страниц;
- 100-300 таблиц;
- 50-200 изображений/карт;
- 5-10 протоколов с содержательными замечаниями.

### Размер после 10 недель

- 200-500 проектов;
- 1,000+ документов;
- 10,000+ страниц;
- 1,000+ gold findings;
- 3,000+ counterfactual pairs.

## 15.3. Layer B - Нормативный корпус

Основные источники:

- Экологический кодекс Республики Казахстан [R04];
- Методика определения нормативов эмиссий [R05];
- Правила разработки программы производственного экологического контроля [R06];
- правила общественных слушаний;
- правила выдачи экологических разрешений;
- классификатор отходов;
- санитарные правила по санитарно-защитным зонам;
- связанные приказы и актуальные редакции.

### Структура regulation chunk

```json
{
  "regulation_id": "KZ-ECO-CODE-2021",
  "version_date": "2026-07-13",
  "article": "39",
  "paragraph": "5",
  "language": "ru",
  "text": "...",
  "effective_from": "...",
  "effective_to": null,
  "source_url": "...",
  "sha256": "..."
}
```

### Критически важно

- хранить дату редакции;
- не смешивать утратившие силу нормы;
- показывать пользователю version date;
- при обновлении нормативов пересчитывать affected requirements;
- сохранять history.

## 15.4. Layer C - Общие Document AI datasets

### DocLayNet

Назначение:

- layout detection;
- page segmentation;
- text/table/picture/title/list labels.

Официальный dataset содержит 80,863 вручную размеченных страниц и 11 layout classes [R12].

Использование:

- взять pretrained weights;
- не смешивать его labels с environmental risk;
- fine-tune на 200-500 вручную размеченных экологических страницах.

### PubTables-1M

Назначение:

- table detection;
- table structure recognition;
- rows, columns, cells, headers.

Официальный repository указывает 575,305 страниц и 947,642 полностью размеченных таблиц [R13].

Использование:

- pretrained Table Transformer;
- domain adaptation на экологических таблицах;
- GriTS/structure metrics;
- hard cases: merged cells, multi-page tables, Cyrillic text.

### Альтернатива 2026

PubTables-v2 может быть полезен для multi-page tables, но для MVP Table Transformer + PubTables-1M стабильнее и лучше документирован.

## 15.5. Layer D - Visual и remote-sensing datasets

### BigEarthNet v2.0

- 549,488 пар Sentinel-1/Sentinel-2 patches [R14];
- land-cover labels;
- полезен для encoder pretraining;
- не является dataset экологических нарушений.

### SEN12MS

- 180,662 georeferenced triplets Sentinel-1, Sentinel-2, MODIS land cover [R15];
- 13 каналов Sentinel-2;
- полезен для multi-sensor fusion.

### Sentinel-2

Copernicus Data Space предоставляет доступ к Sentinel-2 [R28]. Использовать Level-2A для surface reflectance.

### OpenStreetMap

Overpass API используется для тематических пространственных запросов [R29].

### Kazhydromet

Kazhydromet описывает мониторинг атмосферного воздуха в населённых пунктах и на автоматических постах [R30]. Данные можно использовать как внешний контекст, если доступен машиночитаемый формат или разрешённая выгрузка.

### OpenAQ

OpenAQ предоставляет открытую платформу агрегированных данных качества воздуха [R31]. Использовать как optional источник и проверять покрытие Казахстана.

## 15.6. Layer E - Gold expert dataset

### Unit of annotation

Не документ целиком, а finding с evidence.

```json
{
  "finding_id": "G-00018",
  "project_id": "P-001",
  "finding_type": "source_missing_in_pek",
  "severity": "high",
  "expert_action_required": 1,
  "evidence": [
    {"document_id": "NDV", "page": 47, "bbox": [...]},
    {"document_id": "PEK", "page": 22, "bbox": [...]}
  ],
  "requirement_id": "PEK-MONITORING-001",
  "annotator_id": "E-01",
  "adjudicated": true
}
```

### Annotation process

1. Два annotators независимо размечают subset.
2. Считается Cohen's kappa или Krippendorff alpha.
3. Конфликты рассматривает senior expert.
4. Сохраняется adjudicated label.
5. Указываются причины disagreement.

### Для MVP

- 10-15 проектов;
- 100-200 findings;
- 2 annotators хотя бы на 20% subset;
- 30-50 fully adjudicated findings.

## 15.7. Layer F - Weak labels

Источники:

- вопросы общественности;
- ответы инициатора;
- протоколы;
- мотивированные отказы, если публичны;
- повторная подача исправленного проекта;
- explicit phrases: "необходимо дополнить", "отсутствует", "исключить", "обосновать".

Weak labels нельзя считать gold. Для них хранить:

```text
label_source
label_confidence
extraction_method
expert_verified
```

## 15.8. Layer G - Synthetic and counterfactual data

### Зачем

- rare anomalies;
- causal testing;
- unit tests;
- balanced training;
- privacy-safe demo.

### Правила генерации

- изменять одну переменную;
- сохранять pair ID;
- логировать intervention;
- не смешивать synthetic и real test;
- проверять человеком sample;
- поддерживать reversible transformations.

### Intervention manifest

```json
{
  "pair_id": "CF-1021",
  "source_project": "P-001",
  "treatment": "decimal_shift",
  "location": {"document": "NDV", "page": 51, "cell": "R8C5"},
  "before": "2.4",
  "after": "24.0",
  "expected_direction": "risk_increase"
}
```

## 15.9. Split strategy

Никогда не split по страницам.

### Основной split

- group by project_id;
- затем проверить company_id и developer_id;
- StratifiedGroupKFold, если достаточно groups [R25].

### Дополнительные test sets

- unseen company;
- unseen developer;
- unseen region;
- temporal holdout;
- unseen industry;
- scanned-only;
- Kazakh-only;
- counterfactual pairs.

### Пример

```text
Train: projects 2021-2024
Validation: 2025, known industries, unseen projects
Test A: 2026 unseen companies
Test B: unseen developer templates
Test C: counterfactual pairs
Test D: negative controls
```

## 15.10. Dataset card

Обязательные разделы:

- motivation;
- sources;
- license/terms;
- collection process;
- time period;
- languages;
- modalities;
- annotation;
- known biases;
- personal data handling;
- split logic;
- synthetic generation;
- recommended uses;
- prohibited uses;
- update policy.

## 15.11. Data versioning

Рекомендуется:

- DVC или lakeFS;
- Git для schemas/config;
- object storage для файлов;
- immutable manifests;
- MLflow для experiments [R27];
- hash-based deduplication.

# 16. Anti-confounding и anti-leakage checklist

## 16.1. Masking

До training удалить или замаскировать:

- company name;
- BIN;
- person names;
- filename;
- logo;
- developer name;
- direct outcome phrases;
- final protocol outcome;
- future corrected version.

## 16.2. Post-outcome leakage

Если задача - оценить пакет до экспертизы, модель не должна видеть:

- итоговый протокол;
- официальный отказ;
- исправленную версию;
- expert comments, созданные после подачи;
- будущие monitoring values.

Эти данные можно использовать для labels, но не features.

## 16.3. Source balance

Нельзя допустить:

- все positives из одного региона;
- все negatives без протоколов;
- synthetic только в одном class;
- scanned PDFs только среди positives;
- один developer только в high-risk class.

## 16.4. Ablation tests

Обязательные сравнения:

```text
metadata only
text only
tables only
images only
text + tables
text + images
all pillars
all pillars without P7 audit
```

Если metadata-only model сильная, есть leakage/confounding.

# 17. Альтернативные pillars и пути

Пользователь может заменить один из pillars в зависимости от доступных данных и сроков.

## 17.1. Альтернатива A - Public Hearing Intelligence вместо P6

### Когда выбирать

- мало времени на satellite/geospatial;
- много протоколов и комментариев;
- нужен сильный NLP use case.

### Что делает

- классифицирует вопросы общественности;
- кластеризует повторяющиеся concerns;
- связывает вопрос с разделом документа;
- определяет, дан ли содержательный ответ;
- показывает unresolved concerns;
- формирует issue map.

### Модели

- multilingual text classification;
- topic clustering;
- semantic matching question-answer;
- NLI answer sufficiency;
- LLM summary.

### Пример

```text
Concern: санитарно-защитная зона
Questions: 8
Answered with evidence: 3
Partially answered: 2
Unresolved: 3
```

### Плюсы

- реальные weak labels;
- понятный human-centric impact;
- проще, чем satellite pipeline.

### Минусы

- зависит от качества протоколов;
- может стать слишком похожим на text analytics.

## 17.2. Альтернатива B - Audio/Video Hearing Analysis вместо P5

### Когда выбирать

- есть записи слушаний;
- команда сильна в ASR/NLP;
- мало качественных карт/фотографий.

### Пайплайн

- ASR;
- speaker diarization;
- question extraction;
- answer matching;
- contradiction с протоколом;
- unresolved issue detection.

### Главный finding

> В видеозаписи задан вопрос о выбросах, но соответствующий вопрос отсутствует в опубликованной таблице протокола.

### Риск

Это чувствительная проверка. Нужны высокая ASR accuracy, осторожные формулировки и legal review.

## 17.3. Альтернатива C - Temporal Compliance Monitoring вместо P4

### Когда выбирать

- доступны версии документов по годам;
- можно найти повторные подачи;
- нужен longitudinal product.

### Что делает

- сравнивает версии;
- определяет, исправлено ли замечание;
- отслеживает изменение показателей;
- обнаруживает regression;
- показывает diff нормативов.

### Модели

- semantic diff;
- entity-level version graph;
- change classification;
- time-series anomaly detection.

## 17.4. Альтернатива D - Uncertainty & Conformal Prediction вместо P7

### Когда выбирать

- слишком мало данных для убедительного CML;
- важнее статистически контролируемая неопределённость.

### Что делает

- conformal prediction sets;
- abstention;
- risk-coverage curves;
- selective classification;
- out-of-distribution detection.

### Плюс

Можно честно сказать:

> При coverage 90% система автоматически показывает findings только там, где confidence соответствует заданному уровню; остальные отправляет эксперту без автоматического вывода.

### Рекомендация

Не полностью заменять P7, а использовать conformal uncertainty как часть scoring, если успевает команда.

## 17.5. Альтернатива E - Emissions Sensor Reconciliation вместо P6

### Когда выбирать

- партнёр предоставляет данные датчиков;
- необходимо связать документы и фактический monitoring.

### Что делает

- сравнивает заявленные режимы и фактические time series;
- ищет missing periods;
- anomaly detection;
- change point detection;
- объясняет расхождения.

Это наиболее коммерчески сильный путь, но без данных партнёра не подходит для отбора.

# 18. Технический стек

## 18.1. Backend

- Python 3.11+;
- FastAPI;
- Pydantic;
- SQLAlchemy;
- PostgreSQL;
- pgvector;
- Redis/RQ или Celery;
- MinIO;
- NetworkX, позже Neo4j;
- GeoPandas, Rasterio, Shapely;
- scikit-learn;
- XGBoost;
- SHAP;
- DoWhy;
- EconML;
- PyTorch/Transformers;
- Docling.

## 18.2. Frontend

- Next.js;
- TypeScript;
- PDF.js;
- MapLibre/Leaflet;
- chart library;
- evidence side panel;
- decision log.

## 18.3. MLOps

- MLflow tracking and registry;
- DVC;
- Docker Compose;
- GitHub Actions;
- pytest;
- Ruff/Mypy;
- Prometheus/Grafana позже;
- OpenTelemetry traces;
- prompt version registry.

## 18.4. Storage

### PostgreSQL tables

```text
projects
documents
document_pages
page_blocks
tables
images
entities
entity_links
requirements
regulation_chunks
analysis_runs
pillar_results
findings
finding_evidence
expert_decisions
counterfactual_pairs
causal_audit_runs
model_versions
```

# 19. API design

```http
POST /api/projects
POST /api/projects/{id}/documents
POST /api/projects/{id}/analyze
GET  /api/projects/{id}/status
GET  /api/projects/{id}/pillars
GET  /api/projects/{id}/findings
GET  /api/findings/{id}
POST /api/findings/{id}/decision
GET  /api/projects/{id}/risk-score
GET  /api/projects/{id}/causal-audit
POST /api/projects/{id}/counterfactual-test
GET  /api/models/versions
```

## 19.1. Analysis status

```text
uploaded
validating
parsing
extracting
pillar_analysis
critic_verification
scoring
causal_audit
completed
failed
```

## 19.2. Idempotency

Повторный запуск с теми же:

- file hashes;
- config;
- model versions;
- prompt versions

должен возвращать существующий run или создавать явно новую версию.

# 20. Repository structure

```text
dalel-eco/
├── apps/
│   ├── api/
│   └── web/
├── services/
│   ├── ingestion/
│   ├── orchestration/
│   ├── scoring/
│   └── causal_audit/
├── packages/
│   ├── schemas/
│   ├── llm_providers/
│   ├── evidence/
│   └── common/
├── pillars/
│   ├── p1_document_integrity/
│   ├── p2_regulatory/
│   ├── p3_quantitative/
│   ├── p4_coherence/
│   ├── p5_visual/
│   ├── p6_context/
│   └── p7_causal_audit/
├── data/
│   ├── manifests/
│   ├── regulations/
│   ├── annotations/
│   └── synthetic_specs/
├── models/
├── evaluation/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── counterfactual/
│   └── regression/
├── docker-compose.yml
├── Makefile
└── README.md
```

# 21. План разработки

## 21.1. Критический MVP за 5 дней

### День 1 - data lock и ingestion

- выбрать 10-20 проектов;
- скачать 3-5 полных пакетов;
- создать manifest;
- поднять FastAPI/Postgres/MinIO/Next.js;
- интегрировать Docling;
- сохранять страницы, tables и images;
- вручную создать 15 atomic requirements.

**Definition of done:** один пакет загружается, разбирается и отображается по страницам.

### День 2 - P1 и P3

- document type/section classification;
- completeness checklist;
- canonical entities;
- table extraction;
- 5 numeric rules;
- counterfactual generator для 2 типов ошибок.

**Definition of done:** система находит минимум 3 проверяемых findings на demo package.

### День 3 - P2 и P4

- regulatory corpus;
- hybrid retrieval;
- NLI/LLM coverage;
- entity matching;
- source/pollutant coverage checks;
- Evidence schema.

**Definition of done:** каждый finding имеет page evidence и requirement ID.

### День 4 - P5, scorer, P7 minimum

- извлечение одной схемы/карты;
- VLM structured analysis;
- logistic/XGBoost baseline;
- SHAP;
- 50-100 counterfactual pairs;
- nuisance-only model;
- negative controls.

**Definition of done:** causal audit показывает meaningful vs irrelevant interventions.

### День 5 - UX, evaluation, packaging

- side-by-side evidence viewer;
- confirm/reject/request buttons;
- dashboard pillars;
- metrics;
- Docker one-command;
- README;
- demo video;
- 7-10 slides;
- limitations.

**Definition of done:** чистый end-to-end demo без ручного вмешательства разработчика.

## 21.2. Если времени мало

Сокращать в таком порядке:

1. P6 full satellite model -> один geo-context demo;
2. graph database -> NetworkX/rules;
3. trained VLM -> zero-shot VLM + verified JSON;
4. XGBoost -> logistic regression;
5. CausalForest -> paired counterfactual effects + LinearDML;
6. full Kazakh support -> RU baseline + selected KZ tests.

Не сокращать:

- evidence provenance;
- gold test set;
- human decisions;
- anti-leakage split;
- deterministic numeric checks;
- README и Docker.

## 21.3. 10-недельный roadmap

### Недели 1-2

- data agreement;
- ontology;
- annotation guideline;
- 100+ projects;
- baseline evaluation.

### Недели 3-4

- domain Document AI;
- robust table extraction;
- entity resolution;
- bilingual regulation registry.

### Недели 5-6

- visual/spatial pillar;
- geospatial context;
- improved scoring;
- calibration.

### Недели 7-8

- CML;
- active learning;
- expert experiment;
- security/privacy review.

### Недели 9-10

- AlemLLM adapter and evaluation;
- pilot dashboard;
- model cards;
- deployment;
- pitch and partner roadmap.

# 22. Evaluation matrix

| Компонент | Основная метрика | Secondary | MVP target |
|---|---|---|---:|
| Document type | Macro-F1 | accuracy | >0.90 |
| Section detection | Macro-F1 | missing recall | >0.80 |
| Table extraction | cell F1/GriTS | numeric accuracy | >0.85 on gold subset |
| Entity extraction | entity F1 | page provenance | >0.85 |
| Retrieval | Recall@5 | MRR | >0.90 for 20 requirements |
| NLI | Macro-F1 | abstention precision | >0.75 |
| Entity resolution | F1 | unresolved ratio | >0.80 |
| Visual labels | accuracy/F1 | bbox accuracy | >0.75 on limited set |
| Finding quality | Precision@10 | expert confirmation | >0.70 |
| Risk model | PR-AUC | AUROC | beat logistic baseline |
| Calibration | ECE/Brier | reliability diagram | visibly calibrated |
| Counterfactual | direction accuracy | delta magnitude | >0.85 |
| Negative controls | stability | placebo effect | >0.90 stable |
| Domain generalization | performance gap | calibration gap | report honestly |
| Human utility | time + recall | SUS/feedback | pilot measurement |

Не придумывать метрики до фактического эксперимента. В презентации показывать реальные значения и размер test set.

# 23. UX и demo flow

## 23.1. Экран 1 - Projects

```text
Project                  Documents  High findings  Status
Береке 2025-2034         5          4              Complete
ТЭЦ permit package       7          9              Review
```

## 23.2. Экран 2 - Pillar dashboard

```text
P1 Integrity        28/100 risk
P2 Regulatory       71/100 risk
P3 Quantitative     66/100 risk
P4 Coherence        74/100 risk
P5 Visual           42/100 risk
P6 Context          unavailable
Overall Priority    78/100
Confidence          moderate
```

## 23.3. Экран 3 - Finding

Слева:

- PDF page;
- highlighted bbox.

Справа:

- второе доказательство;
- карта/crop;
- requirement;
- explanation;
- confidence;
- SHAP/counterfactual.

Кнопки:

- подтвердить;
- отклонить;
- запросить уточнение;
- изменить severity;
- добавить комментарий.

## 23.4. Экран 4 - Causal audit

- dataset composition;
- nuisance-only score;
- counterfactual pairs;
- negative control stability;
- unseen-domain metrics;
- warning about unobserved confounding.

## 23.5. Demo script на 3 минуты

### 0:00-0:25 - проблема

> Один экологический пакет включает сотни страниц, таблицы и схемы. Ошибка может находиться не на одной странице, а между двумя документами.

### 0:25-0:45 - загрузка

Показать 4 реальных документа.

### 0:45-1:25 - findings

Открыть:

1. missing source in PEK;
2. numeric mismatch;
3. missing regulatory evidence;
4. visual-table mismatch.

### 1:25-1:50 - explainability

Показать page evidence, requirement, SHAP и limitation.

### 1:50-2:20 - CML

> Мы изменили логотип - score стабилен. Добавили числовое противоречие - score вырос. Placebo effect близок к нулю.

### 2:20-2:45 - human decision

Эксперт подтверждает finding и запрашивает уточнение.

### 2:45-3:00 - рост

> Сегодня это pre-review документов. Далее - AlemLLM, датчики, geospatial context и интеграция с государственным экологическим контуром.

# 24. Бизнес-модель и операционный потенциал

## 24.1. B2B SaaS

- оплата за пакет;
- подписка проектной организации;
- enterprise deployment;
- audit trail;
- API.

## 24.2. B2G

- лицензия/подписка;
- private cloud/on-premise;
- оплата за SLA;
- пилот в одном регионе;
- сервис обновления нормативов;
- model monitoring.

## 24.3. B2B2G

Предприятие проверяет документы до подачи, а государственный эксперт получает standardized evidence package. Это снижает число технических возвратов и ускоряет взаимодействие, не передавая решение частной системе.

## 24.4. Moat

- казахстанский multimodal environmental corpus;
- atomic requirement registry;
- expert feedback;
- counterfactual dataset;
- bilingual evaluation;
- provenance graph;
- интеграция с local LLM.

# 25. Риски и меры

| Риск | Влияние | Митигирование |
|---|---|---|
| Мало gold labels | Высокое | weak labels + expert subset + counterfactuals |
| LLM hallucination | Высокое | evidence gate, critic, structured outputs |
| Норматив устарел | Высокое | versioned regulation registry |
| PDF extraction errors | Высокое | fallback parsers, page confidence |
| Confounding | Высокое | group/time splits, nuisance model, P7 |
| Слишком большой scope | Высокое | 3-4 complete pillars, остальные demo-only |
| VLM неправильно читает карту | Среднее | crop, OCR, confidence, expert review |
| Satellite overclaim | Высокое | только context, не обвинение |
| Персональные данные | Среднее | minimization, redaction, public sources |
| Prompt injection | Среднее | tool allowlist, untrusted content policy |
| AlemLLM infrastructure | Среднее | provider adapter, server inference |
| Политическая чувствительность | Среднее | pre-review, не автоматический контроль/штраф |

# 26. Инструкции для другой LLM

Ниже готовый implementation brief, который можно передать coding LLM.

## 26.1. Master implementation prompt

```text
Ты ведущий AI/ML и backend engineer проекта DÁLEL Eco.

Цель: создать воспроизводимый Docker Compose MVP мультимодальной системы
предварительной проверки экологической документации Казахстана.

Не делай простой чат-бот. Система должна:
1. принимать связанные PDF НДВ, ПЭК и ПУО;
2. извлекать страницы, блоки, таблицы и изображения;
3. создавать canonical JSON с provenance;
4. выполнять P1 Document Integrity;
5. выполнять P2 Regulatory Compliance на registry из 20-30 требований;
6. выполнять P3 Quantitative Consistency;
7. выполнять P4 Cross-document Coherence;
8. выполнить ограниченный P5 Visual Evidence;
9. объединять pillar features в calibrated risk scorer;
10. иметь P7 Causal Robustness audit;
11. показывать evidence и human decision buttons.

Жёсткие ограничения:
- LLM не считает числа;
- LLM не выдаёт юридический вердикт;
- finding без page/bbox evidence подавляется;
- документы считаются недоверенным вводом;
- все LLM outputs валидируются Pydantic schemas;
- split только по project_id/company/developer, не по страницам;
- итоговый score означает review priority, а не виновность;
- все модели доступны через provider interfaces;
- код должен быть типизирован, протестирован и запускаться одной командой.

Стек:
- FastAPI, PostgreSQL, pgvector, MinIO, Redis/RQ;
- Next.js/TypeScript/PDF.js;
- Docling/PyMuPDF/Table Transformer;
- scikit-learn/XGBoost/SHAP;
- DoWhy/EconML;
- LangGraph или собственная state machine;
- MLflow;
- Docker Compose.

Сначала создай:
1. архитектурный README;
2. repository tree;
3. Pydantic schemas;
4. database models;
5. ingestion pipeline;
6. tests;
7. только после этого pillar implementations.

Для каждого модуля предоставляй:
- файл;
- полный код;
- unit tests;
- пример входа/выхода;
- команды запуска;
- failure handling.

Не придумывай данные. Для demo создай manifest, который указывает на локально
загруженные публичные документы. Synthetic transformations должны иметь pair_id,
treatment и expected direction.
```

## 26.2. Отдельный prompt для dataset agent

```text
Создай data pipeline для DÁLEL Eco.
Результат: immutable manifest, SHA-256, metadata, document type, project grouping,
source URL, license/terms note, language, year, region, company/developer masked IDs.

Запрещено:
- split по страницам;
- использовать протокол как feature для pre-review target;
- считать weak labels gold;
- смешивать synthetic и real test.

Создай:
- dataset_card.md;
- annotation_guideline.md;
- schema.json;
- split_manifest.csv;
- counterfactual_manifest.csv;
- validation scripts;
- leakage checks.
```

## 26.3. Prompt для CML agent

```text
Построй causal audit итогового risk scorer.

Treatments:
- numeric_mismatch;
- missing_requirement_evidence;
- missing_monitoring_source;
- visual_table_mismatch.

Outcomes:
- final risk score;
- expert_action_required.

Observed confounders:
industry, region, object_category, scale, year, developer_id, template_id,
page_count, OCR quality, scanned flag, table count, image count.

Обязательные outputs:
- causal DAG;
- overlap plot;
- SMD balance table;
- paired counterfactual effects;
- LinearDML estimate;
- optional CausalForestDML;
- placebo treatment refuter;
- random common cause refuter;
- nuisance-only model;
- negative-control stability;
- unseen-domain evaluation;
- limitations about unobserved confounding.

Не утверждай полное отсутствие confounding.
```

# 27. Definition of Done

MVP считается завершённым, если:

- [ ] Docker Compose запускает систему одной командой;
- [ ] загружается минимум один полный публичный пакет;
- [ ] каждый документ имеет hash и provenance;
- [ ] извлекаются страницы, таблицы и изображения;
- [ ] работают минимум P1, P2, P3 и P4;
- [ ] P5 показан хотя бы на одной схеме;
- [ ] минимум 10 verified findings имеют page evidence;
- [ ] пользователь может подтвердить/отклонить finding;
- [ ] есть baseline и основная scoring model;
- [ ] есть calibration plot;
- [ ] есть SHAP explanation;
- [ ] есть минимум 50 counterfactual pairs;
- [ ] negative controls показаны отдельно;
- [ ] nuisance-only model обучена;
- [ ] test split не содержит project leakage;
- [ ] README описывает данные, запуск, ограничения и ethics;
- [ ] demo video показывает полный сценарий;
- [ ] не делаются недоказанные заявления о causal effect или экономии времени.

# 28. Рекомендуемый финальный scope

## Реализовать полностью

- P0 ingestion;
- P1 integrity;
- P2 regulatory;
- P3 quantitative;
- P4 coherence;
- meta-scoring baseline;
- P7 causal audit minimum;
- evidence UX;
- human decision log.

## Реализовать демонстрационно

- P5 на одной карте/схеме;
- P6 на одном geo-context example.

## Оставить на 10 недель

- remote-sensing fine-tuning;
- full graph ML;
- large-scale AlemLLM deployment;
- production integration;
- causal expert trial с достаточной выборкой;
- active learning loop в реальном ведомстве.

# 29. Итоговая позиция проекта

DÁLEL Eco должен выглядеть не как "ещё один AI, читающий PDF", а как:

> **Evidence-first multimodal decision-support infrastructure for environmental review.**

Три главных конкурентных преимущества:

1. **Multi-pillar reasoning:** отдельные модели проверяют структуру, нормы, числа, связи, изображения и контекст.
2. **Causal robustness:** команда демонстрирует, что risk score реагирует на содержательные вмешательства и остаётся стабильным при irrelevant changes.
3. **Human authority:** эксперт видит доказательства и остаётся единственным лицом, принимающим решение.

# 30. Источники и ссылки

## Казахстанские данные и нормативы

- **[R01] Национальный банк данных, портал общественных слушаний:** https://hearings.ndbecology.gov.kz/
- **[R02] Пример полного пакета НДВ + ПУО + ПЭК + план + фото + протокол:** https://hearings.ndbecology.gov.kz/Public/PubHearings/PublicHearingDetail?hearingId=23981
- **[R03] Пример реальных вопросов и ответов по экологическому пакету ТЭЦ:** https://hearings.ndbecology.gov.kz/Public/PubHearings/PublicHearingDetail?hearingId=28876
- **[R04] Экологический кодекс Республики Казахстан:** https://adilet.zan.kz/rus/docs/K2100000400
- **[R05] Методика определения нормативов эмиссий:** https://adilet.zan.kz/rus/docs/V2100022317
- **[R06] Правила разработки программы производственного экологического контроля:** https://adilet.zan.kz/rus/docs/V2100023553
- **[R07] НБД как единое окно экологической отчётности:** https://www.gov.kz/memleket/entities/ecogeo/press/news/details/931901?lang=ru

## Document AI, agents и LLM

- **[R08] Docling documentation:** https://docling-project.github.io/docling/
- **[R09] LangGraph overview:** https://docs.langchain.com/oss/python/langgraph/overview
- **[R10] AlemLLM official model card:** https://huggingface.co/astanahub/alemllm
- **[R11] Qwen2.5-VL technical report:** https://arxiv.org/abs/2502.13923
- **[R12] DocLayNet official repository:** https://github.com/DS4SD/DocLayNet
- **[R13] PubTables-1M / Table Transformer:** https://github.com/microsoft/table-transformer

## Remote sensing и geospatial

- **[R14] BigEarthNet v2.0:** https://bigearth.net/
- **[R15] SEN12MS dataset:** https://mediatum.ub.tum.de/1474000
- **[R16] Copernicus Data Space:** https://dataspace.copernicus.eu/

## Causal ML и model evaluation

- **[R17] DoWhy official repository:** https://github.com/py-why/dowhy
- **[R18] EconML documentation:** https://www.pywhy.org/EconML/
- **[R19] DoWhy + EconML tutorial:** https://www.pywhy.org/dowhy/v0.8/example_notebooks/tutorial-causalinference-machinelearning-using-dowhy-econml.html
- **[R20] SHAP documentation:** https://shap.readthedocs.io/
- **[R21] XGBoost documentation:** https://xgboost.readthedocs.io/
- **[R22] Probability calibration, scikit-learn:** https://scikit-learn.org/stable/modules/calibration.html
- **[R23] XGBoost monotonic constraints:** https://xgboost.readthedocs.io/en/latest/tutorials/monotonic.html
- **[R24] XGBoost feature interaction constraints:** https://xgboost.readthedocs.io/en/stable/tutorials/feature_interaction_constraint.html
- **[R25] StratifiedGroupKFold:** https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html
- **[R26] Brier score:** https://scikit-learn.org/stable/modules/model_evaluation.html
- **[R27] MLflow tracking:** https://mlflow.org/docs/latest/ml/tracking/

## Environmental context data

- **[R28] Sentinel-2 official data page:** https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2
- **[R29] OpenStreetMap Overpass API:** https://wiki.openstreetmap.org/wiki/Overpass_API
- **[R30] Kazhydromet environmental monitoring:** https://www.kazhydromet.kz/en/ecology/monitoring-sostoyaniya-okruzhayuschey-sredy
- **[R31] OpenAQ:** https://openaq.org/

---

**Конец документа.**
