"""P1 run orchestration over the curated dataset (read-only input)."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dalel.ingestion.reports import utc_now_iso
from dalel.pillars.document_integrity import P1_VERSION
from dalel.pillars.document_integrity.config import config_snapshot
from dalel.pillars.document_integrity.document_completeness import (
    appendix_reference_findings,
    duplicate_heading_findings,
    section_findings,
    structural_anomaly_findings,
    table_and_length_findings,
)
from dalel.pillars.document_integrity.package_completeness import (
    date_range_findings,
    metadata_findings,
    package_findings,
)
from dalel.pillars.document_integrity.quality import quality_findings
from dalel.pillars.document_integrity.reports import render_p1_report
from dalel.pillars.document_integrity.schemas import (
    DocumentScoreRecord,
    FindingRecord,
    ProjectScoreRecord,
)
from dalel.pillars.document_integrity.scoring import score_document, score_project
from dalel.pillars.document_integrity.section_matcher import HeadingCandidate, SectionMatch
from dalel.pillars.document_integrity.taxonomy import taxonomy_as_dict


class P1RunError(Exception):
    """Blocking P1 execution failure (missing/invalid curated input)."""


# Single source of truth for the false-positive review-candidate policy.
# Used by metrics.json, report.md, the review template summary and any
# top-level report; counts must never be derived independently elsewhere.
FP_CANDIDATE_TYPES = frozenset(
    {"missing_appendix_reference", "duplicate_heading", "date_range_inconsistency"}
)


def is_false_positive_review_candidate(finding: FindingRecord) -> bool:
    if finding.finding_type in FP_CANDIDATE_TYPES:
        return True
    return finding.finding_type == "missing_expected_section" and finding.severity == "low"


@dataclass
class P1Options:
    dataset_dir: Path
    output_dir: Path
    annotations_root: Path
    project_id: str | None = None
    document_id: str | None = None


@dataclass
class P1RunResult:
    findings: list[FindingRecord] = field(default_factory=list)
    document_scores: list[DocumentScoreRecord] = field(default_factory=list)
    project_scores: list[ProjectScoreRecord] = field(default_factory=list)
    section_matches: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    review_template_path: Path | None = None
    review_template_created: bool = False
    review_template_preserved_decisions: int = 0
    review_template_stale_rows: int = 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise P1RunError(f"curated file is missing: {path}")
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _stable_finding_id(finding: FindingRecord, seen: set[str]) -> str:
    """Content-derived, run-stable finding id (safe for review-template merge)."""
    basis = "|".join(
        [
            finding.project_id,
            finding.document_id or "__package__",
            finding.finding_type,
            finding.rule_id,
            finding.title,
        ]
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    candidate = f"P1__{digest}"
    suffix = 2
    while candidate in seen:
        candidate = f"P1__{digest}__{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


_MATCH_LIMITATIONS = {
    "exact_equality": "Нормализованное равенство; нечувствительно к вариациям формулировок.",
    "normalized_substring": (
        "Alias является подстрокой нормализованного заголовка; возможен избыточный"
        " охват на длинных заголовках."
    ),
    "token_overlap": "Совпадение множеств токенов; порядок слов не проверяется.",
    "fuzzy": (
        "Похожесть строк (SequenceMatcher) с обязательным discriminative-token"
        " evidence; консервативный порог, generic-токены не считаются evidence."
    ),
}


def run_p1(options: P1Options) -> P1RunResult:
    started_monotonic = time.monotonic()
    started_at = utc_now_iso()

    projects = _read_jsonl(options.dataset_dir / "projects.jsonl")
    documents = _read_jsonl(options.dataset_dir / "documents.jsonl")
    pages = _read_jsonl(options.dataset_dir / "pages.jsonl")
    sections = _read_jsonl(options.dataset_dir / "sections.jsonl")

    if options.project_id is not None:
        known = {str(p["project_id"]) for p in projects}
        if options.project_id not in known:
            raise P1RunError(f"--project-id {options.project_id!r} not in curated dataset")
    if options.document_id is not None:
        known_docs = {str(d["document_id"]) for d in documents}
        if options.document_id not in known_docs:
            raise P1RunError(f"--document-id {options.document_id!r} not in curated dataset")

    pages_by_document: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        pages_by_document.setdefault(str(page["provenance"]["document_id"]), []).append(page)
    headings_by_document: dict[str, list[HeadingCandidate]] = {}
    for section in sections:
        title = section.get("title")
        if title:
            headings_by_document.setdefault(str(section["provenance"]["document_id"]), []).append(
                HeadingCandidate(title=str(title), page_number=section.get("page_start"))
            )

    sequence = 0

    def id_gen() -> str:
        nonlocal sequence
        sequence += 1
        return f"P1_TMP__{sequence:05d}"  # provisional; replaced by stable ids

    result = P1RunResult()
    seen_ids: set[str] = set()
    all_matches: list[tuple[str, str, SectionMatch]] = []
    package_profiles: list[dict[str, Any]] = []
    package_checks_skipped = options.document_id is not None

    for project in projects:
        project_id = str(project["project_id"])
        if options.project_id is not None and project_id != options.project_id:
            continue
        project_documents = [
            d
            for d in documents
            if str(d["project_id"]) == project_id
            and (options.document_id is None or str(d["document_id"]) == options.document_id)
        ]
        if not project_documents:
            continue

        document_scores: list[DocumentScoreRecord] = []
        for document in project_documents:
            document_id = str(document["document_id"])
            doc_pages = pages_by_document.get(document_id, [])
            doc_headings = headings_by_document.get(document_id, [])
            doc_titles = [h.title for h in doc_headings]

            doc_findings: list[FindingRecord] = []
            missing_section, matches = section_findings(document, doc_headings, id_gen)
            all_matches.extend((project_id, document_id, m) for m in matches)
            doc_findings.extend(missing_section)
            doc_findings.extend(table_and_length_findings(document, id_gen))
            doc_findings.extend(duplicate_heading_findings(document, doc_titles, id_gen))
            doc_findings.extend(structural_anomaly_findings(document, id_gen))
            doc_findings.extend(
                appendix_reference_findings(document, doc_pages, doc_titles, id_gen)
            )
            doc_findings.extend(quality_findings(document, doc_pages, id_gen))

            for finding in doc_findings:
                finding.finding_id = _stable_finding_id(finding, seen_ids)
            result.findings.extend(doc_findings)
            document_scores.append(
                score_document(
                    project_id, document_id, str(document["document_type"]), doc_findings
                )
            )

        project_level: list[FindingRecord] = []
        if not package_checks_skipped:
            pkg_findings, profile_info = package_findings(project, project_documents, id_gen)
            package_profiles.append(profile_info)
            project_level.extend(pkg_findings)
            project_level.extend(metadata_findings(project, project_documents, id_gen))
            project_level.extend(
                date_range_findings(
                    project,
                    {
                        str(d["document_id"]): pages_by_document.get(str(d["document_id"]), [])
                        for d in project_documents
                    },
                    id_gen,
                )
            )
        for finding in project_level:
            finding.finding_id = _stable_finding_id(finding, seen_ids)
        result.findings.extend(project_level)
        result.document_scores.extend(document_scores)
        result.project_scores.append(score_project(project_id, document_scores, project_level))

    result.section_matches = _build_section_matches(all_matches)
    result.metrics = _build_metrics(
        result, all_matches, package_profiles, package_checks_skipped, pages_by_document
    )
    result.metrics["started_at"] = started_at
    result.metrics["completed_at"] = utc_now_iso()
    result.metrics["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 3)

    _write_outputs(options, result)
    return result


def _build_section_matches(
    matches: list[tuple[str, str, SectionMatch]],
) -> list[dict[str, Any]]:
    """Audit evidence for every ACCEPTED match: which heading satisfied which rule."""
    records: list[dict[str, Any]] = []
    for project_id, document_id, match in matches:
        if not match.matched:
            continue
        digest = hashlib.sha256(f"{document_id}|{match.rule.rule_id}".encode()).hexdigest()[:12]
        records.append(
            {
                "match_id": f"P1M__{digest}",
                "project_id": project_id,
                "document_id": document_id,
                "rule_id": match.rule.rule_id,
                "canonical_section": match.rule.canonical_section,
                "matched_alias": match.matched_alias,
                "observed_heading": match.matched_title,
                "normalized_heading": match.normalized_heading,
                "page_number": match.page_number,
                "method": match.method,
                "match_score": match.score,
                "discriminative_tokens": match.discriminative_tokens,
                "limitations": _MATCH_LIMITATIONS.get(match.method, ""),
            }
        )
    return records


def _build_metrics(
    result: P1RunResult,
    matches: list[tuple[str, str, SectionMatch]],
    package_profiles: list[dict[str, Any]],
    package_checks_skipped: bool,
    pages_by_document: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_document: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for finding in result.findings:
        by_type[finding.finding_type] = by_type.get(finding.finding_type, 0) + 1
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        key = finding.document_id or f"__package__/{finding.project_id}"
        by_document[key] = by_document.get(key, 0) + 1

    match_objects = [m for _p, _d, m in matches]
    matched = [m for m in match_objects if m.matched]
    rejected_fuzzy = [
        {
            "rule_id": m.rule.rule_id,
            "observed_heading": r.observed_heading,
            "matched_alias": r.matched_alias,
            "ratio": r.ratio,
            "reason": r.reason,
        }
        for _p, _d, m in matches
        for r in m.rejected_fuzzy
    ]
    ablation = {
        "rules_evaluated": len(match_objects),
        "matched_total": len(matched),
        "matched_exact_equality": sum(1 for m in matched if m.method == "exact_equality"),
        "matched_normalized_substring": sum(
            1 for m in matched if m.method == "normalized_substring"
        ),
        "matched_token_overlap": sum(1 for m in matched if m.method == "token_overlap"),
        "matched_fuzzy": sum(1 for m in matched if m.method == "fuzzy"),
        "rejected_fuzzy_candidates": len(rejected_fuzzy),
        "rejected_fuzzy_examples": rejected_fuzzy[:10],
        "unmatched_required": sum(1 for m in match_objects if not m.matched and m.rule.required),
        "unmatched_recommended": sum(
            1 for m in match_objects if not m.matched and not m.rule.required
        ),
        "note": (
            "equality и substring считаются раздельно; fuzzy принимается только с"
            " discriminative-token evidence — см. section_matches.jsonl"
        ),
    }

    empty_pages = sum(
        1
        for pages in pages_by_document.values()
        for p in pages
        if int(p.get("char_count") or 0) == 0
    )
    near_empty = sum(
        1
        for pages in pages_by_document.values()
        for p in pages
        if 0 < int(p.get("char_count") or 0) < 32
    )

    false_positive_candidates = [
        f.finding_id for f in result.findings if is_false_positive_review_candidate(f)
    ]

    scores = [s.document_integrity_priority_score for s in result.document_scores]
    return {
        "p1_version": P1_VERSION,
        "documents_analyzed": len(result.document_scores),
        "projects_analyzed": len(result.project_scores),
        "findings_total": len(result.findings),
        "findings_by_type": dict(sorted(by_type.items())),
        "findings_by_severity": dict(sorted(by_severity.items())),
        "findings_by_document": dict(sorted(by_document.items())),
        "score_distribution": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "mean": round(sum(scores) / len(scores), 1) if scores else None,
            "documents": {
                s.document_id: s.document_integrity_priority_score for s in result.document_scores
            },
        },
        "page_quality": {"empty_pages": empty_pages, "near_empty_pages": near_empty},
        "section_matching_ablation": ablation,
        "section_matches_serialized": len(result.section_matches),
        "package_profiles": package_profiles,
        "package_checks_skipped": package_checks_skipped,
        "false_positive_review_candidates": false_positive_candidates,
        "false_positive_review_candidate_count": len(false_positive_candidates),
        "evaluation_note": (
            "4 проекта: ML accuracy не заявляется; метрики описывают coverage и"
            " распределения, а не качество классификации"
        ),
    }


_TEMPLATE_HUMAN_FIELDS = ("expert_decision", "corrected_severity", "expert_comment", "reviewer_id")


def _write_outputs(options: P1Options, result: P1RunResult) -> None:
    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    def _write_jsonl(name: str, records: list[dict[str, Any]]) -> None:
        with (output_dir / name).open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")

    _write_jsonl("project_scores.jsonl", [s.model_dump(mode="json") for s in result.project_scores])
    _write_jsonl(
        "document_scores.jsonl", [s.model_dump(mode="json") for s in result.document_scores]
    )
    _write_jsonl("findings.jsonl", [f.model_dump(mode="json") for f in result.findings])
    _write_jsonl("section_matches.jsonl", result.section_matches)
    (output_dir / "metrics.json").write_text(
        json.dumps(result.metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    snapshot = config_snapshot()
    snapshot["taxonomy"] = taxonomy_as_dict()
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(render_p1_report(result), encoding="utf-8")

    _merge_review_template(options, result, output_dir)


def _merge_review_template(options: P1Options, result: P1RunResult, output_dir: Path) -> None:
    """Create/update the expert review template WITHOUT losing human decisions.

    Existing rows are matched by (content-stable) finding_id; human-filled
    fields are preserved verbatim. Rows whose findings no longer exist are
    moved to a stale-audit file next to the P1 outputs, never silently dropped.
    """
    template_path = options.annotations_root / "p1_review_template.jsonl"
    existing: dict[str, dict[str, Any]] = {}
    if template_path.exists():
        for line in template_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                existing[str(row.get("finding_id"))] = row

    def _empty_row(finding_id: str) -> dict[str, Any]:
        return {
            "finding_id": finding_id,
            "expert_decision": None,
            "corrected_severity": None,
            "expert_comment": None,
            "reviewed_at": None,
            "reviewer_id": None,
        }

    def _has_human_data(row: dict[str, Any]) -> bool:
        return any(row.get(field_name) is not None for field_name in _TEMPLATE_HUMAN_FIELDS)

    current_ids = [finding.finding_id for finding in result.findings]
    current_set = set(current_ids)
    rows: list[dict[str, Any]] = []
    preserved = 0
    for finding_id in current_ids:
        old = existing.get(finding_id)
        if old is not None:
            merged = _empty_row(finding_id)
            for key in (*_TEMPLATE_HUMAN_FIELDS, "reviewed_at"):
                if old.get(key) is not None:
                    merged[key] = old[key]
            if _has_human_data(old):
                preserved += 1
            rows.append(merged)
        else:
            rows.append(_empty_row(finding_id))

    stale = [row for finding_id, row in existing.items() if finding_id not in current_set]

    with template_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
    if stale:
        stale_path = output_dir / "review_template_stale.jsonl"
        with stale_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in stale:
                handle.write(json.dumps(row, ensure_ascii=False))
                handle.write("\n")

    result.review_template_path = template_path
    result.review_template_created = not existing
    result.review_template_preserved_decisions = preserved
    result.review_template_stale_rows = len(stale)
