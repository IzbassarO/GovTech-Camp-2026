"""Read-only artifact repository.

Loads the accepted curated dataset and pillar result artifacts from disk
ONCE and caches them in memory (the artifacts are static and deterministic).
The rest of the API only ever sees plain dicts from here — never file
handles or paths. Missing artifacts degrade gracefully to "unavailable".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from dalel.api.config import (
    META_RESULTS_SUBDIR,
    PILLARS,
    PillarDescriptor,
    Settings,
    get_settings,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class PillarArtifacts:
    descriptor: PillarDescriptor
    available: bool = False
    findings: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    project_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    # P2 extras (empty for other pillars):
    assessments: dict[str, dict[str, Any]] = field(default_factory=dict)  # by id
    requirements: dict[str, dict[str, Any]] = field(default_factory=dict)  # by id
    # P2 assessments grouped per project (for pillar-card metrics):
    assessments_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # P3 per-project aggregate stats (empty for other pillars):
    p3_project_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    # P4 entity-graph artifacts grouped per project (empty for other pillars):
    p4_entities_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    p4_edges_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    p4_resolution_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    p4_suppressed_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    p4_entities_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    report_markdown: str = ""


@dataclass
class MetaArtifacts:
    """Project-level synthesis artifacts, kept outside finding pillars."""

    available: bool = False
    project_assessments: dict[str, dict[str, Any]] = field(default_factory=dict)
    pillar_contributions_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    feature_contributions_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    report_markdown: str = ""

    def assessment(self, project_id: str) -> dict[str, Any] | None:
        return self.project_assessments.get(project_id)


@dataclass
class ArtifactStore:
    settings: Settings
    projects: list[dict[str, Any]] = field(default_factory=list)
    documents_by_project: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    documents_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    dataset_version: str = "v1"
    dataset_fingerprint: str | None = None
    pillars: dict[str, PillarArtifacts] = field(default_factory=dict)
    meta: MetaArtifacts = field(default_factory=MetaArtifacts)

    # ---- lookups -------------------------------------------------------------
    def project(self, project_id: str) -> dict[str, Any] | None:
        for record in self.projects:
            if str(record["project_id"]) == project_id:
                return record
        return None

    def project_documents(self, project_id: str) -> list[dict[str, Any]]:
        return self.documents_by_project.get(project_id, [])

    def document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents_by_id.get(document_id)

    def pillar(self, key: str) -> PillarArtifacts | None:
        return self.pillars.get(key)

    def all_findings(self) -> list[tuple[PillarArtifacts, dict[str, Any]]]:
        pairs: list[tuple[PillarArtifacts, dict[str, Any]]] = []
        for pillar in self.pillars.values():
            for finding in pillar.findings:
                pairs.append((pillar, finding))
        return pairs

    def project_findings(self, project_id: str) -> list[tuple[PillarArtifacts, dict[str, Any]]]:
        return [
            (pillar, finding)
            for pillar, finding in self.all_findings()
            if str(finding.get("project_id")) == project_id
        ]


def _load_pillar(descriptor: PillarDescriptor, results_dir: Path) -> PillarArtifacts:
    base = results_dir / descriptor.results_subdir
    findings = _read_jsonl(base / "findings.jsonl")
    metrics = _read_json(base / "metrics.json")
    available = (base / "metrics.json").is_file()
    project_scores = {
        str(record["project_id"]): record for record in _read_jsonl(base / "project_scores.jsonl")
    }
    document_scores = {
        str(record["document_id"]): record for record in _read_jsonl(base / "document_scores.jsonl")
    }
    artifacts = PillarArtifacts(
        descriptor=descriptor,
        available=available,
        findings=findings,
        metrics=metrics,
        project_scores=project_scores,
        document_scores=document_scores,
    )
    report_path = base / "report.md"
    if report_path.is_file():
        artifacts.report_markdown = report_path.read_text(encoding="utf-8")
    if descriptor.key == "p2":
        assessments = _read_jsonl(base / "assessments.jsonl")
        artifacts.assessments = {str(r["assessment_id"]): r for r in assessments}
        artifacts.requirements = {
            str(record["requirement_id"]): record
            for record in _read_jsonl(base / "requirements_snapshot.jsonl")
        }
        for record in assessments:
            artifacts.assessments_by_project.setdefault(str(record["project_id"]), []).append(
                record
            )
    if descriptor.key == "p3":
        artifacts.p3_project_stats = _p3_project_stats(base)
    if descriptor.key == "p4":
        _load_p4_graph(artifacts, base)
    return artifacts


def _load_p4_graph(artifacts: PillarArtifacts, base: Path) -> None:
    """Load P4 entity-graph artifacts, grouped per project for the coherence
    view. Absent files degrade to empty (P4 simply stays unavailable)."""
    for record in _read_jsonl(base / "entities.jsonl"):
        project_id = str(record["project_id"])
        artifacts.p4_entities_by_project.setdefault(project_id, []).append(record)
        artifacts.p4_entities_by_id[str(record["entity_id"])] = record
    for record in _read_jsonl(base / "edges.jsonl"):
        artifacts.p4_edges_by_project.setdefault(str(record["project_id"]), []).append(record)
    for record in _read_jsonl(base / "resolution_decisions.jsonl"):
        artifacts.p4_resolution_by_project.setdefault(str(record["project_id"]), []).append(record)
    for record in _read_jsonl(base / "suppressed_comparisons.jsonl"):
        artifacts.p4_suppressed_by_project.setdefault(str(record["project_id"]), []).append(record)


def _p3_project_stats(base: Path) -> dict[str, dict[str, int]]:
    """Per-project quantitative-pipeline aggregates (mentions, comparisons,
    aggregation checks, suppressed comparisons)."""
    stats: dict[str, dict[str, int]] = {}

    def _bucket(project_id: str) -> dict[str, int]:
        return stats.setdefault(
            project_id,
            {
                "mentions": 0,
                "comparisons_compared": 0,
                "comparisons_suppressed": 0,
                "aggregation_checks": 0,
                "aggregation_consistent": 0,
            },
        )

    for mention in _read_jsonl(base / "mentions.jsonl"):
        _bucket(str(mention["project_id"]))["mentions"] += 1
    for candidate in _read_jsonl(base / "candidates.jsonl"):
        bucket = _bucket(str(candidate["project_id"]))
        if candidate.get("status") == "compared":
            bucket["comparisons_compared"] += 1
        else:
            bucket["comparisons_suppressed"] += 1
    for check in _read_jsonl(base / "aggregation_checks.jsonl"):
        bucket = _bucket(str(check["project_id"]))
        bucket["aggregation_checks"] += 1
        if check.get("decision") == "consistent":
            bucket["aggregation_consistent"] += 1
    return stats


def _load_meta(results_dir: Path, project_ids: set[str]) -> MetaArtifacts:
    """Load a complete Meta bundle without treating it as a finding pillar.

    Availability is intentionally conservative. A partial output directory is
    not presented as an assessment that passed: all project assessments and
    both exact-decomposition artifacts must exist, satisfy the strict Meta
    schemas and align to curated project IDs. Before promotion, the same
    independent replay used by ``dalel validate-meta`` must also pass.
    """
    from dalel.meta_review.schemas import (
        CalibrationMetadata,
        FeatureContribution,
        MetaFeatureRecord,
        ModelMetadata,
        PillarContribution,
        ProjectMetaAssessment,
    )

    base = results_dir / META_RESULTS_SUBDIR
    assessment_path = base / "project_assessments.jsonl"
    pillar_path = base / "pillar_contributions.jsonl"
    feature_path = base / "feature_contributions.jsonl"
    raw_feature_path = base / "features.jsonl"
    metrics_path = base / "metrics.json"
    snapshot_path = base / "config_snapshot.json"
    calibration_path = base / "calibration_metadata.json"
    model_path = base / "model_metadata.json"
    report_path = base / "report.md"

    required_files = (
        assessment_path,
        pillar_path,
        feature_path,
        raw_feature_path,
        metrics_path,
        snapshot_path,
        calibration_path,
        model_path,
        report_path,
    )
    if not all(path.is_file() for path in required_files):
        return MetaArtifacts()

    try:
        assessments = [
            ProjectMetaAssessment.model_validate(record).model_dump(mode="json")
            for record in _read_jsonl(assessment_path)
        ]
        pillar_contributions = [
            PillarContribution.model_validate(record).model_dump(mode="json")
            for record in _read_jsonl(pillar_path)
        ]
        feature_contributions = [
            FeatureContribution.model_validate(record).model_dump(mode="json")
            for record in _read_jsonl(feature_path)
        ]
        raw_features = [
            MetaFeatureRecord.model_validate(record).model_dump(mode="json")
            for record in _read_jsonl(raw_feature_path)
        ]
        metrics = _read_json(metrics_path)
        _read_json(snapshot_path)
        calibration = CalibrationMetadata.model_validate(_read_json(calibration_path)).model_dump(
            mode="json"
        )
        model = ModelMetadata.model_validate(_read_json(model_path)).model_dump(mode="json")
        report_markdown = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        # Invalid or hand-edited output is not promoted into the API. The CLI
        # validator provides the detailed independent diagnostic.
        return MetaArtifacts()

    artifacts = MetaArtifacts(metrics=metrics)

    assessment_ids: set[str] = set()
    assessment_projects: set[str] = set()
    structurally_valid = True
    for record in assessments:
        project_id = str(record.get("project_id", ""))
        assessment_id = str(record.get("assessment_id", ""))
        if (
            not project_id
            or project_id in assessment_projects
            or not assessment_id
            or assessment_id in assessment_ids
        ):
            structurally_valid = False
            continue
        assessment_projects.add(project_id)
        assessment_ids.add(assessment_id)
        artifacts.project_assessments[project_id] = record

    for record in pillar_contributions:
        project_id = str(record.get("project_id", ""))
        if not project_id or project_id not in project_ids:
            structurally_valid = False
            continue
        artifacts.pillar_contributions_by_project.setdefault(project_id, []).append(record)
    for record in feature_contributions:
        project_id = str(record.get("project_id", ""))
        if not project_id or project_id not in project_ids:
            structurally_valid = False
            continue
        artifacts.feature_contributions_by_project.setdefault(project_id, []).append(record)

    raw_feature_projects = {str(record["project_id"]) for record in raw_features}
    aligned = bool(project_ids) and assessment_projects == project_ids
    decomposed = all(
        artifacts.pillar_contributions_by_project.get(project_id)
        and artifacts.feature_contributions_by_project.get(project_id)
        for project_id in project_ids
    )
    nested_pillars = {
        str(item["contribution_id"]): item
        for assessment in assessments
        for item in assessment["pillar_contributions"]
    }
    separate_pillars = {str(item["contribution_id"]): item for item in pillar_contributions}
    nested_features = {
        str(item["contribution_id"]): item
        for assessment in assessments
        for item in assessment["feature_contributions"]
    }
    separate_features = {str(item["contribution_id"]): item for item in feature_contributions}
    no_duplicate_decomposition_ids = (
        len(nested_pillars) == sum(len(a["pillar_contributions"]) for a in assessments)
        and len(separate_pillars) == len(pillar_contributions)
        and len(nested_features) == sum(len(a["feature_contributions"]) for a in assessments)
        and len(separate_features) == len(feature_contributions)
    )
    decomposition_matches = (
        nested_pillars == separate_pillars and nested_features == separate_features
    )
    production_metadata_matches = all(
        assessment["calibration_metadata"] == calibration and assessment["model_metadata"] == model
        for assessment in assessments
    )
    artifacts.report_markdown = report_markdown
    structurally_available = (
        structurally_valid
        and aligned
        and raw_feature_projects == project_ids
        and decomposed
        and no_duplicate_decomposition_ids
        and decomposition_matches
        and production_metadata_matches
    )
    replay_valid = False
    if structurally_available:
        try:
            from dalel.meta_review.validation import validate_meta

            validation = validate_meta(
                results_dir / "p1/v1",
                results_dir / "p2/v1",
                results_dir / "p3/v1",
                results_dir / "p4/v1",
                base,
                results_dir.parent / "annotations",
            )
            replay_valid = validation.ok
        except (OSError, UnicodeDecodeError, ValueError):
            replay_valid = False
    artifacts.available = structurally_available and replay_valid
    return artifacts


def _build_store(settings: Settings) -> ArtifactStore:
    curated = settings.curated_dir
    store = ArtifactStore(settings=settings)
    store.projects = _read_jsonl(curated / "projects.jsonl")

    documents = _read_jsonl(curated / "documents.jsonl")
    for document in documents:
        project_id = str(document["project_id"])
        store.documents_by_project.setdefault(project_id, []).append(document)
        store.documents_by_id[str(document["document_id"])] = document
    for docs in store.documents_by_project.values():
        docs.sort(key=lambda d: str(d["document_id"]))

    build_report = _read_json(curated / "build_report.json")
    store.dataset_version = str(build_report.get("dataset_version") or "v1")
    store.dataset_fingerprint = build_report.get("input_fingerprint")

    for descriptor in PILLARS:
        store.pillars[descriptor.key] = _load_pillar(descriptor, settings.results_dir)
    store.meta = _load_meta(
        settings.results_dir,
        {str(project["project_id"]) for project in store.projects},
    )
    return store


@lru_cache(maxsize=1)
def _cached_store(data_dir: str) -> ArtifactStore:
    return _build_store(get_settings())


def get_store() -> ArtifactStore:
    """Cached, process-wide artifact store keyed by the data directory."""
    settings = get_settings()
    return _cached_store(str(settings.data_dir))


def reset_store_cache() -> None:
    """Testing hook: drop the cached store so a new data dir is re-read."""
    _cached_store.cache_clear()
