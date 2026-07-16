"""Read-only loading and alignment checks for accepted P1--P4 artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from dalel.meta_review.config import PILLARS


class MetaArtifactError(ValueError):
    """A concise, expected error in the P1--P4 artifact contract."""


@dataclass(frozen=True)
class PillarArtifactBundle:
    pillar_id: str
    available: bool
    project_scores: list[dict[str, Any]] = field(default_factory=list)
    document_scores: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    config_snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def project_ids(self) -> set[str]:
        return {str(record["project_id"]) for record in self.project_scores}


_EXTRA_JSONL = {
    "P1": (),
    "P2": ("assessments", "retrievals", "project_evidence", "requirements_snapshot"),
    "P3": ("mentions", "candidates", "aggregation_checks", "suppressed_samples"),
    "P4": (
        "claims",
        "entities",
        "edges",
        "resolution_decisions",
        "suppressed_comparisons",
    ),
}

_EXTRA_REQUIRED: dict[str, dict[str, tuple[str, ...]]] = {
    "P1": {},
    "P2": {
        "assessments": (
            "assessment_id",
            "project_id",
            "label",
            "confidence",
            "requirement_is_authoritative",
            "retrieval_id",
            "evidence_ids",
        ),
        "retrievals": ("retrieval_id", "project_id"),
        "project_evidence": ("evidence_id", "project_id"),
        "requirements_snapshot": ("requirement_id",),
    },
    "P3": {
        "mentions": ("mention_id", "project_id"),
        "candidates": ("candidate_id", "project_id", "status"),
        "aggregation_checks": ("check_id", "project_id", "decision"),
        "suppressed_samples": ("sample_id", "project_id"),
    },
    "P4": {
        "claims": ("claim_id", "project_id"),
        "entities": ("entity_id", "project_id"),
        "edges": ("edge_id", "project_id"),
        "resolution_decisions": ("decision_id", "project_id", "decision"),
        "suppressed_comparisons": ("suppression_id", "project_id"),
    },
}

# Primary-key field(s) for EVERY loaded artifact collection, used to reject
# duplicate upstream records before any feature/coverage arithmetic runs.
# ``document_scores`` has no dedicated id field: its stable identity is the
# (project_id, document_id) pair, which is why it is composite here while
# every other artifact type carries a single content-derived id field.
_ID_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "P1": {
        "document_scores": ("project_id", "document_id"),
        "findings": ("finding_id",),
    },
    "P2": {
        "document_scores": ("project_id", "document_id"),
        "findings": ("finding_id",),
        "assessments": ("assessment_id",),
        "retrievals": ("retrieval_id",),
        "project_evidence": ("evidence_id",),
        "requirements_snapshot": ("requirement_id",),
    },
    "P3": {
        "document_scores": ("project_id", "document_id"),
        "findings": ("finding_id",),
        "mentions": ("mention_id",),
        "candidates": ("candidate_id",),
        "aggregation_checks": ("check_id",),
        "suppressed_samples": ("sample_id",),
    },
    "P4": {
        "document_scores": ("project_id", "document_id"),
        "findings": ("finding_id",),
        "claims": ("claim_id",),
        "entities": ("entity_id",),
        "edges": ("edge_id",),
        "resolution_decisions": ("decision_id",),
        "suppressed_comparisons": ("suppression_id",),
    },
}

# Findings are the artifact type that feeds Meta scoring most directly (and
# the one the reproduced bug appended), and their schema is always fully
# populated (evidence, pages, requirement/entity references, ...), so a
# canonical fingerprint of the record with only ``finding_id`` excluded
# additionally rejects an exact-duplicate finding even if a malformed fixture
# changed or stripped the stable id, without risking false positives.
# Other artifact types ("extras" such as P2 retrievals or P3 candidates) are
# raw, loosely-shaped records that legitimately carry few fields beyond their
# own id in some pillars, so they rely on plain id-uniqueness (above) only --
# fingerprinting them on their non-id fields could wrongly equate two
# genuinely distinct records that happen to share every other populated field.
_FINGERPRINT_ID_FIELDS: dict[str, dict[str, str]] = {
    pillar: {"findings": "finding_id"} for pillar in _ID_FIELDS
}


def _models_for(pillar_id: str) -> tuple[type[BaseModel], type[BaseModel], type[BaseModel]]:
    if pillar_id == "P1":
        from dalel.pillars.document_integrity.schemas import (
            DocumentScoreRecord,
            FindingRecord,
            ProjectScoreRecord,
        )

        return ProjectScoreRecord, DocumentScoreRecord, FindingRecord
    if pillar_id == "P2":
        from dalel.pillars.regulatory_compliance.schemas import (
            P2DocumentScoreRecord,
            P2FindingRecord,
            P2ProjectScoreRecord,
        )

        return P2ProjectScoreRecord, P2DocumentScoreRecord, P2FindingRecord
    if pillar_id == "P3":
        from dalel.pillars.quantitative_consistency.schemas import (
            P3DocumentScoreRecord,
            P3FindingRecord,
            P3ProjectScoreRecord,
        )

        return P3ProjectScoreRecord, P3DocumentScoreRecord, P3FindingRecord
    from dalel.pillars.cross_document_coherence.schemas import (
        P4DocumentScoreRecord,
        P4FindingRecord,
        P4ProjectScoreRecord,
    )

    return P4ProjectScoreRecord, P4DocumentScoreRecord, P4FindingRecord


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MetaArtifactError(f"{path.name}: required artifact is missing") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetaArtifactError(f"{path.name}: invalid JSON ({exc})") from exc
    if not isinstance(value, dict):
        raise MetaArtifactError(f"{path.name}: expected one JSON object")
    return value


def _read_jsonl(path: Path, model: type[BaseModel] | None = None) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise MetaArtifactError(f"{path.name}: required artifact is missing") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise MetaArtifactError(f"{path.name}: cannot read artifact ({exc})") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MetaArtifactError(
                f"{path.name}: line {line_number}: invalid JSON ({exc.msg})"
            ) from exc
        if not isinstance(value, dict):
            raise MetaArtifactError(f"{path.name}: line {line_number}: expected JSON object")
        if model is not None:
            try:
                value = model.model_validate(value).model_dump(mode="json")
            except ValidationError as exc:
                raise MetaArtifactError(
                    f"{path.name}: line {line_number}: schema mismatch ({exc.errors()[0]['msg']})"
                ) from exc
        records.append(value)
    return records


def load_pillar_artifacts(pillar_id: str, directory: Path) -> PillarArtifactBundle:
    """Load one pillar. A wholly absent directory is an explicit unavailable pillar."""
    if pillar_id not in PILLARS:
        raise MetaArtifactError(f"unsupported pillar: {pillar_id}")
    if not directory.exists():
        return PillarArtifactBundle(pillar_id=pillar_id, available=False)
    if not directory.is_dir():
        raise MetaArtifactError(f"{pillar_id}: artifact location is not a directory")

    project_model, document_model, finding_model = _models_for(pillar_id)
    project_scores = _read_jsonl(directory / "project_scores.jsonl", project_model)
    document_scores = _read_jsonl(directory / "document_scores.jsonl", document_model)
    findings = _read_jsonl(directory / "findings.jsonl", finding_model)
    records = {name: _read_jsonl(directory / f"{name}.jsonl") for name in _EXTRA_JSONL[pillar_id]}
    metrics = _read_json(directory / "metrics.json")
    snapshot = _read_json(directory / "config_snapshot.json")
    bundle = PillarArtifactBundle(
        pillar_id=pillar_id,
        available=True,
        project_scores=project_scores,
        document_scores=document_scores,
        findings=findings,
        records=records,
        metrics=metrics,
        config_snapshot=snapshot,
    )
    _validate_bundle_identity(bundle)
    return bundle


def _canonical_fingerprint(row: dict[str, Any], exclude: str) -> str:
    trimmed = {key: value for key, value in row.items() if key != exclude}
    return json.dumps(trimmed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_bundle_identity(bundle: PillarArtifactBundle) -> None:
    project_ids = [str(row["project_id"]) for row in bundle.project_scores]
    if len(project_ids) != len(set(project_ids)):
        raise MetaArtifactError(f"{bundle.pillar_id}: duplicate project score IDs")
    known = set(project_ids)
    if not known:
        raise MetaArtifactError(f"{bundle.pillar_id}: no project scores")
    id_field_map = _ID_FIELDS[bundle.pillar_id]
    fingerprint_field_map = _FINGERPRINT_ID_FIELDS[bundle.pillar_id]
    for artifact_name, rows in (
        ("document_scores", bundle.document_scores),
        ("findings", bundle.findings),
        *bundle.records.items(),
    ):
        required = _EXTRA_REQUIRED[bundle.pillar_id].get(artifact_name, ())
        id_fields = id_field_map.get(artifact_name, ())
        fingerprint_field = fingerprint_field_map.get(artifact_name)
        seen_ids: set[tuple[str, ...]] = set()
        seen_fingerprints: set[str] = set()
        for row in rows:
            missing = [key for key in required if key not in row]
            if missing:
                raise MetaArtifactError(
                    f"{bundle.pillar_id}:{artifact_name}: missing required fields {missing}"
                )
            project_id = row.get("project_id")
            if project_id is not None and str(project_id) not in known:
                raise MetaArtifactError(
                    f"{bundle.pillar_id}:{artifact_name}: unknown project_id {project_id!r}"
                )
            if id_fields:
                missing_id_fields = [id_field for id_field in id_fields if id_field not in row]
                if missing_id_fields:
                    raise MetaArtifactError(
                        f"{bundle.pillar_id}:{artifact_name}: "
                        f"missing id field(s) {missing_id_fields}"
                    )
                record_id = tuple(str(row[id_field]) for id_field in id_fields)
                if record_id in seen_ids:
                    label = "/".join(record_id)
                    raise MetaArtifactError(
                        f"{bundle.pillar_id}:{artifact_name}: duplicate record ID {label}"
                        + (f" (project {project_id!r})" if project_id is not None else "")
                    )
                seen_ids.add(record_id)
            if fingerprint_field is not None:
                fingerprint = _canonical_fingerprint(row, fingerprint_field)
                if fingerprint in seen_fingerprints:
                    raise MetaArtifactError(
                        f"{bundle.pillar_id}:{artifact_name}: duplicate record content"
                        + (f" (project {project_id!r})" if project_id is not None else "")
                    )
                seen_fingerprints.add(fingerprint)


def align_projects(bundles: dict[str, PillarArtifactBundle]) -> list[str]:
    available = [bundle for bundle in bundles.values() if bundle.available]
    if not available:
        raise MetaArtifactError("no P1--P4 artifact directories are available")
    expected = available[0].project_ids
    for bundle in available[1:]:
        if bundle.project_ids != expected:
            missing = sorted(expected - bundle.project_ids)
            extra = sorted(bundle.project_ids - expected)
            raise MetaArtifactError(
                f"{bundle.pillar_id}: project alignment mismatch; missing={missing}, extra={extra}"
            )
    return sorted(expected)
