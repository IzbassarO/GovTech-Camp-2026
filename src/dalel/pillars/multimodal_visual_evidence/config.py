"""Versioned deterministic configuration for P5.

Every knob is a module constant captured verbatim into
``config_snapshot.json``; there is no config file and no environment
dependence (the only environment interaction is the optional model/OCR
availability, which is recorded honestly in ``model_metadata.json``).

The engine is conservative by construction: exclusion and duplicate rules are
generic (hashes, recurrence, geometry, entropy) and never reference concrete
filenames or asset numbers; model similarity is a review signal, never proof.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

P5_SCORING_CONFIG_VERSION = "1.0.0"

# --- visual classes ----------------------------------------------------------
# Meaningful environmental-evidence candidates.
MEANINGFUL_CLASSES: tuple[str, ...] = (
    "map",
    "site_photo",
    "industrial_equipment_photo",
    "technical_diagram",
    "process_flow_diagram",
    "site_plan",
    "impact_zone_diagram",
    "chart",
    "table",
    "satellite_or_aerial_image",
)
# Supporting / non-evidence classes.
SUPPORTING_CLASSES: tuple[str, ...] = (
    "procedural_notice",
    "text_fragment",
    "logo_or_branding",
    "stamp_or_signature",
    "qr_code",
)
ALL_CLASSES: tuple[str, ...] = (*MEANINGFUL_CLASSES, *SUPPORTING_CLASSES, "unknown")

# Map-like classes share the map-completeness cue check.
MAP_LIKE_CLASSES: frozenset[str] = frozenset(
    {"map", "site_plan", "impact_zone_diagram", "satellite_or_aerial_image"}
)
CHART_TABLE_CLASSES: frozenset[str] = frozenset({"chart", "table"})
# Classes that are plausibly project-specific evidence: identical reuse across
# documents/projects of these classes is worth an expert look.
PROJECT_SPECIFIC_CLASSES: frozenset[str] = frozenset(
    {
        "map",
        "site_photo",
        "industrial_equipment_photo",
        "technical_diagram",
        "process_flow_diagram",
        "site_plan",
        "impact_zone_diagram",
        "chart",
        "table",
        "satellite_or_aerial_image",
    }
)

RUSSIAN_CLASS_LABELS: dict[str, str] = {
    "map": "Карта",
    "site_photo": "Фото площадки",
    "industrial_equipment_photo": "Фото оборудования",
    "technical_diagram": "Технический чертёж",
    "process_flow_diagram": "Технологическая схема",
    "site_plan": "Генеральный план",
    "impact_zone_diagram": "Схема зоны воздействия",
    "chart": "График",
    "table": "Таблица",
    "satellite_or_aerial_image": "Спутниковый/аэроснимок",
    "procedural_notice": "Процедурная публикация",
    "text_fragment": "Фрагмент текста",
    "logo_or_branding": "Логотип/брендинг",
    "stamp_or_signature": "Печать/подпись",
    "qr_code": "QR-код",
    "unknown": "Не определено",
}

# --- zero-shot prompt ensembles ----------------------------------------------
# The multilingual text tower accepts both Russian and English prompts; each
# class similarity is the MEAN cosine similarity over its ensemble.
CLASS_PROMPTS: dict[str, tuple[str, ...]] = {
    "map": (
        "карта расположения объекта на местности",
        "топографическая карта района",
        "a map of a geographic area",
    ),
    "site_photo": (
        "фотография промышленной площадки под открытым небом",
        "фотография территории предприятия",
        "an outdoor photograph of an industrial site",
    ),
    "industrial_equipment_photo": (
        "фотография промышленного оборудования",
        "фотография установки или резервуара в цехе",
        "a photograph of industrial equipment or machinery",
    ),
    "technical_diagram": (
        "технический чертёж конструкции",
        "инженерная схема с размерами",
        "a technical engineering drawing",
    ),
    "process_flow_diagram": (
        "технологическая схема производственного процесса",
        "блок-схема процесса со стрелками",
        "a process flow diagram with boxes and arrows",
    ),
    "site_plan": (
        "генеральный план промышленной площадки",
        "план размещения зданий и сооружений",
        "an architectural site plan drawing",
    ),
    "impact_zone_diagram": (
        "схема санитарно-защитной зоны предприятия",
        "карта рассеивания загрязняющих веществ с изолиниями",
        "a pollution dispersion contour diagram",
    ),
    "chart": (
        "график с осями и числовыми данными",
        "столбчатая или линейная диаграмма",
        "a chart with axes and data series",
    ),
    "table": (
        "таблица с числовыми данными в строках и столбцах",
        "a table with rows and columns of numbers",
    ),
    "satellite_or_aerial_image": (
        "спутниковый снимок местности",
        "аэрофотоснимок территории сверху",
        "a satellite image of terrain",
    ),
    "procedural_notice": (
        "страница газеты с объявлением",
        "скан официального объявления для публикации",
        "a newspaper page with a public announcement",
    ),
    "text_fragment": (
        "отсканированный фрагмент печатного текста документа",
        "a scanned fragment of printed document text",
    ),
    "logo_or_branding": (
        "логотип компании",
        "фирменная эмблема организации",
        "a company logo",
    ),
    "stamp_or_signature": (
        "оттиск круглой печати организации и подпись",
        "a round official ink stamp and a handwritten signature",
    ),
    "qr_code": (
        "QR-код",
        "a QR code on a white background",
    ),
}

# --- vision-language model ---------------------------------------------------
# OpenCLIP multilingual CLIP: MIT-licensed code and weights, CPU inference.
# The text tower (XLM-RoBERTa base) understands Russian captions/prompts.
MODEL_NAME = "xlm-roberta-base-ViT-B-32"
MODEL_PRETRAINED_TAG = "laion5b_s13b_b90k"
MODEL_LICENSE = "MIT (OpenCLIP code and released weights; trained on LAION-5B)"
MODEL_DEVICE = "cpu"
MODEL_EMBEDDING_DIM = 512
MODEL_IMAGE_BATCH_SIZE = 8
MODEL_TEXT_BATCH_SIZE = 32
# Similarities are serialized rounded to this many decimals; the validator
# replays classification decisions from the rounded values.
SIMILARITY_DECIMALS = 6
CONFIDENCE_DECIMALS = 4
# Softmax temperature over per-class cosine similarities. A fixed constant --
# deliberately NOT the learned logit scale -- so the "classification
# confidence" reads as a calibrated-looking label affinity, honestly named:
# it is the share of similarity mass, not a probability of correctness.
SOFTMAX_TEMPERATURE = 50.0

# Decision thresholds over the softmax affinity distribution.
MODEL_MIN_TOP_AFFINITY = 0.30
MODEL_MIN_MARGIN = 0.05
# Context adjustment: a caption-implied class is adopted when the model ranks
# it within the top competitors above this affinity.
CONTEXT_ADJUST_MIN_AFFINITY = 0.12
CONTEXT_ADJUST_TOP_K = 3

# --- deterministic exclusion --------------------------------------------------
# A raster smaller than either bound carries too little signal for semantic
# analysis (icons, bullets, line fragments).
TINY_MIN_SIDE_PX = 64
TINY_MIN_AREA_PX = 8_192
# Near-uniform rasters (blank fills, separators).
UNIFORM_MAX_EXTREMA_SPAN = 3
UNIFORM_MAX_STDDEV = 2.0
# Perceptual near-duplicate linking: dHash Hamming distance and relative
# dimension tolerance (repeated page banners drift by a pixel or two).
DHASH_ALGORITHM = "dhash64"
NEAR_DUPLICATE_MAX_DISTANCE = 4
NEAR_DUPLICATE_DIM_TOLERANCE = 0.04
# A recurring cluster whose representative is at least this many times wider
# than tall is banner-like page furniture (e.g. a scanned applicant-name line
# repeated on every page), never environmental imagery. Generic by
# construction: recurrence + geometry, never filenames or asset numbers.
HEADER_ASPECT_RATIO = 3.0
HEADER_MIN_OCCURRENCES = 3
# A small raster recurring across documents is treated as branding.
LOGO_MAX_SIDE_PX = 256
LOGO_MIN_DOCUMENTS = 2

# --- OCR ---------------------------------------------------------------------
OCR_ENGINE = "easyocr"
OCR_LANGUAGES: tuple[str, ...] = ("ru", "en")
# Only cluster representatives are OCR-ed; duplicates reuse the representative
# result. Hard cap keeps live jobs bounded.
OCR_MAX_ASSETS = 300
OCR_MIN_SIDE_PX = 48
OCR_MIN_MEAN_CONFIDENCE = 0.2
OCR_TEXT_MAX_CHARS = 2_000

# --- context -----------------------------------------------------------------
CAPTION_PATTERNS: tuple[str, ...] = (
    r"^\s*(рис(?:унок|\.)?\s*№?\s*\d+[^\n]{0,200})",
    r"^\s*(схема\s*№?\s*\d+[^\n]{0,200})",
    r"^\s*(карта(?:-схема)?\s*№?\s*\d+[^\n]{0,200})",
    r"^\s*(фото(?:графия)?\s*№?\s*\d+[^\n]{0,200})",
    r"^\s*(диаграмма\s*№?\s*\d+[^\n]{0,200})",
)
# Explicit numbered references to visuals inside body text (check D).
FIGURE_REFERENCE_PATTERN = (
    r"(?:рис(?:унок|\.)?|схем[аеу]|карт[аеу](?:-схем[аеу])?|фото(?:графи[яи])?|"
    r"диаграмм[аеу])\s*№?\s*(\d{1,3})"
)
MISSING_VISUAL_MIN_REFERENCES = 2
PAGE_CONTEXT_SNIPPET_CHARS = 400
CAPTION_MIN_CHARS = 8
# Caption keywords that imply an expected class family (check B).
CAPTION_CLASS_HINTS: dict[str, tuple[str, ...]] = {
    "map": ("карта", "map"),
    "site_plan": ("генплан", "генеральный план", "ситуационный план"),
    "impact_zone_diagram": ("сзз", "санитарно-защитн", "рассеивани", "зона воздействия"),
    "site_photo": ("фото", "фотографи"),
    "technical_diagram": ("чертёж", "чертеж", "схема конструкции"),
    "process_flow_diagram": ("технологическая схема", "блок-схема"),
    "chart": ("график", "диаграмма"),
    "table": ("таблица",),
}
# Classes considered compatible with each caption hint (superset of the hint
# class itself; prevents flagging a site plan captioned as a map).
CAPTION_COMPATIBLE_CLASSES: dict[str, frozenset[str]] = {
    "map": frozenset({"map", "site_plan", "impact_zone_diagram", "satellite_or_aerial_image"}),
    "site_plan": frozenset({"site_plan", "map", "technical_diagram", "impact_zone_diagram"}),
    "impact_zone_diagram": frozenset({"impact_zone_diagram", "map", "site_plan", "chart"}),
    "site_photo": frozenset({"site_photo", "industrial_equipment_photo"}),
    "technical_diagram": frozenset(
        {"technical_diagram", "process_flow_diagram", "site_plan", "chart"}
    ),
    "process_flow_diagram": frozenset({"process_flow_diagram", "technical_diagram", "chart"}),
    "chart": frozenset({"chart", "impact_zone_diagram", "table", "process_flow_diagram"}),
    "table": frozenset({"table", "chart", "text_fragment"}),
}
# Entity terms shorter than this are too ambiguous to count as overlap.
ENTITY_TERM_MIN_CHARS = 5
ENTITY_TERM_MAX_COUNT = 40

# --- cross-modal thresholds --------------------------------------------------
# Cosine similarity below which an image-text pair is treated as a weak-link
# review cue (check A). Low similarity is NEVER a proven contradiction.
RELEVANCE_LOW_SIMILARITY = 0.10
# Mismatch findings (check B) additionally require a confidently classified
# asset (see MODEL_MIN_TOP_AFFINITY / MODEL_MIN_MARGIN).
MISMATCH_MIN_AFFINITY = 0.45

# --- duplicate-inflation check (C) -------------------------------------------
DUPLICATE_INFLATION_MIN_MEMBERS = 5

# --- map/chart completeness cues (E, F) --------------------------------------
MAP_CUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "legend": ("условные обозначения", "легенда", "экспликация"),
    "scale": ("масштаб", "м 1:", "1:"),
    "coordinates": ("°", "координат", "широт", "долгот"),
    "boundary": ("граница", "сзз", "санитарно-защитн"),
    "location_marker": ("площадка", "объект", "предприяти"),
}
MAP_CUE_MIN_OCR_TOKENS = 3
CHART_CUE_UNIT_KEYWORDS: tuple[str, ...] = (
    "мг/",
    "г/с",
    "т/год",
    "т/г",
    "%",
    "мкг/",
    "дб",
    "дба",
)

# --- severity / scoring ------------------------------------------------------
# Same points table as the sibling pillars; high severity is NEVER produced by
# P5 (no visual signal alone is strong enough).
SEVERITY_POINTS: dict[str, int] = {
    "high": 25,
    "medium": 12,
    "low": 5,
    "info": 2,
}
SCORE_CAP = 100
MAX_SEVERITY = "medium"

FINDING_TYPES: tuple[str, ...] = (
    "visual_relevance_review",
    "caption_image_mismatch",
    "duplicate_visual_inflation",
    "missing_referenced_visual",
    "map_completeness_cue",
    "chart_readability_cue",
    "cross_document_visual_reuse",
)
# Finding-type base confidence (deterministic rubric, mirrors P4 conventions).
FINDING_CONFIDENCE: dict[str, float] = {
    "visual_relevance_review": 0.3,
    "caption_image_mismatch": 0.55,
    "duplicate_visual_inflation": 0.85,
    "missing_referenced_visual": 0.5,
    "map_completeness_cue": 0.5,
    "chart_readability_cue": 0.45,
    "cross_document_visual_reuse": 0.85,
}
CONFIDENCE_MIN = 0.05
CONFIDENCE_MAX = 0.95
CONFIDENCE_PENALTIES: dict[str, float] = {
    "ocr_low_confidence": 0.1,
    "ocr_unavailable": 0.15,
    "model_low_margin": 0.1,
    "sparse_context": 0.1,
}

# --- assessment confidence / coverage ----------------------------------------
# Deterministic blend recorded per component in the project score so the
# validator can recompute it. Weights sum to 1.0.
ASSESSMENT_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "model_available": 0.4,
    "classification_decisiveness": 0.25,
    "ocr_success_share": 0.15,
    "context_link_share": 0.2,
}
ASSESSMENT_CONFIDENCE_MIN = 0.05
ASSESSMENT_CONFIDENCE_MAX = 0.95

META_INTEGRATION_STATUS = "pending_p6_meta_v2"

PROJECT_SCORE_NOTE = (
    "Приоритет проверки визуальных доказательств — очередь ручной проверки."
    " Это НЕ вероятность экологического вреда, НЕ вероятность соответствия"
    " законодательству и НЕ сертификация подлинности изображений."
)
DOCUMENT_SCORE_NOTE = (
    "Сумма баллов находок P5 по документу (с ограничением сверху)."
    " Приоритет проверки, а не оценка риска или нарушения."
)

# --- review template ---------------------------------------------------------
REVIEW_TEMPLATE_FILENAME = "p5_review_template.jsonl"
REVIEW_TEMPLATE_LOW_INFORMATION_SEED = 5
REVIEW_TEMPLATE_MAX_ROWS = 120

SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/tiff", "image/gif", "image/bmp", "image/webp"}
)


def prompts_fingerprint() -> str:
    """Stable digest of the zero-shot prompt configuration."""
    canonical = json.dumps(
        {name: list(prompts) for name, prompts in sorted(CLASS_PROMPTS.items())},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def config_snapshot() -> dict[str, Any]:
    """Serializable snapshot of every deterministic knob used by a run."""
    from dalel.pillars.multimodal_visual_evidence import P5_VERSION

    return {
        "p5_version": P5_VERSION,
        "scoring_config_version": P5_SCORING_CONFIG_VERSION,
        "classes": list(ALL_CLASSES),
        "meaningful_classes": list(MEANINGFUL_CLASSES),
        "supporting_classes": list(SUPPORTING_CLASSES),
        "map_like_classes": sorted(MAP_LIKE_CLASSES),
        "chart_table_classes": sorted(CHART_TABLE_CLASSES),
        "project_specific_classes": sorted(PROJECT_SPECIFIC_CLASSES),
        "class_prompts_sha256": prompts_fingerprint(),
        "model": {
            "name": MODEL_NAME,
            "pretrained_tag": MODEL_PRETRAINED_TAG,
            "license": MODEL_LICENSE,
            "device": MODEL_DEVICE,
            "embedding_dim": MODEL_EMBEDDING_DIM,
            "image_batch_size": MODEL_IMAGE_BATCH_SIZE,
            "text_batch_size": MODEL_TEXT_BATCH_SIZE,
            "softmax_temperature": SOFTMAX_TEMPERATURE,
            "similarity_decimals": SIMILARITY_DECIMALS,
        },
        "decision_thresholds": {
            "model_min_top_affinity": MODEL_MIN_TOP_AFFINITY,
            "model_min_margin": MODEL_MIN_MARGIN,
            "context_adjust_min_affinity": CONTEXT_ADJUST_MIN_AFFINITY,
            "context_adjust_top_k": CONTEXT_ADJUST_TOP_K,
            "relevance_low_similarity": RELEVANCE_LOW_SIMILARITY,
            "mismatch_min_affinity": MISMATCH_MIN_AFFINITY,
        },
        "exclusion": {
            "tiny_min_side_px": TINY_MIN_SIDE_PX,
            "tiny_min_area_px": TINY_MIN_AREA_PX,
            "uniform_max_extrema_span": UNIFORM_MAX_EXTREMA_SPAN,
            "uniform_max_stddev": UNIFORM_MAX_STDDEV,
            "dhash_algorithm": DHASH_ALGORITHM,
            "near_duplicate_max_distance": NEAR_DUPLICATE_MAX_DISTANCE,
            "near_duplicate_dim_tolerance": NEAR_DUPLICATE_DIM_TOLERANCE,
            "header_aspect_ratio": HEADER_ASPECT_RATIO,
            "header_min_occurrences": HEADER_MIN_OCCURRENCES,
            "logo_max_side_px": LOGO_MAX_SIDE_PX,
            "logo_min_documents": LOGO_MIN_DOCUMENTS,
        },
        "ocr": {
            "engine": OCR_ENGINE,
            "languages": list(OCR_LANGUAGES),
            "max_assets": OCR_MAX_ASSETS,
            "min_side_px": OCR_MIN_SIDE_PX,
            "min_mean_confidence": OCR_MIN_MEAN_CONFIDENCE,
            "text_max_chars": OCR_TEXT_MAX_CHARS,
        },
        "context": {
            "caption_patterns": list(CAPTION_PATTERNS),
            "figure_reference_pattern": FIGURE_REFERENCE_PATTERN,
            "missing_visual_min_references": MISSING_VISUAL_MIN_REFERENCES,
            "page_context_snippet_chars": PAGE_CONTEXT_SNIPPET_CHARS,
            "caption_min_chars": CAPTION_MIN_CHARS,
            "caption_class_hints": {k: list(v) for k, v in sorted(CAPTION_CLASS_HINTS.items())},
            "caption_compatible_classes": {
                k: sorted(v) for k, v in sorted(CAPTION_COMPATIBLE_CLASSES.items())
            },
            "entity_term_min_chars": ENTITY_TERM_MIN_CHARS,
            "entity_term_max_count": ENTITY_TERM_MAX_COUNT,
        },
        "checks": {
            "duplicate_inflation_min_members": DUPLICATE_INFLATION_MIN_MEMBERS,
            "map_cue_keywords": {k: list(v) for k, v in sorted(MAP_CUE_KEYWORDS.items())},
            "map_cue_min_ocr_tokens": MAP_CUE_MIN_OCR_TOKENS,
            "chart_cue_unit_keywords": list(CHART_CUE_UNIT_KEYWORDS),
        },
        "severity_points": dict(SEVERITY_POINTS),
        "score_cap": SCORE_CAP,
        "max_severity": MAX_SEVERITY,
        "finding_types": list(FINDING_TYPES),
        "finding_confidence": dict(sorted(FINDING_CONFIDENCE.items())),
        "confidence_bounds": [CONFIDENCE_MIN, CONFIDENCE_MAX],
        "confidence_penalties": dict(sorted(CONFIDENCE_PENALTIES.items())),
        "assessment_confidence_weights": dict(sorted(ASSESSMENT_CONFIDENCE_WEIGHTS.items())),
        "assessment_confidence_bounds": [
            ASSESSMENT_CONFIDENCE_MIN,
            ASSESSMENT_CONFIDENCE_MAX,
        ],
        "meta_integration_status": META_INTEGRATION_STATUS,
        "supported_media_types": sorted(SUPPORTED_MEDIA_TYPES),
        "honesty": {
            "llm_used": False,
            "vision_language_model_used": True,
            "model_proves_environmental_harm": False,
            "low_similarity_is_contradiction": False,
            "chart_digitization_attempted": False,
            "geospatial_analysis": False,
            "high_severity_possible": False,
        },
    }
