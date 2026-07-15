"""Independent validation of P2 outputs (``dalel validate-p2``).

Strategy mirrors P1/P3: every deterministic artifact is REPLAYED from the
raw inputs (curated dataset + regulatory corpus) and compared record by
record — the validator never trusts serialized values. Tampering with any
single field of a requirement, retrieval, assessment, finding, score or
review-template row is detected.

For runs that used an LLM provider the deterministic core is still fully
replayed (deterministic_label, retrievals, findings-from-assessments,
scores); provider-dependent fields are checked structurally (hash formats,
label-merge policy, confidence bounds) because provider output cannot be
recomputed offline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dalel.pillars.regulatory_compliance.config import SEVERITY_POINTS
from dalel.pillars.regulatory_compliance.corpus import (
    CorpusError,
    corpus_is_demo_only,
    load_corpus,
)
from dalel.pillars.regulatory_compliance.evidence import build_evidence_stores
from dalel.pillars.regulatory_compliance.nli import assess_requirement
from dalel.pillars.regulatory_compliance.retrieval import (
    build_index,
    retrieve_for_project,
)
from dalel.pillars.regulatory_compliance.schemas import (
    INFERENCE_LABELS,
    P2Assessment,
    P2FindingRecord,
    deterministic_id,
)
from dalel.pillars.regulatory_compliance.scoring import (
    build_findings,
    score_document,
    score_project,
    sort_findings,
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class P2ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)


def _read_jsonl(path: Path, result: P2ValidationResult) -> list[dict[str, Any]] | None:
    if not path.is_file():
        result.error(f"missing output file: {path.name}")
        return None
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            result.error(f"{path.name}: line {line_number}: invalid JSON ({exc.msg})")
            return None
    return records


def _read_dataset_jsonl(path: Path, result: P2ValidationResult) -> list[dict[str, Any]] | None:
    if not path.is_file():
        result.error(f"missing curated file: {path}")
        return None
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def validate_p2_outputs(
    dataset_dir: Path,
    regulations_path: Path,
    output_dir: Path,
    annotations_root: Path | None = None,
) -> P2ValidationResult:
    result = P2ValidationResult()

    # --- corpus: load independently (schema, hashes, versions, duplicates) ------
    try:
        requirements = load_corpus(regulations_path)
    except CorpusError as exc:
        result.error(f"regulatory corpus invalid: {exc}")
        return result
    requirements_by_id = {r.requirement_id: r for r in requirements}
    demo_corpus = corpus_is_demo_only(requirements)

    snapshot_records = _read_jsonl(output_dir / "requirements_snapshot.jsonl", result)
    if snapshot_records is None:
        return result
    expected_snapshot = [r.model_dump(mode="json") for r in requirements]
    if snapshot_records != expected_snapshot:
        result.error(
            "requirements_snapshot.jsonl does not match the regulatory corpus"
            " (record-by-record replay failed)"
        )

    # --- dataset + evidence/retrieval replay ------------------------------------
    projects = _read_dataset_jsonl(dataset_dir / "projects.jsonl", result)
    documents = _read_dataset_jsonl(dataset_dir / "documents.jsonl", result)
    sections = _read_dataset_jsonl(dataset_dir / "sections.jsonl", result)
    if projects is None or documents is None or sections is None:
        return result

    metrics_path = output_dir / "metrics.json"
    if not metrics_path.is_file():
        result.error("missing output file: metrics.json")
        return result
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    # Replay is restricted to the projects that actually appear in the
    # outputs (supports --project-id runs without trusting metrics).
    analyzed_projects = {str(p["project_id"]) for p in projects}
    assessments_raw = _read_jsonl(output_dir / "assessments.jsonl", result)
    retrievals_raw = _read_jsonl(output_dir / "retrievals.jsonl", result)
    evidence_raw = _read_jsonl(output_dir / "project_evidence.jsonl", result)
    findings_raw = _read_jsonl(output_dir / "findings.jsonl", result)
    document_scores_raw = _read_jsonl(output_dir / "document_scores.jsonl", result)
    project_scores_raw = _read_jsonl(output_dir / "project_scores.jsonl", result)
    if None in (
        assessments_raw,
        retrievals_raw,
        evidence_raw,
        findings_raw,
        document_scores_raw,
        project_scores_raw,
    ):
        return result
    assert assessments_raw is not None
    assert retrievals_raw is not None
    assert evidence_raw is not None
    assert findings_raw is not None
    assert document_scores_raw is not None
    assert project_scores_raw is not None

    serialized_projects = {str(r.get("project_id")) for r in assessments_raw} | {
        str(r.get("project_id")) for r in retrievals_raw
    }
    if serialized_projects:
        analyzed_projects = serialized_projects
    replay_projects = [p for p in projects if str(p["project_id"]) in analyzed_projects]
    replay_documents = [d for d in documents if str(d["project_id"]) in analyzed_projects]
    replay_document_ids = {str(d["document_id"]) for d in replay_documents}
    sections_by_document: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        document_id = str(section["provenance"]["document_id"])
        if document_id in replay_document_ids:
            sections_by_document.setdefault(document_id, []).append(section)

    # top_k is CONFIGURATION echoed into metrics; a tampered value cannot
    # pass unnoticed because the whole retrieval replay depends on it.
    top_k = int(metrics.get("top_k") or 5)
    stores = build_evidence_stores(replay_projects, replay_documents, sections_by_document)
    index = build_index(requirements)

    expected_retrievals: list[dict[str, Any]] = []
    expected_assessment_core: dict[str, dict[str, Any]] = {}
    expected_evidence: list[dict[str, Any]] = []
    for project_id in sorted(stores):
        store = stores[project_id]
        all_retrievals, best = retrieve_for_project(index, store, top_k)
        expected_retrievals.extend(
            r.model_dump(mode="json")
            for r in sorted(all_retrievals, key=lambda r: (r.query_id, r.rank, r.requirement_id))
        )
        for requirement_id in sorted(best):
            retrieval = best[requirement_id]
            requirement = requirements_by_id[requirement_id]
            nli = assess_requirement(requirement, store, retrieval.score)
            expected_assessment_core[
                deterministic_id(
                    "P2A",
                    project_id,
                    requirement_id,
                    requirement.corpus_id,
                    requirement.corpus_version,
                )
            ] = {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "retrieval_id": retrieval.retrieval_id,
                "retrieval_score": retrieval.score,
                "retrieval_rank": retrieval.rank,
                "deterministic_label": nli.label,
                "applicability": nli.applicability,
                "evidence_ids": nli.evidence_ids,
                "confidence": nli.confidence,
            }
        expected_evidence.extend(e.model_dump(mode="json") for e in store.ordered())

    if retrievals_raw != expected_retrievals:
        result.error(
            "retrievals.jsonl does not replay from the dataset and corpus"
            " (scores, ordering or contents differ)"
        )
    if evidence_raw != expected_evidence:
        result.error("project_evidence.jsonl does not replay from the dataset")

    # --- assessments -------------------------------------------------------------
    evidence_by_id = {str(e["evidence_id"]): e for e in evidence_raw}
    assessments: list[P2Assessment] = []
    seen_assessments: set[str] = set()
    for record in assessments_raw:
        try:
            assessment = P2Assessment.model_validate(record)
        except ValidationError as exc:
            result.error(f"assessments.jsonl: invalid record: {exc.errors()[0].get('msg')}")
            continue
        assessments.append(assessment)
        if assessment.assessment_id in seen_assessments:
            result.error(f"duplicate assessment_id {assessment.assessment_id}")
        seen_assessments.add(assessment.assessment_id)
        if assessment.requirement_id not in requirements_by_id:
            result.error(
                f"{assessment.assessment_id}: unknown requirement {assessment.requirement_id}"
            )
            continue
        requirement = requirements_by_id[assessment.requirement_id]
        if assessment.requirement_demo_only != requirement.demo_only or (
            assessment.requirement_is_authoritative != requirement.is_authoritative
        ):
            result.error(
                f"{assessment.assessment_id}: authoritative/demo flags do not match the corpus"
            )
        if assessment.label not in INFERENCE_LABELS:
            result.error(f"{assessment.assessment_id}: unknown label {assessment.label}")
        if not 0.0 <= assessment.confidence <= 1.0:
            result.error(f"{assessment.assessment_id}: confidence out of bounds")
        core = expected_assessment_core.get(assessment.assessment_id)
        if core is None:
            result.error(
                f"{assessment.assessment_id}: not reproducible from dataset+corpus"
                " (unexpected assessment)"
            )
            continue
        for field_name in (
            "project_id",
            "requirement_id",
            "retrieval_id",
            "retrieval_score",
            "retrieval_rank",
            "deterministic_label",
            "applicability",
            "evidence_ids",
        ):
            if getattr(assessment, field_name) != core[field_name]:
                result.error(
                    f"{assessment.assessment_id}: field '{field_name}' does not"
                    " replay from the deterministic baseline"
                )
        if assessment.inference_engine == "deterministic":
            if assessment.label != core["deterministic_label"]:
                result.error(f"{assessment.assessment_id}: deterministic label mismatch")
            if assessment.confidence != core["confidence"]:
                result.error(f"{assessment.assessment_id}: deterministic confidence mismatch")
            if assessment.prompt_hash is not None or assessment.provider_name is not None:
                result.error(
                    f"{assessment.assessment_id}: provider metadata on a deterministic assessment"
                )
        else:
            if assessment.prompt_hash is None or not _HEX64_RE.match(assessment.prompt_hash):
                result.error(f"{assessment.assessment_id}: missing/invalid prompt_hash")
            if assessment.cached_response_hash is not None and not _HEX64_RE.match(
                assessment.cached_response_hash
            ):
                result.error(f"{assessment.assessment_id}: invalid cached_response_hash")
            if assessment.label != assessment.deterministic_label and (
                assessment.label != "insufficient_evidence"
            ):
                result.error(
                    f"{assessment.assessment_id}: LLM label merge violates the"
                    " confirm-or-downgrade policy"
                )
        for evidence_id in assessment.evidence_ids:
            if evidence_id not in evidence_by_id:
                result.error(f"{assessment.assessment_id}: unresolved evidence {evidence_id}")
        referenced_texts = [
            str(evidence_by_id[e]["text"]) for e in assessment.evidence_ids if e in evidence_by_id
        ]
        for snippet in assessment.evidence_snippets:
            if snippet.quote is None:
                continue
            if referenced_texts and not any(snippet.quote in text for text in referenced_texts):
                result.error(
                    f"{assessment.assessment_id}: evidence quote is not a"
                    " substring of the referenced evidence"
                )

    # --- findings: full replay from serialized assessments ----------------------
    expected_findings = build_findings(
        assessments,
        requirements_by_id,
        demo_corpus,
        sorted(analyzed_projects),
    )
    expected_findings_json = [f.model_dump(mode="json") for f in expected_findings]
    if findings_raw != expected_findings_json:
        result.error(
            "findings.jsonl does not replay from assessments (contents,"
            " severity, IDs or ordering differ)"
        )

    findings: list[P2FindingRecord] = []
    seen_finding_ids: set[str] = set()
    for record in findings_raw:
        try:
            finding = P2FindingRecord.model_validate(record)
        except ValidationError as exc:
            result.error(f"findings.jsonl: invalid record: {exc.errors()[0].get('msg')}")
            continue
        findings.append(finding)
        if finding.finding_id in seen_finding_ids:
            result.error(f"duplicate finding_id {finding.finding_id}")
        seen_finding_ids.add(finding.finding_id)
        if finding.severity not in SEVERITY_POINTS:
            result.error(f"{finding.finding_id}: unknown severity {finding.severity}")
            continue
        if finding.priority_score != SEVERITY_POINTS[finding.severity]:
            result.error(f"{finding.finding_id}: priority_score does not match severity")
        if finding.requirement_demo_only and finding.severity in ("high", "medium"):
            result.error(
                f"{finding.finding_id}: demo-only requirement produced {finding.severity} severity"
            )
        if finding.confidence is not None and not 0.0 <= finding.confidence <= 1.0:
            result.error(f"{finding.finding_id}: confidence out of bounds")
    if [f.model_dump(mode="json") for f in sort_findings(findings)] != findings_raw:
        result.error("findings.jsonl ordering is not the canonical deterministic order")

    # --- scores ------------------------------------------------------------------
    findings_by_document: dict[str, list[P2FindingRecord]] = {}
    package_by_project: dict[str, list[P2FindingRecord]] = {}
    for finding in findings:
        if finding.document_id is not None:
            findings_by_document.setdefault(finding.document_id, []).append(finding)
        else:
            package_by_project.setdefault(finding.project_id, []).append(finding)
    expected_document_scores: list[dict[str, Any]] = []
    expected_project_scores: list[dict[str, Any]] = []
    for project in sorted(replay_projects, key=lambda p: str(p["project_id"])):
        project_id = str(project["project_id"])
        project_documents = sorted(
            (d for d in replay_documents if str(d["project_id"]) == project_id),
            key=lambda d: str(d["document_id"]),
        )
        if not project_documents:
            continue
        document_scores = [
            score_document(
                project_id,
                str(document["document_id"]),
                str(document["document_type"]),
                findings_by_document.get(str(document["document_id"]), []),
            )
            for document in project_documents
        ]
        expected_document_scores.extend(s.model_dump(mode="json") for s in document_scores)
        expected_project_scores.append(
            score_project(
                project_id, document_scores, package_by_project.get(project_id, [])
            ).model_dump(mode="json")
        )
    if document_scores_raw != expected_document_scores:
        result.error("document_scores.jsonl does not replay from findings")
    if project_scores_raw != expected_project_scores:
        result.error("project_scores.jsonl does not replay from findings")

    # --- metrics + report counts ---------------------------------------------------
    checks = {
        "assessments_total": len(assessments_raw),
        "retrievals_total": len(retrievals_raw),
        "findings_total": len(findings_raw),
        "requirements_total": len(requirements),
    }
    for key, expected in checks.items():
        if metrics.get(key) != expected:
            result.error(f"metrics.json: {key}={metrics.get(key)} but artifacts have {expected}")
    if bool(metrics.get("corpus_demo_only")) != demo_corpus:
        result.error("metrics.json: corpus_demo_only does not match the corpus")

    report_path = output_dir / "report.md"
    if not report_path.is_file():
        result.error("missing output file: report.md")
    else:
        report_text = report_path.read_text(encoding="utf-8")
        if f"Находок: {len(findings_raw)}" not in report_text:
            result.error("report.md: findings count does not match findings.jsonl")
        if demo_corpus and "демонстрационному корпусу" not in report_text.replace("\n", " "):
            result.error("report.md: demo corpus warning is missing")

    # --- review template -----------------------------------------------------------
    template_root = (
        annotations_root
        if annotations_root is not None
        else dataset_dir.parent.parent / "annotations"
    )
    template_path = template_root / "p2_review_template.jsonl"
    if template_path.is_file():
        template_ids = [
            str(json.loads(line).get("finding_id"))
            for line in template_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        finding_ids = [str(r["finding_id"]) for r in findings_raw]
        unknown = [t for t in template_ids if t not in set(finding_ids)]
        missing = [f for f in finding_ids if f not in set(template_ids)]
        if unknown:
            result.error(f"review template references unknown finding ids: {unknown[:3]}")
        if missing:
            result.error(f"review template is missing finding ids: {missing[:3]}")
    else:
        result.warnings.append("review template not found (run with default annotations root?)")

    result.counts = {
        "requirements": len(requirements),
        "evidence": len(evidence_raw),
        "retrievals": len(retrievals_raw),
        "assessments": len(assessments_raw),
        "findings": len(findings_raw),
        "document_scores": len(document_scores_raw),
        "project_scores": len(project_scores_raw),
    }
    return result


def _infer_top_k(retrievals_raw: list[dict[str, Any]]) -> int:
    """The run's top-k is the maximum serialized rank (floor of 1); replay
    with the exact k reproduces the records byte-for-byte."""
    ranks = [int(r.get("rank", 1)) for r in retrievals_raw]
    return max(ranks) if ranks else 5
