"""Service layer: normalize on-disk artifacts into stable API contracts.

All pillar-specific knowledge lives here. Routes stay thin. The frontend
never sees raw artifact shapes — only the normalized schemas. No response
produced here contains a filesystem path, secret or Python repr.
"""

from __future__ import annotations

from typing import Any

from dalel.api import API_VERSION
from dalel.api.config import RESERVED_PILLARS
from dalel.api.repository import ArtifactStore, PillarArtifacts
from dalel.api.schemas import (
    CoherenceDetail,
    ConflictingClaimRef,
    DocumentInfo,
    EntityRef,
    EvidenceItem,
    FilterOption,
    FindingDetail,
    FindingFilters,
    FindingListItem,
    FindingsPage,
    MetricItem,
    PillarSummary,
    ProjectDetail,
    ProjectListItem,
    ProjectSummary,
    QuantitativeDetail,
    ReportResponse,
    RequirementRef,
    ReservedPillar,
    SeverityCounts,
    SystemMetrics,
)

# --- constants ---------------------------------------------------------------

DEMO_CORPUS_NOTICE = (
    "Демонстрационный нормативный корпус. Не является официальным источником права."
)
REVIEW_NOTICE = (
    "Потенциальное замечание для экспертной проверки. Не является"
    " административным или юридическим выводом."
)
P3_EMPTY_STATE = "Доказанных числовых противоречий не обнаружено."
P3_EXCLUSION_NOTE = "Сравнения с недостаточным контекстом были исключены из выводов."
P4_EMPTY_STATE = "Доказанных междокументных противоречий не обнаружено."
P4_EXCLUSION_NOTE = (
    "Сопоставления с недостаточной идентичностью или контекстом были исключены из выводов."
)
INTEGRATED_RISK_NOTE = (
    "Интегральный риск — следующий этап. Сейчас сводная оценка не рассчитывается."
)

# Presentation-only project display names (not legal entity identities).
_PROJECT_NAMES = {
    "project_001_bereke": "Bereke",
    "project_002_azm": "AZM",
    "project_003_bayterek": "Bayterek",
    "project_004_sintez_ural": "Sintez Ural",
}

_INDUSTRY_LABELS = {
    "food_production": "Пищевое производство",
    "metal_manufacturing": "Металлообработка",
    "construction_materials": "Стройматериалы",
    "chemical_manufacturing": "Химическое производство",
}

_DOCUMENT_TYPE_LABELS = {
    "ndv": "Проект НДВ",
    "pek": "Программа ПЭК",
    "puo": "Программа управления отходами",
    "action_plan": "План мероприятий",
    "nontechnical_summary": "Нетехническое резюме",
    "roos": "ОВОС / раздел ООС",
    "explanatory_note": "Пояснительная записка",
    "working_project_note": "Записка рабочего проекта",
}

_FINDING_TYPE_LABELS = {
    # P1
    "missing_document": "Отсутствует документ",
    "missing_expected_section": "Отсутствует ожидаемый раздел",
    "empty_page": "Пустая страница",
    "low_text_coverage": "Низкое покрытие текстом",
    "high_ocr_dependency": "Высокая зависимость от OCR",
    "missing_expected_tables": "Отсутствуют ожидаемые таблицы",
    "duplicate_heading": "Повтор заголовка",
    "suspicious_document_length": "Нетипичный объём документа",
    "metadata_inconsistency": "Несогласованность метаданных",
    "date_range_inconsistency": "Несогласованность дат",
    "missing_appendix_reference": "Ссылка на отсутствующее приложение",
    "structural_anomaly": "Структурная аномалия",
    # P2
    "missing_required_document": "Не найден требуемый документ",
    "missing_required_section": "Не найден требуемый раздел",
    "potential_regulatory_conflict": "Потенциальное противоречие требованию",
    "insufficient_regulatory_evidence": "Недостаточно свидетельств выполнения",
    "applicability_uncertain": "Применимость не установлена",
    "outdated_or_unknown_regulation_version": "Версия нормы неизвестна",
    "non_authoritative_demo_requirement": "Демонстрационный корпус (не право)",
    "malformed_regulatory_source": "Некорректный источник требования",
    # P3
    "direct_value_conflict": "Прямое расхождение значений",
    "equivalent_unit_conflict": "Расхождение в эквивалентных единицах",
    "aggregate_total_mismatch": "Несходящийся итог таблицы",
    "percentage_mismatch": "Расхождение процентов",
    "bound_violation": "Выход за границу норматива",
    "range_inversion": "Инверсия диапазона",
    "impossible_value": "Невозможное значение",
    "ambiguous_numeric_format": "Неоднозначный числовой формат",
    "insufficient_context": "Недостаточный контекст",
    "unsupported_conversion": "Неподдерживаемое преобразование",
    # P4
    "conflicting_project_identity": "Противоречие идентичности проекта",
    "conflicting_facility_identity": "Противоречие идентичности объекта",
    "conflicting_location": "Противоречие местоположения",
    "conflicting_activity_or_category": "Противоречие вида деятельности",
    "conflicting_reporting_period": "Противоречие отчётного периода",
    "conflicting_operator": "Противоречие идентификатора оператора",
    "unresolved_entity_identity": "Идентичность не разрешена",
    "insufficient_cross_document_context": "Недостаточно контекста для сравнения",
    "orphan_document_reference": "Ссылка на отсутствующий документ",
}

# P4 finding types that assert a PROVEN cross-document incompatibility (vs a
# diagnostic about missing linkage). Drives the honest empty state.
_P4_CONFLICT_TYPES = frozenset(
    {
        "conflicting_project_identity",
        "conflicting_facility_identity",
        "conflicting_location",
        "conflicting_activity_or_category",
        "conflicting_reporting_period",
        "conflicting_operator",
    }
)

_P4_ENTITY_TYPE_LABELS = {
    "organization": "Организация",
    "reporting_period": "Отчётный период",
    "administrative_location": "Местоположение",
    "activity": "Деятельность",
    "emission_source": "Источник выброса",
    "facility": "Объект",
    "project": "Проект",
    "document": "Документ",
}

_P4_ROLE_LABELS = {"operator": "оператор", "designer": "разработчик", "unknown": "—"}

_P4_RELATION_LABELS = {
    "project_contains_document": "содержит документ",
    "document_identifies_operator": "указывает оператора",
    "document_names_designer": "называет разработчика",
    "document_names_organization": "упоминает организацию",
    "document_covers_period": "охватывает период",
    "document_states_location": "указывает адрес",
    "document_describes_activity": "описывает деятельность",
    "document_describes_emission_source": "описывает источник выброса",
    "project_located_in": "расположен в регионе",
    "project_performs_activity": "вид деятельности",
}

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


# --- small helpers -----------------------------------------------------------


def project_display_name(project_id: str) -> str:
    if project_id in _PROJECT_NAMES:
        return _PROJECT_NAMES[project_id]
    slug = project_id.split("_", 2)[-1] if project_id.startswith("project_") else project_id
    return slug.replace("_", " ").title()


def industry_label(value: str | None) -> str | None:
    if value is None:
        return None
    return _INDUSTRY_LABELS.get(value, value.replace("_", " "))


def document_type_label(value: str | None) -> str | None:
    if value is None:
        return None
    return _DOCUMENT_TYPE_LABELS.get(value, value)


def finding_type_label(value: str) -> str:
    return _FINDING_TYPE_LABELS.get(value, value.replace("_", " "))


def _severity_counts(findings: list[dict[str, Any]]) -> SeverityCounts:
    counts = SeverityCounts()
    for finding in findings:
        severity = str(finding.get("severity", "info"))
        if severity == "high":
            counts.high += 1
        elif severity == "medium":
            counts.medium += 1
        elif severity == "low":
            counts.low += 1
        else:
            counts.info += 1
    return counts


def _score_for(pillar: PillarArtifacts, project_id: str) -> int | None:
    record = pillar.project_scores.get(project_id)
    if record is None:
        return None
    value = record.get(pillar.descriptor.score_field)
    return int(value) if value is not None else None


# --- pillar summary ----------------------------------------------------------


def _pillar_status(available: bool, counts: SeverityCounts) -> str:
    if not available:
        return "unavailable"
    if counts.total == 0:
        return "clear"
    if counts.high or counts.medium or counts.low:
        return "attention"
    return "info"


def _pillar_metrics(
    store: ArtifactStore, pillar: PillarArtifacts, project_id: str, counts: SeverityCounts
) -> list[MetricItem]:
    key = pillar.descriptor.key
    if key == "p1":
        docs = len(store.project_documents(project_id))
        return [
            MetricItem(label="Документов в пакете", value=str(docs)),
            MetricItem(label="Замечаний", value=str(counts.total)),
            MetricItem(
                label="Средних / низких / инфо",
                value=f"{counts.medium} / {counts.low} / {counts.info}",
            ),
        ]
    if key == "p2":
        assessments = pillar.assessments_by_project.get(project_id, [])
        by_label: dict[str, int] = {}
        for assessment in assessments:
            label = str(assessment.get("label"))
            by_label[label] = by_label.get(label, 0) + 1
        return [
            MetricItem(label="Проверок требований", value=str(len(assessments))),
            MetricItem(
                label="Подтверждено свидетельствами",
                value=str(by_label.get("supported_by_evidence", 0)),
            ),
            MetricItem(
                label="Потенциальных замечаний",
                value=str(by_label.get("potential_conflict", 0)),
            ),
            MetricItem(
                label="Недостаточно свидетельств",
                value=str(by_label.get("insufficient_evidence", 0)),
                hint="Требует экспертной проверки",
            ),
        ]
    if key == "p3":
        stats = pillar.p3_project_stats.get(project_id, {})
        return [
            MetricItem(label="Числовых упоминаний", value=str(stats.get("mentions", 0))),
            MetricItem(
                label="Проверок итогов таблиц",
                value=f"{stats.get('aggregation_consistent', 0)} / "
                f"{stats.get('aggregation_checks', 0)} сошлись",
            ),
            MetricItem(
                label="Сравнений выполнено",
                value=str(stats.get("comparisons_compared", 0)),
            ),
            MetricItem(
                label="Исключено по контексту",
                value=str(stats.get("comparisons_suppressed", 0)),
                hint=P3_EXCLUSION_NOTE,
            ),
        ]
    if key == "p4":
        score = pillar.project_scores.get(project_id, {})
        return [
            MetricItem(label="Сущностей графа", value=str(score.get("entity_count", 0))),
            MetricItem(
                label="Связанных документов",
                value=str(score.get("linked_document_count", 0)),
                hint="Подтверждённые межкументные связи (общий БИН/название/период)",
            ),
            MetricItem(label="Связей в графе", value=str(score.get("edge_count", 0))),
            MetricItem(
                label="Исключено сравнений",
                value=str(score.get("suppressed_comparison_count", 0)),
                hint=P4_EXCLUSION_NOTE,
            ),
        ]
    return []


def _pillar_headline(pillar: PillarArtifacts, counts: SeverityCounts, available: bool) -> str:
    key = pillar.descriptor.key
    if not available:
        return "Артефакты пиллара недоступны"
    if key == "p3":
        if counts.total == 0:
            return P3_EMPTY_STATE
        return f"{counts.total} потенциальных числовых замечаний"
    if key == "p2":
        if counts.total == 0:
            return "Демонстрационный корпус · замечаний не выявлено"
        return f"Демонстрационный корпус · {counts.total} замечаний на проверку"
    if counts.total == 0:
        return "Структурных замечаний не выявлено"
    return f"{counts.total} структурных замечаний ({counts.medium} средних)"


def _pillar_empty_state(pillar: PillarArtifacts, counts: SeverityCounts) -> str | None:
    if counts.total > 0:
        return None
    if pillar.descriptor.key == "p3":
        return f"{P3_EMPTY_STATE} {P3_EXCLUSION_NOTE}"
    if pillar.descriptor.key == "p2":
        return "Замечаний по демонстрационному корпусу не выявлено."
    return "Структурных замечаний не выявлено."


def build_pillar_summary(
    store: ArtifactStore, pillar: PillarArtifacts, project_id: str
) -> PillarSummary:
    descriptor = pillar.descriptor
    project_findings = [
        finding for finding in pillar.findings if str(finding.get("project_id")) == project_id
    ]
    counts = _severity_counts(project_findings)
    status = _pillar_status(pillar.available, counts)
    warning = DEMO_CORPUS_NOTICE if descriptor.is_demo else None
    limitations = None
    if descriptor.key == "p2":
        limitations = (
            "Оценки основаны на синтетическом демонстрационном корпусе и"
            " требуют экспертной проверки; выводы о соответствии"
            " законодательству не делаются."
        )
    elif descriptor.key == "p3":
        limitations = (
            "Отсутствие доказанных противоречий не подтверждает"
            " корректность документов; часть сравнений исключена из-за"
            " недостаточного контекста."
        )
    elif descriptor.key == "p1":
        limitations = (
            "Наблюдения о структуре документов, а не административные"
            " выводы; формулировки заголовков и OCR-шум влияют на полноту."
        )
    elif descriptor.key == "p4":
        limitations = (
            "Конфликт поднимается только из явного несовместимого"
            " идентификатора; различия написания и транслитерации — алиасы, а"
            " не противоречия. Отсутствие доказанных противоречий не"
            " подтверждает корректность документов."
        )

    headline = _pillar_headline(pillar, counts, pillar.available)
    empty_state = _pillar_empty_state(pillar, counts)

    # P4-specific fields (only when the pillar is available).
    p4_fields: dict[str, object] = {}
    if descriptor.key == "p4" and pillar.available:
        proven = sum(
            1 for f in project_findings if str(f.get("finding_type")) in _P4_CONFLICT_TYPES
        )
        headline = _p4_headline(counts.total, proven)
        empty_state = f"{P4_EMPTY_STATE} {P4_EXCLUSION_NOTE}" if proven == 0 else None
        score = pillar.project_scores.get(project_id, {})
        p4_fields = {
            "entity_count": int(score.get("entity_count", 0)),
            "edge_count": int(score.get("edge_count", 0)),
            "linked_document_count": int(score.get("linked_document_count", 0)),
            "unresolved_entity_count": int(score.get("unresolved_entity_count", 0)),
            "suppressed_comparison_count": int(score.get("suppressed_comparison_count", 0)),
            "graph": _p4_graph_summary(store, pillar, project_id, proven),
        }

    return PillarSummary(
        pillar_id=descriptor.pillar_id,
        key=descriptor.key,
        title=descriptor.title,
        short_title=descriptor.short_title,
        description=descriptor.description,
        status=status,
        available=pillar.available,
        implemented=descriptor.implemented,
        is_demo=descriptor.is_demo,
        is_authoritative=descriptor.is_authoritative,
        finding_count=counts.total,
        severity_counts=counts,
        score=_score_for(pillar, project_id),
        score_label=descriptor.score_label,
        headline=headline,
        empty_state=empty_state,
        warning=warning,
        limitations=limitations,
        metrics=_pillar_metrics(store, pillar, project_id, counts),
        **p4_fields,  # type: ignore[arg-type]
    )


def _p4_headline(total: int, proven: int) -> str:
    if proven > 0:
        return f"{proven} потенциальных междокументных расхождений на проверку"
    diagnostics = total
    if diagnostics == 0:
        return "Межкументные связи подтверждены · противоречий не обнаружено"
    return f"Противоречий не обнаружено · {diagnostics} диагностик для ориентира"


def _p4_document_label(store: ArtifactStore, document_id: str) -> str:
    document = store.document(document_id)
    if document is None:
        return document_id
    return document_type_label(str(document["document_type"])) or document_id


def _p4_entity_label(store: ArtifactStore, entity: dict[str, Any]) -> str:
    entity_type = str(entity.get("entity_type"))
    if entity_type == "document":
        return _p4_document_label(store, str(entity.get("canonical_label")))
    if entity_type == "project":
        return project_display_name(str(entity.get("canonical_label")))
    return str(entity.get("canonical_label"))


def _p4_graph_summary(
    store: ArtifactStore, pillar: PillarArtifacts, project_id: str, proven: int
) -> dict[str, object]:
    """Compact, provenance-preserving cross-document coherence view for the
    frontend: notable entities, relationships, confirmed links, unresolved
    identities and suppressed comparisons. No graph library required."""
    entities = pillar.p4_entities_by_project.get(project_id, [])
    edges = pillar.p4_edges_by_project.get(project_id, [])
    decisions = pillar.p4_resolution_by_project.get(project_id, [])
    suppressed = pillar.p4_suppressed_by_project.get(project_id, [])
    by_id = {str(e["entity_id"]): e for e in entities}

    entities_by_type: dict[str, int] = {}
    for entity in entities:
        entity_type = str(entity["entity_type"])
        entities_by_type[entity_type] = entities_by_type.get(entity_type, 0) + 1

    # Notable entities exclude structural (project/document) and bulk
    # (emission_source) nodes; those are summarized by count instead.
    notable = [
        {
            "entity_id": str(e["entity_id"]),
            "entity_type": str(e["entity_type"]),
            "entity_type_label": _P4_ENTITY_TYPE_LABELS.get(
                str(e["entity_type"]), str(e["entity_type"])
            ),
            "label": _p4_entity_label(store, e),
            "role": e.get("role"),
            "role_label": _P4_ROLE_LABELS.get(str(e.get("role"))) if e.get("role") else None,
            "identifiers": list(e.get("identifiers") or []),
            "aliases": list(e.get("aliases") or []),
            "document_count": len(e.get("source_document_ids") or []),
            "confidence": e.get("confidence"),
        }
        for e in entities
        if str(e["entity_type"]) not in ("project", "document", "emission_source")
    ]
    notable.sort(key=lambda e: (e["entity_type"], str(e["label"])))

    relationships = []
    for edge in edges:
        relation = str(edge["relation"])
        if relation in ("project_contains_document", "document_describes_emission_source"):
            continue  # structural / bulk — omitted from the compact table
        source = by_id.get(str(edge["source_entity_id"]))
        target = by_id.get(str(edge["target_entity_id"]))
        if source is None or target is None:
            continue
        relationships.append(
            {
                "relation": relation,
                "relation_label": _P4_RELATION_LABELS.get(relation, relation),
                "source_label": _p4_entity_label(store, source),
                "target_label": _p4_entity_label(store, target),
                "target_type": str(target["entity_type"]),
                "document_ids": list(edge.get("source_document_ids") or []),
            }
        )
    relationships.sort(key=lambda r: (str(r["relation"]), str(r["source_label"])))

    confirmed_links = [
        {
            "entity_type": str(d["entity_type"]),
            "entity_type_label": _P4_ENTITY_TYPE_LABELS.get(
                str(d["entity_type"]), str(d["entity_type"])
            ),
            "signal": str(d["signal"]),
            "reason": str(d["reason"]),
            "confidence": d.get("confidence"),
        }
        for d in decisions
        if d.get("decision") == "merged"
    ]
    unresolved_links = [
        {
            "entity_type": str(d["entity_type"]),
            "reason": str(d["reason"]),
        }
        for d in decisions
        if d.get("decision") == "unresolved"
    ]
    suppressed_summary: dict[str, dict[str, Any]] = {}
    for item in suppressed:
        reason = str(item["reason"])
        bucket = suppressed_summary.setdefault(reason, {"reason": reason, "count": 0, "detail": ""})
        bucket["count"] = int(bucket["count"]) + 1
        if not bucket["detail"] and item.get("detail"):
            bucket["detail"] = str(item["detail"])

    return {
        "proven_conflicts": proven,
        "entities_by_type": dict(sorted(entities_by_type.items())),
        "emission_source_count": entities_by_type.get("emission_source", 0),
        "notable_entities": notable,
        "relationships": relationships,
        "confirmed_links": confirmed_links,
        "unresolved_links": unresolved_links,
        "suppressed": sorted(suppressed_summary.values(), key=lambda s: str(s["reason"])),
    }


# --- projects ----------------------------------------------------------------


def build_project_list_item(store: ArtifactStore, project: dict[str, Any]) -> ProjectListItem:
    project_id = str(project["project_id"])
    findings = [finding for _, finding in store.project_findings(project_id)]
    pillar_counts: dict[str, int] = {}
    for pillar_key, pillar in store.pillars.items():
        pillar_counts[pillar_key] = sum(
            1 for finding in pillar.findings if str(finding.get("project_id")) == project_id
        )
    return ProjectListItem(
        project_id=project_id,
        name=project_display_name(project_id),
        region=project.get("region"),
        industry=industry_label(project.get("industry")),
        document_count=len(store.project_documents(project_id)),
        findings_total=len(findings),
        severity_counts=_severity_counts(findings),
        pillar_finding_counts=pillar_counts,
        has_demo_pillar=any(p.descriptor.is_demo for p in store.pillars.values()),
        dataset_version=store.dataset_version,
    )


def build_project_detail(store: ArtifactStore, project: dict[str, Any]) -> ProjectDetail:
    project_id = str(project["project_id"])
    documents = []
    for document in store.project_documents(project_id):
        document_id = str(document["document_id"])
        doc_findings = [
            finding
            for _, finding in store.project_findings(project_id)
            if str(finding.get("document_id")) == document_id
        ]
        documents.append(
            DocumentInfo(
                document_id=document_id,
                document_type=str(document["document_type"]),
                page_count=document.get("page_count"),
                languages=list(document.get("languages") or []),
                document_mode=document.get("document_mode"),
                source_url=document.get("source_url"),
                finding_counts=_severity_counts(doc_findings),
            )
        )
    findings = [finding for _, finding in store.project_findings(project_id)]
    return ProjectDetail(
        project_id=project_id,
        name=project_display_name(project_id),
        region=project.get("region"),
        industry=industry_label(project.get("industry")),
        source_url=project.get("source_url"),
        dataset_version=store.dataset_version,
        document_count=len(documents),
        documents=documents,
        findings_total=len(findings),
        severity_counts=_severity_counts(findings),
    )


def build_project_summary(store: ArtifactStore, project: dict[str, Any]) -> ProjectSummary:
    project_id = str(project["project_id"])
    pillars = [build_pillar_summary(store, store.pillars[key], project_id) for key in store.pillars]
    findings = [finding for _, finding in store.project_findings(project_id)]
    reserved = [
        ReservedPillar(
            pillar_id=item["pillar_id"],
            key=item["key"],
            title=item["title"],
            description=item["description"],
        )
        for item in RESERVED_PILLARS
    ]
    return ProjectSummary(
        project_id=project_id,
        name=project_display_name(project_id),
        region=project.get("region"),
        industry=industry_label(project.get("industry")),
        document_count=len(store.project_documents(project_id)),
        findings_total=len(findings),
        severity_counts=_severity_counts(findings),
        pillars=pillars,
        reserved_pillars=reserved,
        integrated_risk_available=False,
        integrated_risk_note=INTEGRATED_RISK_NOTE,
    )


# --- findings ----------------------------------------------------------------


# Finding types that are demo-corpus notices by construction (they carry no
# per-requirement flags because they are corpus-level, not requirement-level).
_DEMO_NOTICE_TYPES = frozenset({"non_authoritative_demo_requirement"})


def finding_demo_state(
    pillar: PillarArtifacts, finding: dict[str, Any]
) -> tuple[bool, bool | None]:
    """Robust demo/legal-safety normalization for a finding.

    Returns ``(is_demo, is_authoritative)``. Demo state is NOT inferred from
    a single nested requirement field — corpus-level notice findings
    (``non_authoritative_demo_requirement``) carry no ``requirement_demo_only``
    yet are demo by definition. Signals, in order:

    1. an explicit per-finding ``requirement_demo_only`` flag when present;
    2. a corpus-level demo-notice finding type;
    3. otherwise, whether the pillar's corpus is demo-only
       (``metrics.corpus_demo_only``) under a demo pillar.

    ``is_authoritative`` is ``False`` for any demo finding, mirrors the
    finding's explicit flag when present, and is ``None`` for non-regulatory
    pillars (P1/P3) where the concept does not apply.
    """
    if not pillar.descriptor.is_demo and pillar.descriptor.is_authoritative:
        # Non-regulatory pillar (P1/P3): authoritative flag is not meaningful.
        explicit = finding.get("requirement_demo_only")
        return (bool(explicit), None)

    demo_only = finding.get("requirement_demo_only")
    corpus_demo_only = bool(pillar.metrics.get("corpus_demo_only", pillar.descriptor.is_demo))
    is_demo = (
        bool(demo_only)
        if demo_only is not None
        else (str(finding.get("finding_type")) in _DEMO_NOTICE_TYPES or corpus_demo_only)
    )

    explicit_auth = finding.get("requirement_is_authoritative")
    if is_demo:
        is_authoritative: bool | None = False
    elif explicit_auth is not None:
        is_authoritative = bool(explicit_auth)
    else:
        is_authoritative = pillar.descriptor.is_authoritative
    return (is_demo, is_authoritative)


def _finding_list_item(
    store: ArtifactStore, pillar: PillarArtifacts, finding: dict[str, Any]
) -> FindingListItem:
    document_id = finding.get("document_id")
    document = store.document(str(document_id)) if document_id else None
    is_demo, is_authoritative = finding_demo_state(pillar, finding)
    return FindingListItem(
        finding_id=str(finding["finding_id"]),
        pillar_id=pillar.descriptor.pillar_id,
        pillar_key=pillar.descriptor.key,
        project_id=str(finding["project_id"]),
        document_id=str(document_id) if document_id else None,
        document_type=str(document["document_type"]) if document else None,
        finding_type=str(finding["finding_type"]),
        finding_type_label=finding_type_label(str(finding["finding_type"])),
        severity=str(finding.get("severity", "info")),
        confidence=finding.get("confidence"),
        title=str(finding.get("title", "")),
        rule_id=finding.get("rule_id"),
        review_status=str(finding.get("review_status", "pending")),
        page_references=list(finding.get("page_references") or []),
        is_demo=is_demo,
        is_authoritative=is_authoritative,
        inference_label=finding.get("inference_label"),
        requirement_id=finding.get("requirement_id"),
    )


def _sort_key(item: FindingListItem) -> tuple[int, str, str, str]:
    return (
        _SEVERITY_ORDER.get(item.severity, 9),
        item.pillar_key,
        item.document_id or "~",
        item.finding_id,
    )


def _project_finding_items(store: ArtifactStore, project_id: str) -> list[FindingListItem]:
    items = [
        _finding_list_item(store, pillar, finding)
        for pillar, finding in store.project_findings(project_id)
    ]
    items.sort(key=_sort_key)
    return items


def build_findings_page(
    store: ArtifactStore,
    project_id: str,
    *,
    pillar: str | None = None,
    severity: str | None = None,
    finding_type: str | None = None,
    document_id: str | None = None,
    search: str | None = None,
) -> FindingsPage:
    all_items = _project_finding_items(store, project_id)
    filters = _build_filters(store, all_items)

    filtered = all_items
    if pillar:
        filtered = [i for i in filtered if i.pillar_key == pillar.lower()]
    if severity:
        filtered = [i for i in filtered if i.severity == severity.lower()]
    if finding_type:
        filtered = [i for i in filtered if i.finding_type == finding_type]
    if document_id:
        filtered = [i for i in filtered if i.document_id == document_id]
    if search:
        needle = search.strip().lower()
        filtered = [
            i
            for i in filtered
            if needle in i.title.lower()
            or needle in i.finding_type_label.lower()
            or needle in (i.finding_type or "").lower()
        ]

    counts = SeverityCounts()
    for item in filtered:
        setattr(counts, item.severity, getattr(counts, item.severity, 0) + 1)

    return FindingsPage(
        project_id=project_id,
        total=len(all_items),
        returned=len(filtered),
        severity_counts=counts,
        available_filters=filters,
        findings=filtered,
    )


def implemented_pillar_keys(store: ArtifactStore) -> list[str]:
    """The stable, findings-independent list of selectable pillar filters:
    every available, implemented pillar (P1/P2/P3) — never derived from
    which pillars happen to have findings, so P3 stays selectable at zero
    findings. Roadmap pillars (P4/META) are not in ``store.pillars`` and are
    never selectable as finding filters."""
    return [
        key
        for key, pillar in store.pillars.items()
        if pillar.available and pillar.descriptor.implemented
    ]


def _build_filters(store: ArtifactStore, items: list[FindingListItem]) -> FindingFilters:
    type_counts: dict[str, int] = {}
    doc_counts: dict[str, int] = {}
    severities: set[str] = set()
    for item in items:
        type_counts[item.finding_type] = type_counts.get(item.finding_type, 0) + 1
        severities.add(item.severity)
        if item.document_id:
            doc_counts[item.document_id] = doc_counts.get(item.document_id, 0) + 1

    type_options = [
        FilterOption(value=value, label=finding_type_label(value), count=count)
        for value, count in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    doc_options = []
    for doc_id, count in sorted(doc_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        document = store.document(doc_id)
        label = document_type_label(document["document_type"]) if document else doc_id
        doc_options.append(FilterOption(value=doc_id, label=str(label), count=count))

    return FindingFilters(
        pillars=implemented_pillar_keys(store),
        severities=[s for s in ("high", "medium", "low", "info") if s in severities],
        finding_types=type_options,
        documents=doc_options,
    )


def _requirement_ref(pillar: PillarArtifacts, requirement_id: str | None) -> RequirementRef | None:
    if not requirement_id:
        return None
    record = pillar.requirements.get(requirement_id)
    if record is None:
        return None
    return RequirementRef(
        requirement_id=str(record["requirement_id"]),
        title=str(record.get("title", "")),
        requirement_text=str(record.get("requirement_text", "")),
        document_title=str(record.get("document_title", "")),
        article=record.get("article"),
        obligation_type=str(record.get("obligation_type", "other")),
        is_authoritative=bool(record.get("is_authoritative", False)),
        demo_only=bool(record.get("demo_only", True)),
        source_url=record.get("source_url"),
    )


def _evidence_items(
    store: ArtifactStore, finding: dict[str, Any], assessment: dict[str, Any] | None
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    seen: set[tuple[str | None, int | None, str | None]] = set()

    def _add(raw: dict[str, Any]) -> None:
        document_id = raw.get("document_id")
        document = store.document(str(document_id)) if document_id else None
        quote = raw.get("quote")
        note = raw.get("note")
        key = (str(document_id) if document_id else None, raw.get("page_number"), quote)
        if key in seen:
            return
        seen.add(key)
        is_empty = (
            quote is None
            and note is None
            and document_id is None
            and raw.get("page_number") is None
        )
        if is_empty:
            return
        items.append(
            EvidenceItem(
                document_id=str(document_id) if document_id else None,
                document_type=str(document["document_type"]) if document else None,
                page_number=raw.get("page_number"),
                section_id=raw.get("section_id"),
                quote=quote,
                note=note,
            )
        )

    for raw in finding.get("evidence") or []:
        _add(raw)
    if assessment is not None:
        for raw in assessment.get("evidence_snippets") or []:
            _add(raw)
    return items


def build_finding_detail(
    store: ArtifactStore, pillar: PillarArtifacts, finding: dict[str, Any]
) -> FindingDetail:
    base = _finding_list_item(store, pillar, finding)
    assessment = None
    requirement = None
    missing_information: list[str] = []
    applicability = None
    retrieval_score = finding.get("retrieval_score")
    inference_engine = finding.get("inference_engine")
    if pillar.descriptor.key == "p2":
        assessment_id = finding.get("assessment_id")
        assessment = pillar.assessments.get(str(assessment_id)) if assessment_id else None
        requirement = _requirement_ref(pillar, finding.get("requirement_id"))
        if assessment is not None:
            missing_information = list(assessment.get("missing_information") or [])
            applicability = assessment.get("applicability")

    evidence = _evidence_items(store, finding, assessment)
    demo_warning = DEMO_CORPUS_NOTICE if base.is_demo else None
    coherence = _coherence_detail(store, pillar, finding) if pillar.descriptor.key == "p4" else None

    return FindingDetail(
        **base.model_dump(),
        explanation=str(finding.get("explanation", "")),
        observed_value=finding.get("observed_value"),
        expected_value=finding.get("expected_value"),
        limitations=finding.get("limitations"),
        evidence=evidence,
        missing_information=missing_information,
        applicability=applicability,
        retrieval_score=retrieval_score,
        inference_engine=inference_engine,
        requirement=requirement,
        quantitative=_quantitative_detail(finding),
        coherence=coherence,
        demo_warning=demo_warning,
        review_notice=REVIEW_NOTICE,
    )


def _coherence_detail(
    store: ArtifactStore, pillar: PillarArtifacts, finding: dict[str, Any]
) -> CoherenceDetail | None:
    """P4 finding context: referenced entities and the conflicting claims that
    back an evidence-based mismatch."""
    entity_ids = list(finding.get("entity_ids") or [])
    conflicting = finding.get("conflicting_claims") or []
    if not entity_ids and not conflicting:
        return None
    entities: list[EntityRef] = []
    for entity_id in entity_ids:
        record = pillar.p4_entities_by_id.get(str(entity_id))
        if record is None:
            continue
        entities.append(
            EntityRef(
                entity_id=str(record["entity_id"]),
                entity_type=str(record["entity_type"]),
                label=str(record.get("canonical_label", "")),
                role=record.get("role"),
                identifiers=list(record.get("identifiers") or []),
            )
        )
    conflicting_claims = []
    for claim in conflicting:
        document = (
            store.document(str(claim.get("document_id"))) if claim.get("document_id") else None
        )
        conflicting_claims.append(
            ConflictingClaimRef(
                document_id=str(claim.get("document_id", "")),
                document_type=str(document["document_type"]) if document else None,
                attribute=str(claim.get("attribute", "")),
                raw_value=str(claim.get("raw_value", "")),
                normalized_value=str(claim.get("normalized_value", "")),
            )
        )
    return CoherenceDetail(entities=entities, conflicting_claims=conflicting_claims)


def _quantitative_detail(finding: dict[str, Any]) -> QuantitativeDetail | None:
    comparison = finding.get("comparison")
    if not isinstance(comparison, dict):
        return None
    conversions = comparison.get("conversions") or []
    return QuantitativeDetail(
        formula=comparison.get("formula"),
        raw_values=[str(c.get("raw")) for c in conversions if c.get("raw") is not None],
        normalized_values=[
            str(c.get("canonical_value"))
            for c in conversions
            if c.get("canonical_value") is not None
        ],
        canonical_unit=comparison.get("canonical_unit"),
    )


def find_finding(
    store: ArtifactStore, project_id: str, finding_id: str
) -> tuple[PillarArtifacts, dict[str, Any]] | None:
    for pillar, finding in store.project_findings(project_id):
        if str(finding["finding_id"]) == finding_id:
            return pillar, finding
    return None


# --- reports -----------------------------------------------------------------


def build_report(store: ArtifactStore, project: dict[str, Any], pillar_key: str) -> ReportResponse:
    pillar = store.pillars[pillar_key]
    project_id = str(project["project_id"])
    summary = build_pillar_summary(store, pillar, project_id)
    lines = [
        f"# {summary.title} — {project_display_name(project_id)}",
        "",
        f"_{REVIEW_NOTICE}_",
        "",
    ]
    if summary.warning:
        lines += [f"> **{summary.warning}**", ""]
    lines += [
        "## Сводка",
        "",
        f"- Статус: {summary.headline}",
        f"- Замечаний: {summary.finding_count}"
        f" (высоких {summary.severity_counts.high},"
        f" средних {summary.severity_counts.medium},"
        f" низких {summary.severity_counts.low},"
        f" инфо {summary.severity_counts.info})",
    ]
    if summary.score is not None:
        lines.append(f"- {summary.score_label}: {summary.score} / {summary.score_max}")
    lines.append("")
    for metric in summary.metrics:
        lines.append(f"- {metric.label}: {metric.value}")
    lines.append("")

    findings = [
        _finding_list_item(store, pillar, finding)
        for finding in pillar.findings
        if str(finding.get("project_id")) == project_id
    ]
    findings.sort(key=_sort_key)
    if findings:
        lines += ["## Замечания", ""]
        for item in findings:
            document = document_type_label(item.document_type) or "пакет"
            lines.append(f"- **[{item.severity}]** {item.title} — {document}")
    elif summary.empty_state:
        lines += ["## Замечания", "", summary.empty_state]
    lines.append("")
    if summary.limitations:
        lines += ["## Ограничения", "", summary.limitations, ""]

    return ReportResponse(
        project_id=project_id,
        pillar=pillar_key,
        title=f"{summary.title} — {project_display_name(project_id)}",
        format="markdown",
        content="\n".join(lines),
        is_demo=summary.is_demo,
        generated_note=(
            "Сводка сформирована из принятых артефактов анализа для удобства демонстрации."
        ),
    )


# --- system ------------------------------------------------------------------


def build_system_metrics(store: ArtifactStore) -> SystemMetrics:
    findings_by_pillar = {key: len(pillar.findings) for key, pillar in store.pillars.items()}
    all_findings = [finding for _, finding in store.all_findings()]
    pillar_infos: list[dict[str, object]] = []
    for key, pillar in store.pillars.items():
        pillar_infos.append(
            {
                "pillar_id": pillar.descriptor.pillar_id,
                "key": key,
                "title": pillar.descriptor.title,
                "available": pillar.available,
                "is_demo": pillar.descriptor.is_demo,
                "is_authoritative": pillar.descriptor.is_authoritative,
                "finding_count": len(pillar.findings),
            }
        )
    return SystemMetrics(
        api_version=API_VERSION,
        dataset_version=store.dataset_version,
        dataset_fingerprint=store.dataset_fingerprint,
        projects=len(store.projects),
        documents=len(store.documents_by_id),
        findings_total=len(all_findings),
        findings_by_pillar=findings_by_pillar,
        severity_counts=_severity_counts(all_findings),
        pillars=pillar_infos,
    )


def build_project_list(store: ArtifactStore) -> list[ProjectListItem]:
    return [
        build_project_list_item(store, project)
        for project in sorted(store.projects, key=lambda p: str(p["project_id"]))
    ]
