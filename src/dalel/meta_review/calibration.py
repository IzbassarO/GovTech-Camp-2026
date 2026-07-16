"""Calibration-ready contracts without unsupported production model training."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from dalel.meta_review.config import MIN_EXPERT_LABELS
from dalel.meta_review.schemas import CalibrationMetadata, ModelMetadata


class CalibrationInputError(ValueError):
    """Invalid expert-label or synthetic calibration-test input."""


@dataclass(frozen=True)
class ExpertLabelSummary:
    completed_labels: int
    completed_finding_ids: tuple[str, ...]


class ExperimentalCalibrationFixture(BaseModel):
    """Synthetic payload used only to test a future adapter boundary."""

    model_config = ConfigDict(extra="forbid")

    experimental_test_only: bool
    labels: list[int]
    raw_scores: list[float]
    project_groups: list[str]
    shap_rows: list[dict[str, float]] | None = None

    @model_validator(mode="after")
    def validate_test_boundary(self) -> ExperimentalCalibrationFixture:
        if not self.experimental_test_only:
            raise ValueError("synthetic calibration fixture must set experimental_test_only=true")
        if not (len(self.labels) == len(self.raw_scores) == len(self.project_groups)):
            raise ValueError("labels, raw_scores and project_groups must have equal length")
        if not self.labels:
            raise ValueError("synthetic calibration fixture cannot be empty")
        if any(label not in (0, 1) for label in self.labels):
            raise ValueError("synthetic calibration labels must be binary")
        if self.shap_rows is not None and len(self.shap_rows) != len(self.labels):
            raise ValueError("synthetic SHAP rows must align with labels")
        return self


class CalibrationAdapter(Protocol):
    """Future supervised adapter; production has no implementation yet."""

    def evaluate(self, fixture: ExperimentalCalibrationFixture) -> dict[str, float]: ...


def scan_expert_labels(annotations_root: Path) -> ExpertLabelSummary:
    """Count actual completed decisions; weak supervision is deliberately ignored."""
    completed: set[str] = set()
    for pillar in ("p1", "p2", "p3", "p4"):
        path = annotations_root / f"{pillar}_review_template.jsonl"
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise CalibrationInputError(f"{path.name}: cannot read expert labels ({exc})") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CalibrationInputError(
                    f"{path.name}: line {line_number}: invalid JSON ({exc.msg})"
                ) from exc
            if not isinstance(row, dict):
                raise CalibrationInputError(f"{path.name}: line {line_number}: expected object")
            finding_id = row.get("finding_id")
            decision = row.get("expert_decision")
            if isinstance(finding_id, str) and decision is not None and str(decision).strip():
                completed.add(finding_id)
    return ExpertLabelSummary(len(completed), tuple(sorted(completed)))


def production_calibration_metadata(summary: ExpertLabelSummary) -> CalibrationMetadata:
    """Return honest production state. Training is intentionally not automatic."""
    # Even reaching the numeric threshold would only enable an experimental
    # evaluation phase; it must not silently replace deterministic production.
    return CalibrationMetadata(
        calibration_status="not_available_without_expert_labels",
        completed_expert_labels=summary.completed_labels,
        minimum_labels_required=MIN_EXPERT_LABELS,
        calibrated_probability=None,
        method=None,
        experimental_test_only=False,
        limitations=[
            "Калибровка станет доступна после накопления достаточной экспертной разметки.",
            (
                "Требуются группированная проверка без утечки проектов "
                "и обоснованный метод калибровки."
            ),
        ],
    )


def production_model_metadata() -> ModelMetadata:
    return ModelMetadata(
        model_status="not_trained",
        model_type=None,
        model_version=None,
        trained_on_real_labels=False,
        grouped_validation=False,
        experimental_test_only=False,
        shap_available=False,
        limitations=[
            "Production ML model is not trained because completed expert labels are unavailable.",
            "SHAP values are not produced for the deterministic scorer.",
        ],
    )
