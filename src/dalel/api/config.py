"""API configuration and the static pillar registry.

Nothing here contains secrets or absolute paths that reach a response.
The data directory is resolved from the repository layout (or the
``DALEL_DATA_DIR`` env override) and stays server-side only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    """Repository ``data/`` directory.

    ``src/dalel/api/config.py`` → repo root is three parents up from
    ``src/dalel`` (``.../src/dalel/api`` → ``.../``).
    """
    override = os.environ.get("DALEL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "data"


def _cors_origins() -> list[str]:
    raw = os.environ.get("DALEL_API_CORS_ORIGINS")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    # Local Next.js dev servers (default and common alternates).
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]


@dataclass(frozen=True)
class PillarDescriptor:
    """Static, presentation-level description of one analysis pillar.

    ``available`` is resolved at load time from whether the artifacts
    exist; everything else is stable metadata. Future pillars are added
    by appending descriptors — the API/frontend contract does not change.
    """

    pillar_id: str  # "P1" | "P2" | "P3" | future "P4"...
    key: str  # url-safe: "p1" | "p2" | "p3"
    results_subdir: str  # under data/results, e.g. "p1/v1"
    title: str
    short_title: str
    description: str
    score_field: str  # field name inside its project_scores record
    score_label: str
    is_demo: bool = False
    is_authoritative: bool = True
    implemented: bool = True


# Order here is the canonical display order.
PILLARS: tuple[PillarDescriptor, ...] = (
    PillarDescriptor(
        pillar_id="P1",
        key="p1",
        results_subdir="p1/v1",
        title="Целостность документов",
        short_title="Целостность",
        description=(
            "Проверка структурной полноты пакета и отдельных документов:"
            " ожидаемые разделы, пустые страницы, зависимость от OCR,"
            " дубликаты заголовков. Каждое наблюдение — приоритет для"
            " экспертной проверки, а не административный вывод."
        ),
        score_field="document_integrity_priority_score",
        score_label="Приоритет проверки структуры",
    ),
    PillarDescriptor(
        pillar_id="P2",
        key="p2",
        results_subdir="p2/v1",
        title="Регуляторное соответствие",
        short_title="Соответствие",
        description=(
            "Сопоставление документов проекта с требованиями нормативного"
            " корпуса на уровне отдельных требований. Демонстрационный"
            " режим: корпус синтетический и НЕ является официальным"
            " источником права."
        ),
        score_field="regulatory_compliance_priority_score",
        score_label="Приоритет регуляторной проверки",
        is_demo=True,
        is_authoritative=False,
    ),
    PillarDescriptor(
        pillar_id="P3",
        key="p3",
        results_subdir="p3/v1",
        title="Количественная согласованность",
        short_title="Согласованность",
        description=(
            "Детерминированный поиск потенциально противоречивых числовых"
            " утверждений (значения, единицы, итоги таблиц). Сравнения с"
            " недостаточным контекстом сознательно исключаются из выводов."
        ),
        score_field="quantitative_consistency_priority_score",
        score_label="Приоритет числовой проверки",
    ),
    PillarDescriptor(
        pillar_id="P4",
        key="p4",
        results_subdir="p4/v1",
        title="Междокументная согласованность",
        short_title="Междокументная",
        description=(
            "Сопоставляет сведения о проекте, объектах, местоположении,"
            " деятельности и периодах между документами. Конфликт поднимается"
            " только при явном несовместимом идентификаторе; различия написания"
            " и транслитерации считаются алиасами, а не противоречиями."
        ),
        score_field="cross_document_coherence_priority_score",
        score_label="Приоритет проверки согласованности",
    ),
)

# Reserved, NOT-YET-IMPLEMENTED pillars. Surfaced in the API/UI as
# roadmap items (available=false) so the contract already carries them.
# P4 has been implemented (Cross-Document Coherence) and moved into PILLARS
# above; spatial / cartographic / geospatial analysis belongs to the later
# P5/P6 phases, NOT to P4.
RESERVED_PILLARS: tuple[dict[str, str], ...] = (
    {
        "pillar_id": "P5",
        "key": "p5",
        "title": "Пространственный и картографический анализ",
        "description": "Геопривязка объектов и зон воздействия — следующий этап.",
    },
    {
        "pillar_id": "META",
        "key": "meta",
        "title": "Интегральная оценка риска",
        "description": (
            "Калиброванная сводная оценка на основе всех пилларов —"
            " следующий этап. Сейчас интегральный риск не рассчитывается."
        ),
    },
)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    cors_origins: list[str] = field(default_factory=_cors_origins)
    curated_subdir: str = "curated/v1"
    results_subdir: str = "results"

    @property
    def curated_dir(self) -> Path:
        return self.data_dir / self.curated_subdir

    @property
    def results_dir(self) -> Path:
        return self.data_dir / self.results_subdir


def get_settings() -> Settings:
    return Settings()
