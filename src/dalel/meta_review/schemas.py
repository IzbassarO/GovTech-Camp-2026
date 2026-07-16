"""Strict schemas for Meta features, coverage, scoring and calibration state."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PillarId = Literal["P1", "P2", "P3", "P4"]
PriorityLevel = Literal["low", "moderate", "elevated", "high"]


def deterministic_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}__{digest}"


class MetaFeatureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    project_id: str
    feature_name: str
    pillar_source: PillarId
    raw_value: int | float
    normalized_value: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    contribution: float = Field(ge=0.0)
    source_artifact_ids: list[str] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    explanation: str
    limitations: list[str] = Field(default_factory=list)


class FeatureContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contribution_id: str
    feature_id: str
    project_id: str
    feature_name: str
    pillar_source: PillarId
    raw_value: int | float
    normalized_value: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    raw_contribution: float = Field(ge=0.0)
    contribution: float = Field(ge=0.0)
    source_artifact_ids: list[str] = Field(default_factory=list)
    source_finding_ids: list[str] = Field(default_factory=list)
    explanation: str
    limitations: list[str] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list)


class ScoreAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjustment_id: str
    adjustment_type: Literal["discount", "cap", "uncertainty"]
    pillar_source: PillarId | None = None
    amount: float = Field(le=0.0)
    applied: bool
    reason: str
    config_key: str


class PillarContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contribution_id: str
    project_id: str
    pillar_id: PillarId
    available: bool
    raw_subtotal: float = Field(ge=0.0)
    discount_factor: float = Field(ge=0.0, le=1.0)
    discount_amount: float = Field(le=0.0)
    cap: float = Field(ge=0.0)
    cap_adjustment: float = Field(le=0.0)
    subtotal: float = Field(ge=0.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    assessment_confidence: float = Field(ge=0.0, le=1.0)
    caps_applied: list[ScoreAdjustment] = Field(default_factory=list)
    discounts_applied: list[ScoreAdjustment] = Field(default_factory=list)
    feature_contribution_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CoverageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage_id: str
    project_id: str
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    assessment_confidence: float = Field(ge=0.0, le=1.0)
    pillar_coverage: dict[PillarId, float]
    pillar_confidence: dict[PillarId, float]
    missing_pillars: list[PillarId] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CalibrationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calibration_status: Literal[
        "not_available_without_expert_labels", "experimental_test_only", "available"
    ]
    completed_expert_labels: int = Field(ge=0)
    minimum_labels_required: int = Field(ge=1)
    calibrated_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    method: str | None = None
    experimental_test_only: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_probability_policy(self) -> CalibrationMetadata:
        if self.calibration_status == "not_available_without_expert_labels":
            if self.calibrated_probability is not None:
                raise ValueError("calibrated probability requires validated expert labels")
            if self.method is not None:
                raise ValueError("calibration method cannot be set without expert labels")
        if self.calibration_status == "experimental_test_only" and not self.experimental_test_only:
            raise ValueError("synthetic calibration must set experimental_test_only=true")
        return self


class ModelMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_status: Literal["not_trained", "experimental_test_only", "validated"]
    model_type: str | None = None
    model_version: str | None = None
    trained_on_real_labels: bool = False
    grouped_validation: bool = False
    experimental_test_only: bool = False
    shap_available: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_model_policy(self) -> ModelMetadata:
        if self.model_status == "not_trained":
            if self.model_type is not None or self.model_version is not None:
                raise ValueError("untrained model cannot expose model identity")
            if self.shap_available:
                raise ValueError("SHAP is unavailable without a trained validated model")
        if self.model_status == "experimental_test_only" and not self.experimental_test_only:
            raise ValueError("synthetic model tests must set experimental_test_only=true")
        return self


class ProjectMetaAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str
    project_id: str
    meta_version: str
    scoring_config_version: str
    primary_label: str = "Integrated Review Priority Score"
    base_score: float = Field(ge=0.0)
    raw_feature_total: float = Field(ge=0.0)
    uncertainty_adjustment: float = Field(le=0.0)
    global_cap_adjustment: float = Field(le=0.0)
    review_priority_score: float = Field(ge=0.0, le=100.0)
    review_priority_level: PriorityLevel
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    assessment_confidence: float = Field(ge=0.0, le=1.0)
    pillar_contributions: list[PillarContribution]
    feature_contributions: list[FeatureContribution]
    top_positive_factors: list[FeatureContribution]
    caps_applied: list[ScoreAdjustment] = Field(default_factory=list)
    discounts_applied: list[ScoreAdjustment] = Field(default_factory=list)
    uncertainty_adjustments: list[ScoreAdjustment] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    counterfactual_explanation: str
    calibration_status: str
    calibrated_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    shap_contributions: list[dict[str, float]] | None = None
    calibration_metadata: CalibrationMetadata
    model_metadata: ModelMetadata

    @model_validator(mode="after")
    def validate_production_explainability_policy(self) -> ProjectMetaAssessment:
        if self.calibration_status != self.calibration_metadata.calibration_status:
            raise ValueError("calibration status disagrees with metadata")
        if self.calibrated_probability != self.calibration_metadata.calibrated_probability:
            raise ValueError("calibrated probability disagrees with metadata")
        if self.model_metadata.model_status != "validated" and self.shap_contributions is not None:
            raise ValueError("production SHAP requires a validated model")
        if self.shap_contributions is not None and not self.model_metadata.shap_available:
            raise ValueError("SHAP payload present while model metadata marks it unavailable")
        return self


class MetaLimitationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limitation_id: str
    project_id: str
    pillar_source: PillarId | None = None
    code: str
    message: str
