"""Human-readable P1 run report."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dalel.pillars.document_integrity import P1_VERSION

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for typing only
    from dalel.pillars.document_integrity.pipeline import P1RunResult


def render_p1_report(result: P1RunResult) -> str:
    metrics = result.metrics
    lines: list[str] = [
        f"# P1 Document Integrity — deterministic baseline (v{P1_VERSION})",
        "",
        "Score = приоритет ручной проверки структуры (0–100), НЕ вероятность"
        " нарушения. LLM и embeddings не использовались.",
        "",
        f"- Документов проанализировано: {metrics['documents_analyzed']}",
        f"- Проектов: {metrics['projects_analyzed']}",
        f"- Findings: {metrics['findings_total']}",
        f"- По severity: {metrics['findings_by_severity']}",
        "",
        "## Findings по типам",
        "",
    ]
    for finding_type, count in metrics["findings_by_type"].items():
        lines.append(f"- {finding_type}: {count}")

    lines += ["", "## Приоритеты по документам", ""]
    for document_id, score in sorted(
        metrics["score_distribution"]["documents"].items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"- {document_id}: {score}")

    lines += ["", "## Приоритеты по проектам", ""]
    for project_score in result.project_scores:
        lines.append(
            f"- {project_score.project_id}:"
            f" {project_score.document_integrity_priority_score}"
            f" (package findings: {project_score.package_finding_count})"
        )

    ablation = metrics["section_matching_ablation"]
    lines += [
        "",
        "## Section matching — ablation (4 метода раздельно)",
        "",
        f"- Правил проверено: {ablation['rules_evaluated']}",
        f"- Сопоставлено всего: {ablation['matched_total']}"
        f" (exact_equality {ablation['matched_exact_equality']},"
        f" normalized_substring {ablation['matched_normalized_substring']},"
        f" token_overlap {ablation['matched_token_overlap']},"
        f" fuzzy {ablation['matched_fuzzy']})",
        f"- Отклонено fuzzy-кандидатов без discriminative evidence:"
        f" {ablation['rejected_fuzzy_candidates']}",
        f"- Не найдено required: {ablation['unmatched_required']},"
        f" recommended: {ablation['unmatched_recommended']}",
        f"- Evidence всех accepted matches: section_matches.jsonl"
        f" ({metrics['section_matches_serialized']} записей).",
        "",
        "## Качество страниц",
        "",
        f"- Пустых страниц: {metrics['page_quality']['empty_pages']}",
        f"- Почти пустых (<32 симв.): {metrics['page_quality']['near_empty_pages']}",
        "",
        "## Кандидаты на false positive (ручной просмотр в первую очередь)",
        "",
        f"- {metrics['false_positive_review_candidate_count']} findings"
        " (единый источник: is_false_positive_review_candidate):"
        f" {', '.join(metrics['false_positive_review_candidates'][:20])}"
        + ("…" if metrics["false_positive_review_candidate_count"] > 20 else ""),
        "",
        "## Ограничения оценки",
        "",
        f"- {metrics['evaluation_note']}.",
        "- Все findings имеют confidence=null (нет вероятностной модели) и"
        " review_status=pending: решения принимает эксперт через"
        " data/annotations/p1_review_template.jsonl.",
    ]
    return "\n".join(lines) + "\n"
