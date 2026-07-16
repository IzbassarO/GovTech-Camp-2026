"""Cross-document coherence checks (A–E) plus deliberate suppression.

Conservative by construction: a check raises a finding ONLY from an explicit
incompatible identifier or an explicit incompatible structured value across
positively-matched entities and scope. Everything uncertain (free-text
addresses, document-internal facility numbering, differing document purposes)
is recorded as a suppressed comparison, never guessed into a conflict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dalel.pillars.cross_document_coherence.config import (
    ACTIVITY_CATEGORY_ALIASES,
    LOCATION_REGION_TOKENS,
    REPORTING_INSTANCE_DOC_TYPES,
)
from dalel.pillars.cross_document_coherence.entity_resolution import OperatorResolution
from dalel.pillars.cross_document_coherence.schemas import (
    ConflictingClaim,
    EntityClaim,
    P4Evidence,
    P4FindingRecord,
    PackageCheck,
    SuppressedComparison,
    deterministic_id,
)
from dalel.pillars.cross_document_coherence.scoring import (
    cap_severity,
    finding_confidence,
    points_for,
)

# Cautious, review-oriented Russian phrasing (never asserts falsity).
_POTENTIAL = "Обнаружено потенциальное расхождение"
_NEEDS_REVIEW = "Требует экспертной проверки."
_INSUFFICIENT = "Недостаточно контекста для сравнения"


@dataclass
class CheckResult:
    findings: list[P4FindingRecord] = field(default_factory=list)
    suppressed: list[SuppressedComparison] = field(default_factory=list)


def run_checks(
    claims: list[EntityClaim],
    operator_by_project: dict[str, OperatorResolution],
    projects_by_id: dict[str, dict[str, Any]],
    documents: list[dict[str, Any]],
) -> CheckResult:
    result = CheckResult()
    claim_index = {c.claim_id: c for c in claims}
    claims_by_project: dict[str, list[EntityClaim]] = {}
    for claim in claims:
        claims_by_project.setdefault(claim.project_id, []).append(claim)
    docs_by_project: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        docs_by_project.setdefault(str(document["project_id"]), []).append(document)
    doctype_by_id = {str(d["document_id"]): str(d["document_type"]) for d in documents}

    for project_id in sorted(projects_by_id):
        project_claims = claims_by_project.get(project_id, [])
        project_docs = docs_by_project.get(project_id, [])
        project_document_ids = sorted(str(d["document_id"]) for d in project_docs)
        _check_identity(
            result,
            project_id,
            operator_by_project.get(project_id),
            claim_index,
            project_document_ids,
            doctype_by_id,
        )
        _check_reporting_period(result, project_id, project_claims, doctype_by_id)
        _check_location(result, project_id, project_claims)
        _check_facility(result, project_id, project_claims)
        _check_activity(
            result, project_id, project_claims, doctype_by_id, operator_by_project.get(project_id)
        )

    result.findings.sort(
        key=lambda f: (f.project_id, f.document_id or "~", f.finding_type, f.finding_id)
    )
    result.suppressed.sort(key=lambda s: (s.project_id, s.check, s.suppression_id))
    return result


# --- evidence / finding helpers ---------------------------------------------


def _evidence(claim: EntityClaim) -> P4Evidence:
    prov = claim.provenance
    return P4Evidence(
        document_id=prov.document_id,
        document_type=prov.document_type,
        page_number=prov.page_number,
        section_id=prov.section_id,
        quote=claim.raw_value,
        note=None,
    )


def _pages(claims: list[EntityClaim]) -> list[int]:
    return sorted(
        {c.provenance.page_number for c in claims if c.provenance.page_number is not None}
    )


def _flags(claims: list[EntityClaim]) -> list[str]:
    flags: set[str] = set()
    for claim in claims:
        flags.update(claim.quality_flags)
    return sorted(flags)


def _make_finding(
    project_id: str,
    finding_type: str,
    severity: str,
    rule_id: str,
    title: str,
    explanation: str,
    *,
    document_id: str | None = None,
    evidence_claims: list[EntityClaim] | None = None,
    conflicting_claims: list[ConflictingClaim] | None = None,
    entity_ids: list[str] | None = None,
    package_check: PackageCheck | None = None,
    evidence_override: list[P4Evidence] | None = None,
    observed_value: str | None = None,
    expected_value: str | None = None,
    limitations: str,
) -> P4FindingRecord:
    evidence_claims = evidence_claims or []
    flags = _flags(evidence_claims)
    severity = cap_severity(severity)
    confidence, factors = finding_confidence(finding_type, flags)
    claim_ids = sorted({c.claim_id for c in evidence_claims})
    evidence = (
        evidence_override
        if evidence_override is not None
        else [_evidence(c) for c in evidence_claims]
    )
    # Content-derived finding id. Package-level absence findings (no claim/entity
    # references) derive their id from the STRUCTURED package check — the
    # inspected document set — so tampering that set breaks the id (Blocker C).
    if claim_ids:
        key = "|".join(claim_ids)
    elif entity_ids:
        key = "|".join(sorted(entity_ids))
    elif package_check is not None:
        key = f"{package_check.check}@" + "|".join(package_check.inspected_document_ids)
    else:
        key = ""
    finding_id = deterministic_id("P4", project_id, finding_type, document_id or "", key)
    return P4FindingRecord(
        finding_id=finding_id,
        project_id=project_id,
        document_id=document_id,
        finding_type=finding_type,
        severity=severity,
        priority_score=points_for(severity),
        confidence=confidence,
        confidence_factors=factors,
        rule_id=rule_id,
        title=title,
        explanation=explanation,
        evidence=evidence,
        page_references=_pages(evidence_claims),
        entity_ids=sorted(entity_ids or []),
        claim_ids=claim_ids,
        conflicting_claims=conflicting_claims or [],
        package_check=package_check,
        observed_value=observed_value,
        expected_value=expected_value,
        quality_flags=flags,
        limitations=limitations,
    )


def _conflicting(claim: EntityClaim) -> ConflictingClaim:
    return ConflictingClaim(
        claim_id=claim.claim_id,
        document_id=claim.provenance.document_id or "",
        attribute=claim.attribute,
        raw_value=claim.raw_value,
        normalized_value=claim.normalized_value,
    )


def _suppress(
    result: CheckResult,
    project_id: str,
    check: str,
    attribute: str,
    reason: str,
    claim_ids: list[str],
    detail: str = "",
    entity_ids: list[str] | None = None,
) -> None:
    suppression_id = deterministic_id(
        "P4S", project_id, check, attribute, reason, "|".join(sorted(claim_ids))
    )
    result.suppressed.append(
        SuppressedComparison(
            suppression_id=suppression_id,
            project_id=project_id,
            check=check,
            attribute=attribute,
            reason=reason,
            entity_ids=sorted(entity_ids or []),
            claim_ids=sorted(claim_ids),
            detail=detail,
        )
    )


# --- Check A: project / operator identity -----------------------------------

# Structured operator-identity package check (Blocker C): deterministic labels
# so an absence finding is auditable from structured fields, never a fabricated
# quote. The builders below are pure functions of the structured inputs and are
# reproduced verbatim by the validator's replay.
OPERATOR_CHECK = "operator_identity"
OPERATOR_CHECKED_ATTRIBUTES = ["bin", "operator_name"]


def operator_absence_explanation(inspected_ids: list[str]) -> str:
    return (
        f"{_INSUFFICIENT}: среди проверенных документов пакета"
        f" ({', '.join(inspected_ids)}) не найдено квалифицирующих утверждений об"
        " операторе (явное наименование предприятия или БИН), поэтому"
        f" межкументную идентичность оператора установить нельзя. {_NEEDS_REVIEW}"
        " P4 не утверждает, что оператор отсутствует, — только что его"
        " идентичность не выводится из принятых документов."
    )


def operator_absence_note(document_id: str, document_type: str | None) -> str:
    return (
        f"Проверен документ {document_type or document_id}: явных признаков"
        " оператора (наименование предприятия, БИН) не обнаружено."
    )


def _check_identity(
    result: CheckResult,
    project_id: str,
    operator: OperatorResolution | None,
    claim_index: dict[str, EntityClaim],
    project_document_ids: list[str],
    doctype_by_id: dict[str, str],
) -> None:
    if operator is None or operator.status.startswith("confirmed"):
        return  # confirmed identity → graph evidence + resolution decision only
    if operator.status == "conflicting_identifier":
        # one representative BIN claim per distinct explicit BIN
        rep_claims = [claim_index[ids[0]] for _, ids in sorted(operator.bin_claim_ids.items())]
        same_name = len(operator.name_claim_ids) == 1
        severity = "medium" if same_name else "low"
        result.findings.append(
            _make_finding(
                project_id,
                "conflicting_operator",
                severity,
                "P4-A-IDENTIFIER",
                "Разные идентификаторы оператора в документах пакета",
                f"{_POTENTIAL}: документы пакета указывают разные явные"
                f" идентификаторы (БИН) оператора: {', '.join(operator.bins)}."
                f" {_NEEDS_REVIEW} P4 не делает вывода о том, какой из них верен.",
                evidence_claims=rep_claims,
                conflicting_claims=[_conflicting(c) for c in rep_claims],
                entity_ids=operator.operator_entity_ids,
                observed_value=", ".join(operator.bins),
                expected_value="единый БИН оператора",
                limitations="Сравниваются только явные идентификаторы; вывод о"
                " корректности не делается.",
            )
        )
    elif operator.status == "unresolved_names" and len(operator.document_ids) >= 2:
        rep_claims = [claim_index[ids[0]] for _, ids in sorted(operator.name_claim_ids.items())]
        result.findings.append(
            _make_finding(
                project_id,
                "unresolved_entity_identity",
                "info",
                "P4-A-UNRESOLVED",
                "Идентичность оператора между документами не установлена",
                f"{_INSUFFICIENT}: документы называют разных операторов, и общий"
                " явный идентификатор (БИН) их не связывает. Это диагностика для"
                f" ориентира эксперта, а не вывод о противоречии. {_NEEDS_REVIEW}",
                evidence_claims=rep_claims,
                conflicting_claims=[_conflicting(c) for c in rep_claims],
                entity_ids=operator.operator_entity_ids,
                limitations="Различие названий без общего идентификатора — не"
                " противоречие; идентичность остаётся неразрешённой.",
            )
        )
    elif operator.status == "absent" and len(project_document_ids) >= 2:
        inspected = sorted(project_document_ids)
        package_check = PackageCheck(
            check=OPERATOR_CHECK,
            entity_type="organization",
            role="operator",
            checked_attributes=sorted(OPERATOR_CHECKED_ATTRIBUTES),
            inspected_document_ids=inspected,
            qualifying_claims_found=0,
        )
        evidence = [
            P4Evidence(
                document_id=doc_id,
                document_type=doctype_by_id.get(doc_id),
                note=operator_absence_note(doc_id, doctype_by_id.get(doc_id)),
            )
            for doc_id in inspected
        ]
        result.findings.append(
            _make_finding(
                project_id,
                "insufficient_cross_document_context",
                "info",
                "P4-A-ABSENT",
                "Оператор не идентифицирован в документах пакета",
                operator_absence_explanation(inspected),
                package_check=package_check,
                evidence_override=evidence,
                observed_value="0",
                expected_value="≥1 явное утверждение об операторе (наименование или БИН)",
                limitations="Отсутствие идентификации не означает отсутствие"
                " оператора — проверены только ведущие разделы принятых документов;"
                " P4 не делает вывода о существовании оператора.",
            )
        )


# --- Check E: reporting period ----------------------------------------------


def _check_reporting_period(
    result: CheckResult,
    project_id: str,
    project_claims: list[EntityClaim],
    doctype_by_id: dict[str, str],
) -> None:
    period_claims = [
        c
        for c in project_claims
        if c.candidate_entity_type == "reporting_period" and c.attribute == "reporting_period"
    ]
    core: dict[str, list[EntityClaim]] = {}
    non_core: list[EntityClaim] = []
    for claim in period_claims:
        document_id = claim.provenance.document_id or ""
        if doctype_by_id.get(document_id) in REPORTING_INSTANCE_DOC_TYPES:
            core.setdefault(claim.normalized_value, []).append(claim)
        else:
            non_core.append(claim)

    core_docs = {c.provenance.document_id for group in core.values() for c in group}
    if len(core) >= 2 and len(core_docs) >= 2:
        rep_claims = [
            sorted(group, key=lambda c: c.claim_id)[0] for _, group in sorted(core.items())
        ]
        periods = sorted(core)
        result.findings.append(
            _make_finding(
                project_id,
                "conflicting_reporting_period",
                "low",
                "P4-E-PERIOD",
                "Разные отчётные периоды среди документов одного пакета",
                f"{_POTENTIAL}: документы одного отчётного пакета указывают разные"
                f" явные периоды: {', '.join(periods)}. {_NEEDS_REVIEW}",
                evidence_claims=rep_claims,
                conflicting_claims=[_conflicting(c) for c in rep_claims],
                observed_value=", ".join(periods),
                expected_value="единый отчётный период пакета",
                limitations="Сравниваются только явные периоды документов одной"
                " отчётной инстанции; различие назначения документов исключается.",
            )
        )
    # suppress cross-purpose period comparisons
    if non_core and core:
        _suppress(
            result,
            project_id,
            "reporting_period",
            "reporting_period",
            "different_document_purpose",
            [c.claim_id for c in non_core],
            "Периоды проектных/строительных документов не сравниваются с периодами"
            " разрешительного пакета.",
        )


# --- Check C: location -------------------------------------------------------


def _detect_oblast(normalized_address: str) -> str | None:
    matches = {
        oblast for token, oblast in LOCATION_REGION_TOKENS.items() if token in normalized_address
    }
    if len(matches) == 1:
        return next(iter(matches))
    return None  # unknown or ambiguous → not comparable


def _check_location(
    result: CheckResult,
    project_id: str,
    project_claims: list[EntityClaim],
) -> None:
    address_claims = [
        c
        for c in project_claims
        if c.candidate_entity_type == "administrative_location" and c.attribute == "address"
    ]
    if not address_claims:
        return
    by_oblast: dict[str, list[EntityClaim]] = {}
    unknown: list[EntityClaim] = []
    for claim in address_claims:
        oblast = _detect_oblast(claim.normalized_value)
        if oblast is None:
            unknown.append(claim)
        else:
            by_oblast.setdefault(oblast, []).append(claim)

    oblast_docs = {
        oblast: {c.provenance.document_id for c in group} for oblast, group in by_oblast.items()
    }
    if len(by_oblast) >= 2 and sum(len(v) for v in oblast_docs.values()) >= 2:
        rep_claims = [
            sorted(group, key=lambda c: c.claim_id)[0] for _, group in sorted(by_oblast.items())
        ]
        oblasts = sorted(by_oblast)
        result.findings.append(
            _make_finding(
                project_id,
                "conflicting_location",
                "low",
                "P4-C-OBLAST",
                "Разные административные регионы в адресах документов",
                f"{_POTENTIAL}: адреса в документах пакета называют разные"
                f" распознанные области: {', '.join(oblasts)}. {_NEEDS_REVIEW}",
                evidence_claims=rep_claims,
                conflicting_claims=[_conflicting(c) for c in rep_claims],
                observed_value=", ".join(oblasts),
                expected_value="единый регион пакета",
                limitations="Сравниваются только явно распознанные области;"
                " города, частичные и нераспознанные адреса исключаются.",
            )
        )
    if unknown:
        _suppress(
            result,
            project_id,
            "location",
            "address",
            "free_text_address_scope_uncertain",
            [c.claim_id for c in unknown],
            "Свободный текст адреса без распознанной области — идентичность"
            " местоположения не сопоставляется.",
        )


# --- Check B: facility identity ---------------------------------------------


def _check_facility(
    result: CheckResult,
    project_id: str,
    project_claims: list[EntityClaim],
) -> None:
    facility_claims = [c for c in project_claims if c.candidate_entity_type in ("emission_source",)]
    object_claims = [
        c
        for c in project_claims
        if c.candidate_entity_type == "activity" and c.attribute == "object"
    ]
    docs = {c.provenance.document_id for c in facility_claims + object_claims}
    if len(docs) >= 2 and (facility_claims or object_claims):
        _suppress(
            result,
            project_id,
            "facility",
            "facility_identity",
            "no_explicit_facility_identifier",
            [c.claim_id for c in facility_claims + object_claims],
            "Идентичность объекта между документами не устанавливается:"
            " внутридокументная нумерация источников и свободный текст объекта"
            " не являются межкументными идентификаторами.",
        )


# --- Check D: activity / category -------------------------------------------


def _canonical_category(normalized_value: str) -> str | None:
    """Map a normalized category surface to its controlled canonical, or None
    when it is not a recognized structured category (not comparable)."""
    return ACTIVITY_CATEGORY_ALIASES.get(normalized_value)


def _check_activity(
    result: CheckResult,
    project_id: str,
    project_claims: list[EntityClaim],
    doctype_by_id: dict[str, str],
    operator: OperatorResolution | None,
) -> None:
    """Conservative structured activity/category coherence.

    Compares ONLY explicitly-classified category claims (controlled vocabulary),
    within the same reporting instance and reporting context, AND only when the
    compared claims are linked to an established shared identity — a single
    resolved operator entity for the package. This MVP has no facility/entity
    resolution mechanism (Check B always suppresses facility identity), so the
    resolved operator is the only currently available shared-identity anchor.
    Without it, incompatible categories cannot be safely attributed to one
    real-world entity and are suppressed, never guessed into a conflict — even
    when the raw category values are explicit and structured.

    Equivalent aliases fold to one canonical (never a conflict); only distinct
    incompatible canonicals across matched identity AND scope raise a finding.
    Free-text object descriptions and out-of-scope / unspecific categories are
    suppressed, never guessed into a conflict. The accepted corpus has no
    explicit category label, so production yields no category conflict.
    """
    category_claims = [
        c
        for c in project_claims
        if c.candidate_entity_type == "activity" and c.attribute == "category"
    ]

    # Scope gate: compare categories only within the reporting-instance package.
    in_scope: list[EntityClaim] = []
    out_scope: list[EntityClaim] = []
    for claim in category_claims:
        document_id = claim.provenance.document_id or ""
        if doctype_by_id.get(document_id) in REPORTING_INSTANCE_DOC_TYPES:
            in_scope.append(claim)
        else:
            out_scope.append(claim)
    if out_scope:
        _suppress(
            result,
            project_id,
            "activity",
            "category",
            "different_document_purpose",
            [c.claim_id for c in out_scope],
            "Категории из проектных/непрофильных документов не сравниваются с"
            " разрешительным пакетом (иная область применения).",
        )

    # Controlled-vocabulary mapping; unrecognized values are not comparable.
    by_canon: dict[str, list[EntityClaim]] = {}
    unspecific: list[EntityClaim] = []
    for claim in in_scope:
        canon = _canonical_category(claim.normalized_value)
        if canon is None:
            unspecific.append(claim)
        else:
            by_canon.setdefault(canon, []).append(claim)
    if unspecific:
        _suppress(
            result,
            project_id,
            "activity",
            "category",
            "unspecific_category_not_comparable",
            [c.claim_id for c in unspecific],
            "Значение категории не сопоставлено с контролируемым словарём —"
            " недостаточно специфично для сравнения.",
        )

    distinct = sorted(by_canon)
    if len(distinct) >= 2:
        involved_docs = {str(c.provenance.document_id) for grp in by_canon.values() for c in grp}
        all_claim_ids = [c.claim_id for grp in by_canon.values() for c in grp]
        # Identity gate: a conflict may be emitted only when the compared claims
        # are linked to an established shared identity (the package's single
        # resolved operator entity). Absent, conflicting or unresolved operator
        # identity means the categories cannot be safely attributed to the same
        # real-world entity — suppress, never guess a conflict, and never claim
        # the categories ARE compatible either.
        if operator is None or not operator.status.startswith("confirmed"):
            identity_status = operator.status if operator is not None else "absent"
            candidate_entity_ids = operator.operator_entity_ids if operator is not None else []
            _suppress(
                result,
                project_id,
                "activity",
                "category",
                "activity_identity_not_established",
                all_claim_ids,
                f"Категории ({', '.join(distinct)}) в документах"
                f" {', '.join(sorted(involved_docs))} не сопоставляются: идентичность"
                f" оператора/объекта пакета не установлена (статус: {identity_status})."
                " Это не означает, что категории совместимы — сравнение просто"
                " не выполняется без подтверждённой общей идентичности.",
                entity_ids=candidate_entity_ids,
            )
        else:
            # Reporting-context gate: categories from documents that assert
            # DIFFERENT reporting periods describe different instances →
            # suppress, not conflict.
            periods = {
                c.normalized_value
                for c in project_claims
                if c.candidate_entity_type == "reporting_period"
                and c.attribute == "reporting_period"
                and c.provenance.document_id in involved_docs
            }
            if len(periods) >= 2:
                _suppress(
                    result,
                    project_id,
                    "activity",
                    "category",
                    "reporting_context_mismatch",
                    all_claim_ids,
                    "Категории относятся к документам с разными отчётными периодами —"
                    " разные отчётные инстанции, сравнение исключено.",
                    entity_ids=operator.operator_entity_ids,
                )
            else:
                rep_claims = [
                    sorted(grp, key=lambda c: c.claim_id)[0] for _, grp in sorted(by_canon.items())
                ]
                multi_document = len({c.provenance.document_id for c in rep_claims}) >= 2
                flags = _flags(rep_claims)
                severity = "medium" if multi_document and "ocr_source" not in flags else "low"
                result.findings.append(
                    _make_finding(
                        project_id,
                        "conflicting_activity_or_category",
                        severity,
                        "P4-D-CATEGORY",
                        "Несовместимые явные категории деятельности в документах пакета",
                        f"{_POTENTIAL}: документы пакета указывают несовместимые явные"
                        f" категории деятельности: {', '.join(distinct)}. {_NEEDS_REVIEW}",
                        evidence_claims=rep_claims,
                        conflicting_claims=[_conflicting(c) for c in rep_claims],
                        entity_ids=operator.operator_entity_ids,
                        observed_value=", ".join(distinct),
                        expected_value="единая категория деятельности пакета",
                        limitations="Сравниваются только явно классифицированные категории"
                        " из контролируемого словаря при подтверждённой общей"
                        " идентичности оператора; свободный текст, разные отчётные"
                        " инстанции и непрофильные документы исключаются.",
                    )
                )

    # Free-text object descriptions are never compared lexically.
    object_claims = [
        c
        for c in project_claims
        if c.candidate_entity_type == "activity" and c.attribute == "object"
    ]
    obj_docs = {c.provenance.document_id for c in object_claims}
    if len(obj_docs) >= 2:
        _suppress(
            result,
            project_id,
            "activity",
            "object_description",
            "free_text_activity_scope_uncertain",
            [c.claim_id for c in object_claims],
            "Описания деятельности/объекта — свободный текст; лексическое сходство"
            " не используется как признак совпадения или противоречия.",
        )
