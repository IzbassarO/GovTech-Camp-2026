"""P5 conservative cross-modal checks (A–H) producing findings/suppressions.

Every finding is a review cue with document/page/asset provenance, honest
limitations and ``legal_conclusion = False``. Low embedding similarity is a
signal, never a proven contradiction; absence of a visible map element is a
review cue, never proof of an invalid map. High severity is never produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dalel.pillars.multimodal_visual_evidence.config import (
    CAPTION_CLASS_HINTS,
    CAPTION_COMPATIBLE_CLASSES,
    CHART_CUE_UNIT_KEYWORDS,
    CHART_TABLE_CLASSES,
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    CONFIDENCE_PENALTIES,
    DUPLICATE_INFLATION_MIN_MEMBERS,
    FINDING_CONFIDENCE,
    MAP_CUE_KEYWORDS,
    MAP_CUE_MIN_OCR_TOKENS,
    MAP_LIKE_CLASSES,
    MEANINGFUL_CLASSES,
    MISMATCH_MIN_AFFINITY,
    MISSING_VISUAL_MIN_REFERENCES,
    PROJECT_SPECIFIC_CLASSES,
    RELEVANCE_LOW_SIMILARITY,
    RUSSIAN_CLASS_LABELS,
    SEVERITY_POINTS,
)
from dalel.pillars.multimodal_visual_evidence.schemas import (
    ConfidenceFactor,
    P5AssetContext,
    P5AssetRecord,
    P5Classification,
    P5DuplicateCluster,
    P5Evidence,
    P5FindingRecord,
    P5Suppression,
    deterministic_id,
)


@dataclass
class CheckOutcome:
    findings: list[P5FindingRecord] = field(default_factory=list)
    suppressions: list[P5Suppression] = field(default_factory=list)


def finding_confidence(finding_type: str, flags: list[str]) -> tuple[float, list[ConfidenceFactor]]:
    base = FINDING_CONFIDENCE.get(finding_type, 0.5)
    factors = [ConfidenceFactor(factor=f"base:{finding_type}", delta=base)]
    value = base
    applied: set[str] = set()
    for flag in flags:
        penalty = CONFIDENCE_PENALTIES.get(flag)
        if penalty is not None and flag not in applied:
            applied.add(flag)
            value -= penalty
            factors.append(ConfidenceFactor(factor=flag, delta=-penalty))
    value = round(min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, value)), 2)
    return value, factors


def finding_id_for(
    project_id: str,
    finding_type: str,
    document_id: str | None,
    asset_id: str | None,
    cluster_id: str | None,
    related_asset_ids: list[str],
) -> str:
    return deterministic_id(
        "P5",
        project_id,
        finding_type,
        document_id or "",
        asset_id or "",
        cluster_id or "",
        "|".join(related_asset_ids),
    )


def _make_finding(
    *,
    project_id: str,
    finding_type: str,
    severity: str,
    rule_id: str,
    title: str,
    explanation: str,
    limitations: str,
    document_id: str | None = None,
    asset_id: str | None = None,
    related_asset_ids: list[str] | None = None,
    page_number: int | None = None,
    evidence: list[P5Evidence] | None = None,
    duplicate_cluster_id: str | None = None,
    deterministic_signals: list[str] | None = None,
    model_signals: dict[str, float] | None = None,
    context_signals: list[str] | None = None,
    quality_flags: list[str] | None = None,
) -> P5FindingRecord:
    flags = sorted(quality_flags or [])
    confidence, factors = finding_confidence(finding_type, flags)
    related = sorted(related_asset_ids or [])
    return P5FindingRecord(
        finding_id=finding_id_for(
            project_id, finding_type, document_id, asset_id, duplicate_cluster_id, related
        ),
        project_id=project_id,
        document_id=document_id,
        asset_id=asset_id,
        related_asset_ids=related,
        page_number=page_number,
        finding_type=finding_type,
        severity=severity,
        priority_score=SEVERITY_POINTS[severity],
        confidence=confidence,
        confidence_factors=factors,
        rule_id=rule_id,
        title=title,
        explanation=explanation,
        evidence=evidence or [],
        duplicate_cluster_id=duplicate_cluster_id,
        deterministic_signals=sorted(deterministic_signals or []),
        model_signals=model_signals or {},
        context_signals=sorted(context_signals or []),
        quality_flags=flags,
        limitations=limitations,
    )


def _suppression(
    project_id: str,
    check: str,
    reason: str,
    *,
    asset_id: str | None = None,
    document_id: str | None = None,
    detail: str = "",
) -> P5Suppression:
    return P5Suppression(
        suppression_id=deterministic_id(
            "P5S", project_id, check, reason, asset_id or "", document_id or ""
        ),
        project_id=project_id,
        check=check,
        asset_id=asset_id,
        document_id=document_id,
        reason=reason,
        detail=detail,
    )


def _visual_evidence(asset: P5AssetRecord) -> P5Evidence:
    return P5Evidence(
        kind="visual_asset",
        document_id=asset.document_id,
        document_type=asset.document_type,
        page_number=asset.page_number,
        asset_id=asset.asset_id,
        note=f"Растровое изображение {asset.image_id} (стр. {asset.page_number or '—'})",
    )


def run_checks(
    *,
    assets: list[P5AssetRecord],
    contexts: dict[str, P5AssetContext],
    classifications: dict[str, P5Classification],
    clusters: list[P5DuplicateCluster],
    figure_refs_by_document: dict[str, list[tuple[int, str]]],
    document_types: dict[str, str],
    document_projects: dict[str, str],
    model_available: bool,
) -> CheckOutcome:
    """Run checks A–G (H is structural: procedural assets never enter A–G)."""
    outcome = CheckOutcome()
    assets_by_id = {asset.asset_id: asset for asset in assets}
    representatives = [
        asset
        for asset in assets
        if asset.triage_status == "analyzed_representative"
        and not asset.procedural_supporting_evidence
    ]

    _check_a_relevance(outcome, representatives, contexts, classifications, model_available)
    _check_b_caption_mismatch(outcome, representatives, contexts, classifications)
    _check_c_duplicate_inflation(outcome, clusters, assets_by_id, classifications)
    _check_d_missing_visuals(
        outcome, assets, figure_refs_by_document, document_types, document_projects
    )
    _check_e_map_cues(outcome, representatives, contexts, classifications)
    _check_f_chart_cues(outcome, representatives, contexts, classifications)
    _check_g_cross_document_reuse(outcome, clusters, assets_by_id, classifications)

    outcome.findings.sort(
        key=lambda f: (
            f.project_id,
            f.document_id or "~",
            {"high": 0, "medium": 1, "low": 2, "info": 3}.get(f.severity, 9),
            f.finding_type,
            f.finding_id,
        )
    )
    outcome.suppressions.sort(key=lambda s: s.suppression_id)
    return outcome


# --- A. visual relevance ------------------------------------------------------


def _check_a_relevance(
    outcome: CheckOutcome,
    representatives: list[P5AssetRecord],
    contexts: dict[str, P5AssetContext],
    classifications: dict[str, P5Classification],
    model_available: bool,
) -> None:
    if not model_available:
        for project_id in sorted({asset.project_id for asset in representatives}):
            outcome.suppressions.append(
                _suppression(
                    project_id,
                    "visual_relevance",
                    "model_unavailable",
                    detail="Проверка связи изображения с текстом требует мультимодальной модели.",
                )
            )
        return
    for asset in sorted(representatives, key=lambda a: a.asset_id):
        classification = classifications.get(asset.asset_id)
        context = contexts.get(asset.asset_id)
        if classification is None or classification.predicted_class not in MEANINGFUL_CLASSES:
            continue
        if context is None or context.image_context_similarity is None:
            outcome.suppressions.append(
                _suppression(
                    asset.project_id,
                    "visual_relevance",
                    "no_page_context",
                    asset_id=asset.asset_id,
                    document_id=asset.document_id,
                    detail="Нет текста страницы или эмбеддинга для сопоставления.",
                )
            )
            continue
        context_low = context.image_context_similarity < RELEVANCE_LOW_SIMILARITY
        caption_low = (
            context.image_caption_similarity is None
            or context.image_caption_similarity < RELEVANCE_LOW_SIMILARITY
        )
        if context_low and caption_low:
            label = RUSSIAN_CLASS_LABELS.get(
                classification.predicted_class, classification.predicted_class
            )
            model_signals = {
                "image_context_similarity": context.image_context_similarity,
            }
            if context.image_caption_similarity is not None:
                model_signals["image_caption_similarity"] = context.image_caption_similarity
            outcome.findings.append(
                _make_finding(
                    project_id=asset.project_id,
                    finding_type="visual_relevance_review",
                    severity="info",
                    rule_id="P5-A-RELEVANCE",
                    title=f"{label}: слабая связь с окружающим текстом",
                    explanation=(
                        "Эмбеддинговое сходство изображения с текстом страницы и"
                        " подписью низкое. Это сигнал для проверки уместности"
                        " материала, а не доказательство несоответствия."
                    ),
                    limitations=(
                        "Низкое сходство эмбеддингов НЕ является доказанным"
                        " противоречием; модель могла не распознать специфичную"
                        " графику. Требуется проверка экспертом."
                    ),
                    document_id=asset.document_id,
                    asset_id=asset.asset_id,
                    page_number=asset.page_number,
                    evidence=[
                        _visual_evidence(asset),
                        P5Evidence(
                            kind="page_text",
                            document_id=asset.document_id,
                            page_number=asset.page_number,
                            quote=(context.page_text_excerpt or "")[:200] or None,
                            note="Контекст страницы, с которым сопоставлялось изображение.",
                        ),
                    ],
                    model_signals=model_signals,
                    context_signals=["low_image_text_alignment"],
                    quality_flags=["sparse_context"] if context.caption is None else [],
                )
            )


# --- B. caption/image mismatch ------------------------------------------------


def _check_b_caption_mismatch(
    outcome: CheckOutcome,
    representatives: list[P5AssetRecord],
    contexts: dict[str, P5AssetContext],
    classifications: dict[str, P5Classification],
) -> None:
    for asset in sorted(representatives, key=lambda a: a.asset_id):
        context = contexts.get(asset.asset_id)
        classification = classifications.get(asset.asset_id)
        if context is None or classification is None or not context.caption:
            continue
        lowered = context.caption.casefold()
        hinted = [
            visual_class
            for visual_class, keywords in CAPTION_CLASS_HINTS.items()
            if any(keyword in lowered for keyword in keywords)
        ]
        if not hinted:
            continue
        compatible: set[str] = set()
        for visual_class in hinted:
            compatible |= CAPTION_COMPATIBLE_CLASSES.get(visual_class, frozenset({visual_class}))
        predicted = classification.predicted_class
        if predicted in compatible or predicted == "unknown":
            continue
        confident = (
            classification.decision_path == "model_zero_shot"
            and (classification.classification_confidence or 0.0) >= MISMATCH_MIN_AFFINITY
        )
        if not confident:
            outcome.suppressions.append(
                _suppression(
                    asset.project_id,
                    "caption_image_mismatch",
                    "insufficient_model_confidence",
                    asset_id=asset.asset_id,
                    document_id=asset.document_id,
                    detail=(
                        f"Подпись предполагает {'/'.join(sorted(hinted))}, модель"
                        f" предсказала {predicted}, но уверенность ниже порога."
                    ),
                )
            )
            continue
        hinted_labels = ", ".join(RUSSIAN_CLASS_LABELS.get(name, name) for name in sorted(hinted))
        predicted_label = RUSSIAN_CLASS_LABELS.get(predicted, predicted)
        outcome.findings.append(
            _make_finding(
                project_id=asset.project_id,
                finding_type="caption_image_mismatch",
                severity="low",
                rule_id="P5-B-CAPTION-MISMATCH",
                title=f"Подпись «{hinted_labels}» не согласуется с изображением",
                explanation=(
                    f"Подпись описывает материал как «{hinted_labels}», однако"
                    f" модель уверенно классифицировала изображение как"
                    f" «{predicted_label}». Возможна ошибка вставки или подписи."
                ),
                limitations=(
                    "Классификация модели — это аффинность по сходству, а не"
                    " гарантированная истина; эксперт должен сверить страницу"
                    " документа вручную."
                ),
                document_id=asset.document_id,
                asset_id=asset.asset_id,
                page_number=asset.page_number,
                evidence=[
                    _visual_evidence(asset),
                    P5Evidence(
                        kind="caption",
                        document_id=asset.document_id,
                        page_number=asset.page_number,
                        quote=context.caption[:200],
                        note="Подпись, обнаруженная на странице документа.",
                    ),
                ],
                model_signals={
                    "classification_confidence": classification.classification_confidence or 0.0
                },
                context_signals=[f"caption_hint:{name}" for name in sorted(hinted)],
            )
        )


# --- C. duplicate inflation ---------------------------------------------------


def _check_c_duplicate_inflation(
    outcome: CheckOutcome,
    clusters: list[P5DuplicateCluster],
    assets_by_id: dict[str, P5AssetRecord],
    classifications: dict[str, P5Classification],
) -> None:
    for cluster in clusters:
        if cluster.kind not in {"exact_duplicate", "near_duplicate"}:
            continue
        if cluster.member_count < DUPLICATE_INFLATION_MIN_MEMBERS:
            continue
        representative = assets_by_id.get(cluster.representative_asset_id)
        classification = classifications.get(cluster.representative_asset_id)
        if representative is None or classification is None:
            continue
        if classification.predicted_class not in PROJECT_SPECIFIC_CLASSES:
            continue
        label = RUSSIAN_CLASS_LABELS.get(
            classification.predicted_class, classification.predicted_class
        )
        document_id = cluster.document_ids[0] if len(cluster.document_ids) == 1 else None
        pages = ", ".join(str(p) for p in cluster.page_numbers[:12])
        outcome.findings.append(
            _make_finding(
                project_id=cluster.project_id,
                finding_type="duplicate_visual_inflation",
                severity="info",
                rule_id="P5-C-DUP-INFLATION",
                title=f"{label} повторяется {cluster.member_count} раз",
                explanation=(
                    f"Одно и то же изображение класса «{label}» встречается"
                    f" {cluster.member_count} раз (страницы: {pages or '—'})."
                    " Повторы не считаются независимыми доказательствами и"
                    " исключены из оценки; учитывается один представитель."
                ),
                limitations=(
                    "Повторение может быть законным оформительским приёмом;"
                    " проверка нужна только для подтверждения, что повторы не"
                    " маскируют отсутствие уникальных материалов."
                ),
                document_id=document_id,
                asset_id=cluster.representative_asset_id,
                related_asset_ids=[
                    m for m in cluster.member_asset_ids if m != cluster.representative_asset_id
                ],
                page_number=representative.page_number,
                evidence=[_visual_evidence(representative)],
                duplicate_cluster_id=cluster.cluster_id,
                deterministic_signals=cluster.linking_evidence,
            )
        )


# --- D. missing referenced visuals ---------------------------------------------


def _check_d_missing_visuals(
    outcome: CheckOutcome,
    assets: list[P5AssetRecord],
    figure_refs_by_document: dict[str, list[tuple[int, str]]],
    document_types: dict[str, str],
    document_projects: dict[str, str],
) -> None:
    assets_per_document: dict[str, int] = {}
    for asset in assets:
        assets_per_document[asset.document_id] = assets_per_document.get(asset.document_id, 0) + 1
    for document_id, references in sorted(figure_refs_by_document.items()):
        if assets_per_document.get(document_id, 0) > 0:
            continue
        distinct = sorted({reference for _page, reference in references})
        if len(distinct) < MISSING_VISUAL_MIN_REFERENCES:
            continue
        project_id = document_projects.get(document_id)
        if project_id is None:
            # Cannot attribute the document to a project in this run.
            continue
        sample = references[:2]
        evidence = [
            P5Evidence(
                kind="page_text",
                document_id=document_id,
                document_type=document_types.get(document_id),
                page_number=page,
                quote=reference,
                note="Явная ссылка на визуальный материал в тексте.",
            )
            for page, reference in sample
        ]
        outcome.findings.append(
            _make_finding(
                project_id=project_id,
                finding_type="missing_referenced_visual",
                severity="low",
                rule_id="P5-D-MISSING-VISUAL",
                title="Текст ссылается на рисунки, но изображения не извлечены",
                explanation=(
                    f"Документ содержит {len(distinct)} различных нумерованных"
                    " ссылок на рисунки/схемы/карты, однако ни одного растрового"
                    " изображения из документа извлечь не удалось. Ожидаемые"
                    " визуальные материалы недоступны для проверки."
                ),
                limitations=(
                    "Изображение могло быть векторным или не извлечься парсером;"
                    " отсутствие в инвентаре НЕ доказывает отсутствие в исходном"
                    " документе. Требуется ручная проверка исходного файла."
                ),
                document_id=document_id,
                evidence=evidence,
                deterministic_signals=[f"figure_references:{len(distinct)}"],
                context_signals=distinct[:6],
            )
        )


# --- E. map completeness cues ---------------------------------------------------


def _check_e_map_cues(
    outcome: CheckOutcome,
    representatives: list[P5AssetRecord],
    contexts: dict[str, P5AssetContext],
    classifications: dict[str, P5Classification],
) -> None:
    for asset in sorted(representatives, key=lambda a: a.asset_id):
        classification = classifications.get(asset.asset_id)
        if classification is None or classification.predicted_class not in MAP_LIKE_CLASSES:
            continue
        context = contexts.get(asset.asset_id)
        ocr_text = (context.ocr_text if context else None) or ""
        ocr_ok = bool(
            context
            and context.ocr_status == "completed"
            and len(ocr_text.split()) >= MAP_CUE_MIN_OCR_TOKENS
        )
        if not ocr_ok:
            reason = (
                "ocr_unavailable"
                if not context or context.ocr_status in {"unavailable", "not_run"}
                else "ocr_insufficient"
            )
            outcome.suppressions.append(
                _suppression(
                    asset.project_id,
                    "map_completeness",
                    reason,
                    asset_id=asset.asset_id,
                    document_id=asset.document_id,
                    detail="Документальные признаки карты не проверялись без надёжного OCR.",
                )
            )
            continue
        lowered = ocr_text.casefold()
        present = sorted(
            cue
            for cue, keywords in MAP_CUE_KEYWORDS.items()
            if any(keyword in lowered for keyword in keywords)
        )
        absent = sorted(set(MAP_CUE_KEYWORDS) - set(present))
        if not absent:
            continue
        cue_labels = {
            "legend": "легенда/условные обозначения",
            "scale": "масштаб",
            "coordinates": "координатные подписи",
            "boundary": "граница/СЗЗ",
            "location_marker": "маркер площадки",
        }
        absent_text = ", ".join(cue_labels.get(cue, cue) for cue in absent)
        label = RUSSIAN_CLASS_LABELS.get(
            classification.predicted_class, classification.predicted_class
        )
        outcome.findings.append(
            _make_finding(
                project_id=asset.project_id,
                finding_type="map_completeness_cue",
                severity="info",
                rule_id="P5-E-MAP-CUES",
                title=f"{label}: не найдены видимые элементы ({absent_text})",
                explanation=(
                    f"В распознанном тексте карты не обнаружены: {absent_text}."
                    " Отсутствие видимого элемента — повод для проверки"
                    " читаемости и полноты карты, а не доказательство её"
                    " некорректности."
                ),
                limitations=(
                    "OCR мог не распознать мелкие подписи; стрелка севера и"
                    " графические элементы без текста не детектируются."
                    " Вывод требует визуальной проверки экспертом."
                ),
                document_id=asset.document_id,
                asset_id=asset.asset_id,
                page_number=asset.page_number,
                evidence=[
                    _visual_evidence(asset),
                    P5Evidence(
                        kind="ocr_text",
                        document_id=asset.document_id,
                        page_number=asset.page_number,
                        asset_id=asset.asset_id,
                        quote=ocr_text[:200],
                        note="Фрагмент распознанного текста изображения.",
                    ),
                ],
                deterministic_signals=[f"cue_present:{cue}" for cue in present]
                + [f"cue_absent:{cue}" for cue in absent],
                quality_flags=(
                    ["ocr_low_confidence"]
                    if context and (context.ocr_mean_confidence or 1.0) < 0.5
                    else []
                ),
            )
        )


# --- F. chart/table cues --------------------------------------------------------


def _check_f_chart_cues(
    outcome: CheckOutcome,
    representatives: list[P5AssetRecord],
    contexts: dict[str, P5AssetContext],
    classifications: dict[str, P5Classification],
) -> None:
    chart_projects: set[str] = set()
    for asset in sorted(representatives, key=lambda a: a.asset_id):
        classification = classifications.get(asset.asset_id)
        if classification is None or classification.predicted_class not in CHART_TABLE_CLASSES:
            continue
        chart_projects.add(asset.project_id)
        context = contexts.get(asset.asset_id)
        if not context or context.ocr_status != "completed" or not context.ocr_text:
            outcome.suppressions.append(
                _suppression(
                    asset.project_id,
                    "chart_readability",
                    "ocr_unavailable",
                    asset_id=asset.asset_id,
                    document_id=asset.document_id,
                    detail="Читаемость графика/таблицы не проверялась без OCR.",
                )
            )
            continue
        lowered = context.ocr_text.casefold()
        has_units = any(keyword in lowered for keyword in CHART_CUE_UNIT_KEYWORDS)
        has_digits = any(character.isdigit() for character in lowered)
        if has_units or has_digits:
            continue
        label = RUSSIAN_CLASS_LABELS.get(
            classification.predicted_class, classification.predicted_class
        )
        outcome.findings.append(
            _make_finding(
                project_id=asset.project_id,
                finding_type="chart_readability_cue",
                severity="info",
                rule_id="P5-F-CHART-CUES",
                title=f"{label}: не распознаны числа и единицы измерения",
                explanation=(
                    "В распознанном тексте графика/таблицы не найдено ни чисел,"
                    " ни единиц измерения. Материал может быть нечитаемым в"
                    " печатном виде или вставлен в низком разрешении."
                ),
                limitations=(
                    "OCR ограничен по качеству на мелких шрифтах; вывод о"
                    " читаемости должен подтвердить эксперт. Сверка значений с"
                    " P3 не выполнялась (оцифровка графиков не производится)."
                ),
                document_id=asset.document_id,
                asset_id=asset.asset_id,
                page_number=asset.page_number,
                evidence=[
                    _visual_evidence(asset),
                    P5Evidence(
                        kind="ocr_text",
                        document_id=asset.document_id,
                        page_number=asset.page_number,
                        asset_id=asset.asset_id,
                        quote=(context.ocr_text or "")[:200] or None,
                        note="Распознанный текст изображения.",
                    ),
                ],
                deterministic_signals=["no_digits_in_ocr", "no_units_in_ocr"],
                context_signals=(
                    [f"p3_mentions_on_page:{context.quantitative_mentions_on_page}"]
                    if context.quantitative_mentions_on_page
                    else []
                ),
            )
        )
    # Honest suppression: chart digitization is never attempted.
    for project_id in sorted(chart_projects):
        outcome.suppressions.append(
            _suppression(
                project_id,
                "chart_value_digitization",
                "not_reliable_without_manual_check",
                detail=(
                    "Автоматическая оцифровка значений графиков не выполняется:"
                    " сверка чисел с P3 без надёжного извлечения точек данных"
                    " дала бы ложные сигналы."
                ),
            )
        )


# --- G. cross-document visual reuse ---------------------------------------------


def _check_g_cross_document_reuse(
    outcome: CheckOutcome,
    clusters: list[P5DuplicateCluster],
    assets_by_id: dict[str, P5AssetRecord],
    classifications: dict[str, P5Classification],
) -> None:
    for cluster in clusters:
        if cluster.kind not in {"exact_duplicate", "near_duplicate"}:
            continue
        if len(cluster.document_ids) < 2 or len(cluster.exact_sha256_values) != 1:
            # Identity across documents is only "well established" for
            # byte-identical images.
            continue
        classification = classifications.get(cluster.representative_asset_id)
        representative = assets_by_id.get(cluster.representative_asset_id)
        if representative is None or classification is None:
            continue
        if classification.predicted_class not in PROJECT_SPECIFIC_CLASSES:
            continue
        label = RUSSIAN_CLASS_LABELS.get(
            classification.predicted_class, classification.predicted_class
        )
        documents = ", ".join(cluster.document_ids)
        outcome.findings.append(
            _make_finding(
                project_id=cluster.project_id,
                finding_type="cross_document_visual_reuse",
                severity="low",
                rule_id="P5-G-CROSS-DOC-REUSE",
                title=f"{label} побайтово повторяется в {len(cluster.document_ids)} документах",
                explanation=(
                    f"Идентичное изображение класса «{label}» (SHA-256 совпадает)"
                    f" используется в документах: {documents}. Повторное"
                    " использование проектно-специфичного материала стоит"
                    " проверить на актуальность в каждом документе."
                ),
                limitations=(
                    "Повторное использование может быть корректным (одна карта"
                    " для всего пакета); находка лишь фиксирует факт идентичности"
                    " байтов, без вывода о нарушении."
                ),
                document_id=None,
                asset_id=cluster.representative_asset_id,
                related_asset_ids=[
                    m for m in cluster.member_asset_ids if m != cluster.representative_asset_id
                ],
                page_number=representative.page_number,
                evidence=[_visual_evidence(representative)],
                duplicate_cluster_id=cluster.cluster_id,
                deterministic_signals=["exact_sha256_across_documents"],
            )
        )
