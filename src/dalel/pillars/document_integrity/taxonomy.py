"""Versioned taxonomy of EXPECTED STRUCTURAL SECTIONS per document type.

Wording is deliberate: these are *expected structural sections* observed in
Kazakhstan environmental-permit documentation practice — NOT legal
requirements. No rule asserts legal bindingness without a normative citation;
the baseline never produces "violation" claims, only review candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "1.0.0"

_COMMON_LIMITATION = (
    "Expected structural section, not a legal requirement; heading wording"
    " varies between developers and OCR noise may hide a present section."
)


@dataclass(frozen=True)
class SectionRule:
    rule_id: str
    document_type: str
    canonical_section: str
    aliases_ru: tuple[str, ...]
    aliases_kk: tuple[str, ...] = ()
    required: bool = True  # required => finding severity medium; recommended => low
    severity: str = "medium"
    rationale: str = ""
    limitations: str = _COMMON_LIMITATION


@dataclass(frozen=True)
class PackageProfile:
    profile_id: str
    description: str
    trigger_types: frozenset[str]
    required_types: tuple[str, ...]
    recommended_types: tuple[str, ...]
    limitations: str


def _rule(
    rule_id: str,
    document_type: str,
    canonical: str,
    ru: tuple[str, ...],
    kk: tuple[str, ...] = (),
    required: bool = True,
    rationale: str = "",
) -> SectionRule:
    return SectionRule(
        rule_id=rule_id,
        document_type=document_type,
        canonical_section=canonical,
        aliases_ru=ru,
        aliases_kk=kk,
        required=required,
        severity="medium" if required else "low",
        rationale=rationale
        or (
            "Раздел стабильно присутствует в структуре документов данного типа"
            " в отобранном корпусе и типовой практике оформления."
        ),
    )


SECTION_RULES: dict[str, list[SectionRule]] = {
    "ndv": [
        _rule("NDV-S01", "ndv", "введение", ("введение", "общие положения"), ("кіріспе",)),
        _rule(
            "NDV-S02",
            "ndv",
            "общие сведения о предприятии",
            (
                "общие сведения о предприятии",
                "сведения о предприятии",
                "краткая характеристика предприятия",
            ),
            ("кәсіпорын туралы жалпы мәліметтер",),
        ),
        _rule(
            "NDV-S03",
            "ndv",
            "инвентаризация источников выбросов",
            (
                "инвентаризация источников",
                "характеристика источников выбросов",
                "источники выбросов загрязняющих веществ",
            ),
        ),
        _rule(
            "NDV-S04",
            "ndv",
            "расчёт рассеивания / нормативов выбросов",
            (
                "расчет рассеивания",
                "расчеты рассеивания",
                "расчет нормативов",
                "нормативы допустимых выбросов",
                "предложения по нормативам",
            ),
        ),
        _rule(
            "NDV-S05",
            "ndv",
            "санитарно-защитная зона",
            ("санитарно защитная зона", "сзз"),
            required=False,
        ),
        _rule(
            "NDV-S06",
            "ndv",
            "мероприятия при НМУ",
            (
                "мероприятия при неблагоприятных метеорологических условиях",
                "нму",
                "период неблагоприятных метеорологических условий",
            ),
            required=False,
        ),
        _rule(
            "NDV-S07",
            "ndv",
            "контроль за соблюдением нормативов",
            (
                "контроль за соблюдением нормативов",
                "производственный контроль",
                "контроль нормативов выбросов",
            ),
            required=False,
        ),
    ],
    "pek": [
        _rule(
            "PEK-S01",
            "pek",
            "общие сведения",
            ("общие сведения", "введение", "общие данные"),
            ("жалпы мәліметтер", "кіріспе"),
        ),
        _rule(
            "PEK-S02",
            "pek",
            "производственный контроль атмосферного воздуха",
            (
                "контроль атмосферного воздуха",
                "мониторинг атмосферного воздуха",
                "эмиссии в атмосферу",
            ),
        ),
        _rule(
            "PEK-S03",
            "pek",
            "контроль обращения с отходами",
            ("контроль отходов", "обращение с отходами", "мониторинг отходов"),
            required=False,
        ),
        _rule(
            "PEK-S04",
            "pek",
            "периодичность контроля",
            (
                "периодичность контроля",
                "график контроля",
                "периодичность наблюдений",
                "план график",
            ),
        ),
        _rule(
            "PEK-S05",
            "pek",
            "отчётность",
            ("отчетность", "предоставление отчетности", "порядок отчетности"),
            required=False,
        ),
    ],
    "puo": [
        _rule(
            "PUO-S01",
            "puo",
            "общие сведения",
            ("общие сведения", "введение"),
            ("жалпы мәліметтер", "кіріспе"),
        ),
        _rule(
            "PUO-S02",
            "puo",
            "сведения об образующихся отходах",
            ("сведения об отходах", "виды отходов", "перечень отходов", "образование отходов"),
        ),
        _rule(
            "PUO-S03",
            "puo",
            "накопление и хранение отходов",
            ("накопление отходов", "хранение отходов", "места накопления"),
        ),
        _rule(
            "PUO-S04",
            "puo",
            "передача / переработка отходов",
            ("передача отходов", "утилизация", "переработка отходов", "удаление отходов"),
            required=False,
        ),
    ],
    "ovvos": [
        _rule(
            "OVVOS-S01",
            "ovvos",
            "описание намечаемой деятельности",
            ("описание намечаемой деятельности", "общие сведения о проекте"),
        ),
        _rule(
            "OVVOS-S02",
            "ovvos",
            "оценка воздействия на атмосферный воздух",
            ("воздействие на атмосферный воздух", "оценка воздействия на атмосферу"),
        ),
        _rule(
            "OVVOS-S03",
            "ovvos",
            "оценка воздействия на водные ресурсы",
            ("воздействие на водные ресурсы", "воздействие на поверхностные и подземные воды"),
            required=False,
        ),
        _rule(
            "OVVOS-S04",
            "ovvos",
            "мероприятия по охране окружающей среды",
            ("мероприятия по охране окружающей среды", "природоохранные мероприятия"),
        ),
    ],
    "roos": [
        _rule(
            "ROOS-S01",
            "roos",
            "общие сведения / описание проекта",
            (
                "общие сведения",
                "введение",
                "краткая характеристика проекта",
                "описание проектируемого объекта",
            ),
            ("жалпы мәліметтер", "кіріспе"),
        ),
        _rule(
            "ROOS-S02",
            "roos",
            "охрана атмосферного воздуха",
            (
                "охрана атмосферного воздуха",
                "воздействие на атмосферный воздух",
                "мероприятия по охране атмосферного воздуха",
            ),
        ),
        _rule(
            "ROOS-S03",
            "roos",
            "охрана водных ресурсов",
            (
                "охрана водных ресурсов",
                "охрана поверхностных и подземных вод",
                "водопотребление и водоотведение",
            ),
            required=False,
        ),
        _rule(
            "ROOS-S04",
            "roos",
            "обращение с отходами",
            (
                "отходы производства",
                "обращение с отходами",
                "охрана окружающей среды при обращении с отходами",
            ),
        ),
        _rule(
            "ROOS-S05",
            "roos",
            "шумовое воздействие",
            ("шум", "шумовое воздействие", "защита от шума", "акустическое воздействие"),
            required=False,
        ),
    ],
    "action_plan": [
        _rule(
            "AP-S01",
            "action_plan",
            "перечень мероприятий",
            (
                "план мероприятий",
                "перечень мероприятий",
                "мероприятия по охране окружающей среды",
                "наименование мероприятия",
            ),
            ("іс шаралар жоспары",),
            rationale=(
                "План мероприятий по определению содержит перечень мероприятий (обычно таблицей)."
            ),
        ),
        _rule(
            "AP-S02",
            "action_plan",
            "сроки выполнения",
            ("срок выполнения", "сроки реализации", "период выполнения"),
            required=False,
        ),
    ],
    "nontechnical_summary": [
        _rule(
            "NTS-S01",
            "nontechnical_summary",
            "краткое описание проекта",
            ("нетехническое резюме", "краткое описание", "общие сведения", "резюме"),
            ("техникалық емес түйіндеме",),
        ),
        _rule(
            "NTS-S02",
            "nontechnical_summary",
            "основные выводы",
            ("выводы", "заключение", "основные результаты"),
            ("қорытынды",),
            required=False,
        ),
    ],
    "explanatory_note": [
        _rule(
            "EN-S01",
            "explanatory_note",
            "общие сведения",
            ("общие сведения", "введение", "общая часть"),
            ("жалпы мәліметтер", "кіріспе"),
        ),
        _rule(
            "EN-S02",
            "explanatory_note",
            "технические решения",
            (
                "технические решения",
                "технологические решения",
                "генеральный план",
                "архитектурно строительные решения",
            ),
            required=False,
        ),
    ],
    "working_project_note": [
        _rule(
            "WPN-S01",
            "working_project_note",
            "общие сведения",
            ("общие сведения", "введение", "общая часть"),
            ("жалпы мәліметтер", "кіріспе"),
        ),
        _rule(
            "WPN-S02",
            "working_project_note",
            "технологические решения",
            (
                "технологические решения",
                "технология производства",
                "описание технологического процесса",
            ),
            required=False,
        ),
        _rule(
            "WPN-S03",
            "working_project_note",
            "охрана окружающей среды",
            ("охрана окружающей среды", "мероприятия по охране окружающей среды"),
            required=False,
        ),
    ],
}


PACKAGE_PROFILES: tuple[PackageProfile, ...] = (
    PackageProfile(
        profile_id="permit_package",
        description=(
            "Пакет заявки на экологическое разрешение: НДВ + ПЭК + ПУО + план"
            " мероприятий; нетехническое резюме обычно прилагается."
        ),
        trigger_types=frozenset({"ndv", "pek", "puo"}),
        required_types=("ndv", "pek", "puo", "action_plan"),
        recommended_types=("nontechnical_summary",),
        limitations=(
            "Ожидаемый состав пакета выведен из практики портала общественных"
            " слушаний; юридическая комплектность не утверждается."
        ),
    ),
    PackageProfile(
        profile_id="construction_eia",
        description=(
            "Пакет строительного проекта: пояснительная записка + раздел РООС;"
            " протоколы/заключения приходят позже и не входят в pre-review пакет."
        ),
        trigger_types=frozenset({"roos", "explanatory_note"}),
        required_types=("explanatory_note", "roos"),
        recommended_types=(),
        limitations=(
            "Профиль выбирается по фактическому составу; отсутствие ОВОС может"
            " быть законным в зависимости от категории объекта."
        ),
    ),
)


def infer_package_profile(document_types: set[str]) -> PackageProfile:
    """Deterministic profile inference by best trigger overlap."""
    best = PACKAGE_PROFILES[0]
    best_overlap = -1
    for profile in PACKAGE_PROFILES:
        overlap = len(profile.trigger_types & document_types)
        if overlap > best_overlap:
            best, best_overlap = profile, overlap
    return best


def taxonomy_as_dict() -> dict[str, object]:
    """Serializable taxonomy snapshot for config_snapshot.json."""
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "wording": "expected structural section (not a legal requirement)",
        "section_rules": {
            document_type: [
                {
                    "rule_id": rule.rule_id,
                    "canonical_section": rule.canonical_section,
                    "aliases_ru": list(rule.aliases_ru),
                    "aliases_kk": list(rule.aliases_kk),
                    "required": rule.required,
                    "severity": rule.severity,
                    "rationale": rule.rationale,
                    "limitations": rule.limitations,
                }
                for rule in rules
            ]
            for document_type, rules in SECTION_RULES.items()
        },
        "package_profiles": [
            {
                "profile_id": profile.profile_id,
                "description": profile.description,
                "trigger_types": sorted(profile.trigger_types),
                "required_types": list(profile.required_types),
                "recommended_types": list(profile.recommended_types),
                "limitations": profile.limitations,
            }
            for profile in PACKAGE_PROFILES
        ],
    }
