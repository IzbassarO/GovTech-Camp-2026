"""Independent Meta recomputation and material-tamper validation."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from dalel.meta_review.artifacts import PillarArtifactBundle
from dalel.meta_review.config import SCORE_CAP, config_snapshot
from dalel.meta_review.pipeline import MetaRunError, compute_meta
from dalel.meta_review.reports import render_meta_report
from dalel.meta_review.schemas import (
    CalibrationMetadata,
    FeatureContribution,
    MetaFeatureRecord,
    ModelMetadata,
    PillarContribution,
    ProjectMetaAssessment,
)

_OUTPUT_FILES = (
    "features.jsonl",
    "project_assessments.jsonl",
    "pillar_contributions.jsonl",
    "feature_contributions.jsonl",
    "metrics.json",
    "config_snapshot.json",
    "calibration_metadata.json",
    "model_metadata.json",
    "report.md",
)
_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*__[0-9a-f]{12}$")
T = TypeVar("T", bound=BaseModel)


@dataclass
class MetaValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_model(path: Path, model: type[T]) -> T:
    return model.model_validate(_read_json(path))


def _read_jsonl(path: Path, model: type[T]) -> list[T]:
    records: list[T] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(model.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"{path.name}: line {line_number}: {exc}") from exc
    return records


def _dump(records: Sequence[BaseModel]) -> list[dict[str, Any]]:
    return [record.model_dump(mode="json") for record in records]


def _find_forbidden(value: Any, location: str = "root") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            child_location = f"{location}.{key}"
            if lowered in {"timestamp", "created_at", "updated_at", "reviewed_at"}:
                errors.append(f"timestamp field is forbidden: {child_location}")
            errors.extend(_find_forbidden(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_find_forbidden(child, f"{location}[{index}]"))
    elif isinstance(value, str) and (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)):
        errors.append(f"local path is forbidden: {location}")
    return errors


def _validate_arithmetic(
    assessments: list[ProjectMetaAssessment], result: MetaValidationResult
) -> None:
    for assessment in assessments:
        feature_by_id = {item.contribution_id: item for item in assessment.feature_contributions}
        if len(feature_by_id) != len(assessment.feature_contributions):
            result.error(f"{assessment.project_id}: duplicate feature contribution ID")
        for item in assessment.feature_contributions:
            for stable_id in (item.feature_id, item.contribution_id):
                if not _ID_RE.fullmatch(stable_id):
                    result.error(f"{assessment.project_id}: invalid stable ID {stable_id}")
        for pillar in assessment.pillar_contributions:
            expected_subtotal = round(
                pillar.raw_subtotal + pillar.discount_amount + pillar.cap_adjustment, 2
            )
            if expected_subtotal != pillar.subtotal:
                result.error(f"{assessment.project_id}/{pillar.pillar_id}: subtotal mismatch")
            applied_sum = round(
                sum(
                    feature_by_id[item_id].contribution
                    for item_id in pillar.feature_contribution_ids
                ),
                2,
            )
            if applied_sum != pillar.subtotal:
                result.error(
                    f"{assessment.project_id}/{pillar.pillar_id}: feature contributions do not sum"
                )
            if pillar.subtotal > pillar.cap:
                result.error(f"{assessment.project_id}/{pillar.pillar_id}: cap exceeded")
            if (
                pillar.pillar_id == "P2"
                and pillar.available
                and (pillar.discount_factor > 1.0 or pillar.cap > 15.0)
            ):
                result.error(f"{assessment.project_id}/P2: synthetic safeguard invalid")
        expected_final = round(
            assessment.base_score
            + sum(item.contribution for item in assessment.feature_contributions)
            + assessment.uncertainty_adjustment
            + assessment.global_cap_adjustment,
            2,
        )
        if expected_final != assessment.review_priority_score:
            result.error(f"{assessment.project_id}: final score decomposition mismatch")
        if assessment.review_priority_score > SCORE_CAP:
            result.error(f"{assessment.project_id}: global score cap exceeded")
        if assessment.calibrated_probability is not None:
            result.error(f"{assessment.project_id}: unsupported calibrated probability")
        if assessment.shap_contributions is not None:
            result.error(f"{assessment.project_id}: unsupported production SHAP")


def _validate_ids_and_references(
    features: list[MetaFeatureRecord],
    contributions: list[FeatureContribution],
    pillars: list[PillarContribution],
    assessments: list[ProjectMetaAssessment],
    bundles: dict[str, PillarArtifactBundle],
    result: MetaValidationResult,
) -> None:
    id_groups: tuple[tuple[str, list[str]], ...] = (
        ("feature", [item.feature_id for item in features]),
        ("feature contribution", [item.contribution_id for item in contributions]),
        ("pillar contribution", [item.contribution_id for item in pillars]),
        ("assessment", [item.assessment_id for item in assessments]),
    )
    for label, identifiers in id_groups:
        if len(identifiers) != len(set(identifiers)):
            result.error(f"duplicate {label} ID")
        for identifier in identifiers:
            if not _ID_RE.fullmatch(identifier):
                result.error(f"invalid stable {label} ID: {identifier}")

    findings: dict[str, dict[str, str]] = {}
    for pillar, bundle in bundles.items():
        for finding in bundle.findings:
            findings[str(finding["finding_id"])] = {
                "pillar": pillar,
                "project_id": str(finding["project_id"]),
            }
    traceable: list[MetaFeatureRecord | FeatureContribution] = [*features, *contributions]
    for item in traceable:
        for finding_id in item.source_finding_ids:
            source = findings.get(finding_id)
            if source is None:
                result.error(f"{item.feature_id}: unknown source finding ID {finding_id}")
                continue
            if source["pillar"] != item.pillar_source:
                result.error(f"{item.feature_id}: source finding belongs to another pillar")
            if source["project_id"] != item.project_id:
                result.error(f"{item.feature_id}: source finding belongs to another project")
        for artifact_id in item.source_artifact_ids:
            if not artifact_id.startswith(f"{item.pillar_source}:") or "/" in artifact_id:
                result.error(f"{item.feature_id}: invalid source artifact ID {artifact_id}")


def validate_meta(
    p1_dir: Path,
    p2_dir: Path,
    p3_dir: Path,
    p4_dir: Path,
    output_dir: Path,
    annotations_root: Path = Path("data/annotations"),
) -> MetaValidationResult:
    result = MetaValidationResult()
    for name in _OUTPUT_FILES:
        if not (output_dir / name).is_file():
            result.error(f"missing output artifact: {name}")
    if not result.ok:
        return result
    try:
        expected, bundles = compute_meta(p1_dir, p2_dir, p3_dir, p4_dir, annotations_root)
        features = _read_jsonl(output_dir / "features.jsonl", MetaFeatureRecord)
        assessments = _read_jsonl(output_dir / "project_assessments.jsonl", ProjectMetaAssessment)
        pillars = _read_jsonl(output_dir / "pillar_contributions.jsonl", PillarContribution)
        contributions = _read_jsonl(output_dir / "feature_contributions.jsonl", FeatureContribution)
        metrics = _read_json(output_dir / "metrics.json")
        snapshot = _read_json(output_dir / "config_snapshot.json")
        calibration = _read_model(output_dir / "calibration_metadata.json", CalibrationMetadata)
        model = _read_model(output_dir / "model_metadata.json", ModelMetadata)
        report = (output_dir / "report.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        result.error(f"cannot parse Meta outputs: {exc}")
        return result
    except MetaRunError as exc:
        result.error(f"cannot recompute Meta outputs: {exc}")
        return result

    comparisons = (
        ("features", _dump(features), _dump(expected.features)),
        ("project assessments", _dump(assessments), _dump(expected.assessments)),
        ("pillar contributions", _dump(pillars), _dump(expected.pillar_contributions)),
        ("feature contributions", _dump(contributions), _dump(expected.feature_contributions)),
    )
    for label, actual, wanted in comparisons:
        if actual != wanted:
            result.error(f"{label} differ from independent recomputation")
    if metrics != expected.metrics:
        result.error("metrics differ from independent recomputation")
    if snapshot != config_snapshot():
        result.error("config snapshot differs from versioned configuration")
    if expected.calibration_metadata is None or calibration != expected.calibration_metadata:
        result.error("calibration metadata differs from label audit")
    if expected.model_metadata is None or model != expected.model_metadata:
        result.error("model metadata differs from production policy")
    if report != render_meta_report(expected.assessments, expected.metrics):
        result.error("report differs from deterministic rendering or has incorrect counts")

    serialized = {
        "features": _dump(features),
        "assessments": _dump(assessments),
        "pillars": _dump(pillars),
        "contributions": _dump(contributions),
        "metrics": metrics,
        "snapshot": snapshot,
        "calibration": calibration.model_dump(mode="json"),
        "model": model.model_dump(mode="json"),
    }
    for error in _find_forbidden(serialized):
        result.error(error)
    _validate_arithmetic(assessments, result)
    _validate_ids_and_references(features, contributions, pillars, assessments, bundles, result)
    result.counts = {
        "projects": len(assessments),
        "features": len(features),
        "pillar_contributions": len(pillars),
        "feature_contributions": len(contributions),
    }
    return result


validate_meta_outputs = validate_meta
