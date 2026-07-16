"""Deterministic P1--P4 Meta pipeline and artifact writer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dalel.meta_review.artifacts import (
    MetaArtifactError,
    PillarArtifactBundle,
    align_projects,
    load_pillar_artifacts,
)
from dalel.meta_review.calibration import (
    CalibrationInputError,
    production_calibration_metadata,
    production_model_metadata,
    scan_expert_labels,
)
from dalel.meta_review.config import config_snapshot
from dalel.meta_review.coverage import assess_coverage
from dalel.meta_review.features import extract_project_features
from dalel.meta_review.reports import render_meta_report
from dalel.meta_review.schemas import (
    CalibrationMetadata,
    CoverageAssessment,
    FeatureContribution,
    MetaFeatureRecord,
    ModelMetadata,
    PillarContribution,
    ProjectMetaAssessment,
)
from dalel.meta_review.scoring import score_project


class MetaRunError(Exception):
    """Expected Meta execution failure with a concise CLI-safe message."""


@dataclass
class MetaRunResult:
    features: list[MetaFeatureRecord] = field(default_factory=list)
    coverage: list[CoverageAssessment] = field(default_factory=list)
    assessments: list[ProjectMetaAssessment] = field(default_factory=list)
    pillar_contributions: list[PillarContribution] = field(default_factory=list)
    feature_contributions: list[FeatureContribution] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    calibration_metadata: CalibrationMetadata | None = None
    model_metadata: ModelMetadata | None = None


def _load_bundles(
    p1_dir: Path, p2_dir: Path, p3_dir: Path, p4_dir: Path
) -> dict[str, PillarArtifactBundle]:
    paths = {"P1": p1_dir, "P2": p2_dir, "P3": p3_dir, "P4": p4_dir}
    return {pillar: load_pillar_artifacts(pillar, path) for pillar, path in paths.items()}


def _build_metrics(
    result: MetaRunResult,
    bundles: dict[str, PillarArtifactBundle],
    completed_labels: int,
) -> dict[str, Any]:
    from dalel.meta_review import META_SCORING_CONFIG_VERSION, META_VERSION

    scores = [item.review_priority_score for item in result.assessments]
    levels: dict[str, int] = {}
    for item in result.assessments:
        levels[item.review_priority_level] = levels.get(item.review_priority_level, 0) + 1
    ordered = sorted(
        result.assessments, key=lambda item: (-item.review_priority_score, item.project_id)
    )
    return {
        "meta_version": META_VERSION,
        "scoring_config_version": META_SCORING_CONFIG_VERSION,
        "projects_assessed": len(result.assessments),
        "pillars_available": [pillar for pillar, bundle in bundles.items() if bundle.available],
        "pillars_unavailable": [
            pillar for pillar, bundle in bundles.items() if not bundle.available
        ],
        "features_total": len(result.features),
        "positive_feature_contributions": sum(
            1 for item in result.feature_contributions if item.contribution > 0
        ),
        "score_ordering": [item.project_id for item in ordered],
        "score_distribution": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "mean": round(sum(scores) / len(scores), 2) if scores else None,
            "projects": {
                item.project_id: item.review_priority_score for item in result.assessments
            },
        },
        "levels": dict(sorted(levels.items())),
        "mean_evidence_coverage": (
            round(
                sum(item.evidence_coverage for item in result.assessments)
                / len(result.assessments),
                4,
            )
            if result.assessments
            else None
        ),
        "mean_assessment_confidence": (
            round(
                sum(item.assessment_confidence for item in result.assessments)
                / len(result.assessments),
                4,
            )
            if result.assessments
            else None
        ),
        "completed_expert_labels": completed_labels,
        "calibration_status": "not_available_without_expert_labels",
        "production_calibrated_probabilities": 0,
        "production_shap_records": 0,
        "interpretation": (
            "Integrated Review Priority Score orders expert review; it is not legal, "
            "environmental-harm, compliance or permit probability."
        ),
    }


def compute_meta(
    p1_dir: Path,
    p2_dir: Path,
    p3_dir: Path,
    p4_dir: Path,
    annotations_root: Path = Path("data/annotations"),
) -> tuple[MetaRunResult, dict[str, PillarArtifactBundle]]:
    """Pure read/compute phase shared with independent output validation."""
    try:
        bundles = _load_bundles(p1_dir, p2_dir, p3_dir, p4_dir)
        project_ids = align_projects(bundles)
        label_summary = scan_expert_labels(annotations_root)
    except (MetaArtifactError, CalibrationInputError) as exc:
        raise MetaRunError(str(exc)) from exc
    calibration = production_calibration_metadata(label_summary)
    model = production_model_metadata()
    result = MetaRunResult(calibration_metadata=calibration, model_metadata=model)
    for project_id in project_ids:
        features = extract_project_features(project_id, bundles)
        coverage = assess_coverage(project_id, bundles)
        assessment = score_project(project_id, features, coverage, bundles, calibration, model)
        result.features.extend(features)
        result.coverage.append(coverage)
        result.assessments.append(assessment)
        result.pillar_contributions.extend(assessment.pillar_contributions)
        result.feature_contributions.extend(assessment.feature_contributions)
    result.metrics = _build_metrics(result, bundles, label_summary.completed_labels)
    return result, bundles


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def write_meta_outputs(output_dir: Path, result: MetaRunResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        output_dir / "features.jsonl",
        [item.model_dump(mode="json") for item in result.features],
    )
    _write_jsonl(
        output_dir / "project_assessments.jsonl",
        [item.model_dump(mode="json") for item in result.assessments],
    )
    _write_jsonl(
        output_dir / "pillar_contributions.jsonl",
        [item.model_dump(mode="json") for item in result.pillar_contributions],
    )
    _write_jsonl(
        output_dir / "feature_contributions.jsonl",
        [item.model_dump(mode="json") for item in result.feature_contributions],
    )
    (output_dir / "metrics.json").write_text(
        json.dumps(result.metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(config_snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if result.calibration_metadata is None or result.model_metadata is None:
        raise MetaRunError("internal error: calibration metadata is unavailable")
    (output_dir / "calibration_metadata.json").write_text(
        json.dumps(
            result.calibration_metadata.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "model_metadata.json").write_text(
        json.dumps(result.model_metadata.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        render_meta_report(result.assessments, result.metrics), encoding="utf-8"
    )


def run_meta(
    p1_dir: Path,
    p2_dir: Path,
    p3_dir: Path,
    p4_dir: Path,
    output_dir: Path,
    annotations_root: Path = Path("data/annotations"),
) -> MetaRunResult:
    result, _bundles = compute_meta(p1_dir, p2_dir, p3_dir, p4_dir, annotations_root)
    write_meta_outputs(output_dir, result)
    return result
