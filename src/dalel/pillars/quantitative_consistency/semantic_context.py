"""Deterministic semantic context for quantitative mentions.

Controlled alias lexicons (RU/KK/EN) — no embeddings, no fuzzy similarity.
The context answers: WHAT metric, WHICH substance, WHICH emission source,
WHAT period, and WHICH qualifiers (planned/actual, gross/one-time, limit,
with/without treatment) a number belongs to. Missing context stays ``None``
and downgrades comparison eligibility instead of being guessed.
"""

from __future__ import annotations

import re

from dalel.pillars.quantitative_consistency.normalization import normalize_label

# --- metric groups --------------------------------------------------------------
# Phrase aliases are matched on normalized label text; longest phrase wins.
_METRIC_ALIASES: tuple[tuple[str, str], ...] = (
    ("выброс вещества", "emission"),
    ("выбросы загрязняющих веществ", "emission"),
    ("выброс загрязняющих веществ", "emission"),
    ("валовый выброс", "emission"),
    ("валовой выброс", "emission"),
    ("выбросов", "emission"),
    ("выбросы", "emission"),
    ("выброс", "emission"),
    ("эмиссия", "emission"),
    ("эмиссии", "emission"),
    ("шығарынды", "emission"),  # kk
    ("emission", "emission"),
    ("пдк", "concentration_limit"),
    ("обув", "concentration_limit"),
    ("концентрация", "concentration"),
    ("концентрации", "concentration"),
    ("приземная концентрация", "concentration"),
    ("concentration", "concentration"),
    ("образование отходов", "waste"),
    ("отходов", "waste"),
    ("отходы", "waste"),
    ("отход", "waste"),
    ("тко", "waste"),
    ("тбо", "waste"),
    ("қалдық", "waste"),  # kk
    ("waste", "waste"),
    ("водопотребление", "water_use"),
    ("водоотведение", "water_discharge"),
    ("сточные воды", "water_discharge"),
    ("сточных вод", "water_discharge"),
    ("водозабор", "water_use"),
    ("расход воды", "water_use"),
    ("су тұтыну", "water_use"),  # kk
    ("площадь", "area"),
    ("аумағы", "area"),  # kk
    ("area", "area"),
    ("производительность", "production"),
    ("мощность", "production"),
    ("объем производства", "production"),
    ("выпуск продукции", "production"),
    ("өнімділік", "production"),  # kk
)
_METRIC_ALIASES_SORTED = tuple(sorted(_METRIC_ALIASES, key=lambda item: (-len(item[0]), item[0])))

# --- substances -------------------------------------------------------------------
# canonical key -> alias phrases (normalized). Longest alias wins; CO aliases
# are longer than bare «углерод», so soot never swallows carbon monoxide.
_SUBSTANCES: dict[str, tuple[str, ...]] = {
    "no2": (
        "диоксид азота",
        "диоксида азота",
        "азота диоксид",
        "азота диоксида",
        "двуокись азота",
        "двуокиси азота",
        "азот 4 оксид",
        "no2",
    ),
    "no": ("оксид азота", "оксида азота", "азота оксид", "азота оксида", "азот 2 оксид", "no "),
    "nox": ("оксиды азота", "оксидов азота", "азота оксиды", "nox"),
    "so2": (
        "диоксид серы",
        "диоксида серы",
        "серы диоксид",
        "серы диоксида",
        "сернистый ангидрид",
        "сернистого ангидрида",
        "ангидрид сернистый",
        "сера диоксид",
        "so2",
    ),
    "co": (
        "оксид углерода",
        "оксида углерода",
        "углерода оксид",
        "углерода оксида",
        "окись углерода",
        "окиси углерода",
        "угарный газ",
        "углерод оксид",
        "co ",
    ),
    "soot": ("сажа", "сажи", "углерод черный", "углерод сажа"),
    "h2s": ("сероводород", "сероводорода", "h2s"),
    "nh3": ("аммиак", "аммиака", "nh3"),
    "ch4": ("метан", "метана", "ch4"),
    "benzapyrene": ("бенз а пирен", "бенз а пирена", "бензапирен", "бензапирена"),
    "formaldehyde": ("формальдегид", "формальдегида"),
    "suspended_solids": ("взвешенные вещества", "взвешенных веществ"),
    "hydrocarbons_c1_c5": ("углеводороды предельные с1 с5", "алканы с1 с5"),
    "hydrocarbons_c6_c10": ("углеводороды предельные с6 с10", "алканы с6 с10"),
    "hydrocarbons_c12_c19": ("углеводороды предельные с12 с19",),
    "hydrocarbons": ("углеводороды", "углеводородов"),
    "gasoline": ("бензин", "бензина"),
    "kerosene": ("керосин", "керосина"),
    "white_spirit": ("уайт спирит", "уайт спирита"),
    "coal_ash": ("зола углей", "зола угольная", "зола", "золы"),
    "hf": ("фтористый водород", "фтористого водорода", "фториды", "фтористые соединения"),
    "hcl": ("хлористый водород", "хлористого водорода", "соляная кислота", "соляной кислоты"),
    "h2so4": ("серная кислота", "серной кислоты"),
    "benzene": ("бензол", "бензола"),
    "toluene": ("толуол", "толуола"),
    "xylene": ("ксилол", "ксилола"),
    "phenol": ("фенол", "фенола"),
    "manganese": ("марганец и его соединения", "марганца оксиды", "марганца"),
    "iron_oxide": ("оксид железа", "оксида железа", "железа оксид"),
    "lead": ("свинец и его соединения", "свинец", "свинца"),
}
_SUBSTANCE_ALIASES_SORTED: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((alias, key) for key, aliases in _SUBSTANCES.items() for alias in aliases),
        key=lambda item: (-len(item[0]), item[0]),
    )
)

# Inorganic dust classes (KZ inventory codes 2907/2908/2909) need their SiO2
# share disambiguator: they are DIFFERENT substances.
_DUST_STEM = "пыль неорганическая"
_DUST_ABOVE_70_RE = re.compile(r"(?:выше|более|свыше)\s*70|70\s*100")
_DUST_BELOW_20_RE = re.compile(r"(?:до|менее|ниже)\s*20")
_DUST_20_70_RE = re.compile(r"70\s*20|20\s*70")

# KZ emission inventory codes for the frequent pollutants.
_CODE_MAP: dict[str, str] = {
    "0301": "no2",
    "0304": "no",
    "0328": "soot",
    "0330": "so2",
    "0333": "h2s",
    "0337": "co",
    "0303": "nh3",
    "0410": "ch4",
    "0703": "benzapyrene",
    "1325": "formaldehyde",
    "2902": "suspended_solids",
    "2704": "gasoline",
    "2732": "kerosene",
    "2752": "white_spirit",
    "2907": "dust_sio2_above_70",
    "2908": "dust_sio2_20_70",
    "2909": "dust_sio2_below_20",
    "3714": "coal_ash",
}

# --- qualifiers -------------------------------------------------------------------
_QUALIFIER_ALIASES: tuple[tuple[str, str], ...] = (
    ("максимально разовый", "max_onetime"),
    ("максимальный разовый", "max_onetime"),
    ("макс разовый", "max_onetime"),
    ("разовый", "max_onetime"),
    ("м р", "max_onetime"),
    ("валовый", "gross"),
    ("валовой", "gross"),
    ("годовой", "gross"),
    ("среднегодовой", "annual_mean"),
    ("средне суточная", "daily_mean"),
    ("среднесуточная", "daily_mean"),
    ("планируемый", "planned"),
    ("планируемые", "planned"),
    ("план", "planned"),
    ("проектный", "planned"),
    ("проектируемый", "planned"),
    ("намечаемый", "planned"),
    ("перспектива", "planned"),
    ("перспективу", "planned"),
    ("жоспарланған", "planned"),  # kk
    ("фактический", "actual"),
    ("фактические", "actual"),
    ("факт", "actual"),
    ("отчетный", "actual"),
    ("существующее положение", "actual"),
    ("нақты", "actual"),  # kk
    ("норматив", "limit"),
    ("нормативы", "limit"),
    ("пдв", "limit"),
    ("ндв", "limit"),
    ("лимит", "limit"),
    ("предельно допустимый", "limit"),
    ("допустимый", "limit"),
    ("разрешенный", "limit"),
    ("с учетом очистки", "with_treatment"),
    ("после очистки", "with_treatment"),
    ("без учета очистки", "without_treatment"),
    ("без очистки", "without_treatment"),
    ("до очистки", "without_treatment"),
    ("аварийный", "emergency"),
    ("аварийная", "emergency"),
    ("залповый", "emergency"),
    ("фоновая", "background"),
    ("фоновый", "background"),
    ("фон", "background"),
    ("накоплено", "accumulated"),
    ("накопленных", "accumulated"),
    ("образовано", "generated"),
    ("образование", "generated"),
)
_QUALIFIER_ALIASES_SORTED = tuple(
    sorted(_QUALIFIER_ALIASES, key=lambda item: (-len(item[0]), item[0]))
)

# --- scope: totals and subset rows ---------------------------------------------------
_TOTAL_PREFIXES = (
    "итого",
    "всего",
    "подытог",
    "сумма",
    "суммарно",
    "суммарный",
    "барлығы",
    "жиыны",
    "total",
)
_SUBSET_PREFIXES = ("в том числе", "из них", "оның ішінде", "including")

# NB: NFKC folds «№» into «No», so normalized labels carry «no6003».
# «источник выделения» uses a per-block LOCAL numbering scheme (001, 002…)
# incompatible with the ИЗА scheme — deliberately NOT matched.
_SOURCE_KEY_RE = re.compile(
    r"(?:источник[аиу]?(?:\s+(?:выбросов|загрязнения))?|ист(?:очн)?\.?)"
    r"\s*(?:№|no|n)?\s*(\d{2,4}(?:-\d{2,4})?)",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_QUARTER_RE = re.compile(r"(?<![\w])(i{1,3}v?|iv|[1-4])\s*квартал", re.IGNORECASE)


def classify_metric(text: str) -> str | None:
    """Metric group of a normalized label, longest declared phrase wins."""
    label = normalize_label(text)
    if not label:
        return None
    padded = f" {label} "
    for alias, group in _METRIC_ALIASES_SORTED:
        if f" {alias} " in padded or padded.strip().startswith(alias):
            return group
    return None


def extract_substance(text: str) -> str | None:
    """Canonical substance key from a label, or None."""
    label = normalize_label(text)
    if not label:
        return None
    if _DUST_STEM in label:
        if _DUST_ABOVE_70_RE.search(label):
            return "dust_sio2_above_70"
        if _DUST_20_70_RE.search(label):
            return "dust_sio2_20_70"
        if _DUST_BELOW_20_RE.search(label):
            return "dust_sio2_below_20"
        return "dust_inorganic"
    padded = f" {label} "
    for alias, key in _SUBSTANCE_ALIASES_SORTED:
        needle = alias if alias.endswith(" ") else f"{alias} "
        if f" {needle}" in padded or padded.strip() == alias.strip():
            return key
    return None


def substance_from_code(code: str) -> str | None:
    """Substance key from a KZ inventory code cell (e.g. «0301»).

    Unmapped codes still yield a stable identity (``code_NNNN``) so that
    equal codes match each other without any name lexicon.
    """
    digits = code.strip()
    if not re.fullmatch(r"\d{3,4}", digits):
        return None
    padded = digits.zfill(4)
    return _CODE_MAP.get(padded, f"code_{padded}")


def extract_qualifiers(text: str) -> frozenset[str]:
    label = normalize_label(text)
    if not label:
        return frozenset()
    padded = f" {label} "
    tags = {tag for alias, tag in _QUALIFIER_ALIASES_SORTED if f" {alias} " in padded}
    return frozenset(tags)


def extract_period(text: str) -> str | None:
    """Period key from years/quarters in a label («на 2025-2034 годы»)."""
    label = normalize_label(text)
    if not label:
        return None
    years = sorted({int(y) for y in _YEAR_RE.findall(label)})
    quarter_match = _QUARTER_RE.search(label)
    parts: list[str] = []
    if years:
        parts.append("y" + "_".join(str(y) for y in years))
    if quarter_match:
        raw = quarter_match.group(1).casefold()
        roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
        parts.append(f"q{roman.get(raw, raw)}")
    return "-".join(parts) if parts else None


def extract_source_key(text: str) -> str | None:
    """Emission-source identity («источник № 6001») from a label."""
    match = _SOURCE_KEY_RE.search(normalize_label(text))
    if match:
        return match.group(1)
    return None


# Sub-entity identity INSIDE a source: release points («источник выделения
# N 6001 05, Автоматическая сварка …») and calculation operations
# («РАСЧЕТ выбросов ЗВ от сварки металлов»).
_RELEASE_POINT_RE = re.compile(
    r"источник[аиу]?\s+выделения\s*(?:№|no|n)?[:\s]*((?:\d+[\s\-]?)+)",
    re.IGNORECASE,
)
_OPERATION_RE = re.compile(
    r"расчет\s+выбросов(?:\s+зв)?\s+(?:от|при)\s+(.{3,60})",
    re.IGNORECASE,
)


def extract_sub_entity(text: str) -> str | None:
    """Release-point / operation identity from a heading, or None."""
    label = normalize_label(text)
    if not label:
        return None
    match = _RELEASE_POINT_RE.search(label)
    if match:
        digits = re.sub(r"[\s\-]+", "-", match.group(1).strip()).strip("-")
        return f"rp:{digits}"
    match = _OPERATION_RE.search(label)
    if match:
        operation = " ".join(match.group(1).split()[:4])
        return f"op:{operation}"
    return None


def is_total_label(text: str) -> bool:
    label = normalize_label(text)
    return any(label.startswith(prefix) for prefix in _TOTAL_PREFIXES)


def is_subset_label(text: str) -> bool:
    label = normalize_label(text)
    return any(label.startswith(prefix) for prefix in _SUBSET_PREFIXES)


def lexicon_snapshot() -> dict[str, object]:
    """Deterministic dump for config_snapshot.json."""
    return {
        "metric_aliases": {alias: group for alias, group in sorted(_METRIC_ALIASES)},
        "substance_aliases": {key: sorted(aliases) for key, aliases in sorted(_SUBSTANCES.items())},
        "substance_codes": dict(sorted(_CODE_MAP.items())),
        "qualifier_aliases": {alias: tag for alias, tag in sorted(_QUALIFIER_ALIASES)},
        "total_prefixes": sorted(_TOTAL_PREFIXES),
        "subset_prefixes": sorted(_SUBSET_PREFIXES),
        "dust_disambiguation": "sio2 share classes 2907/2908/2909 kept distinct",
    }
