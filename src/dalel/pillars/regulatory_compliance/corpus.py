"""Regulatory corpus loading and validation.

A corpus is one JSONL file of requirement-level records (see
``RegulatoryRequirement``). The loader is strict: schema violations,
duplicate IDs, hash mismatches, unsupported corpus versions and
demo/authoritative contradictions abort with a concise ``CorpusError`` —
never a traceback and never silently-repaired metadata.

The packaged demo corpus is SYNTHETIC (``demo_only=true``,
``is_authoritative=false``): illustrative requirement shapes for the demo
pipeline, NOT Kazakhstan law and NOT an authoritative legal source.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from dalel.pillars.regulatory_compliance.config import SUPPORTED_CORPUS_VERSIONS
from dalel.pillars.regulatory_compliance.schemas import (
    RegulatoryRequirement,
    requirement_text_hash,
)


class CorpusError(Exception):
    """Blocking regulatory-corpus problem (file, line and reason)."""


DEMO_CORPUS_RESOURCE = Path(__file__).parent / "resources" / "demo_regulatory_corpus.jsonl"


def _parse_iso_date(value: str, file_name: str, line_number: int, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CorpusError(
            f"{file_name}: line {line_number}: field '{field}': {value!r}"
            " is not an ISO date (YYYY-MM-DD)"
        ) from exc


def load_corpus(path: Path) -> list[RegulatoryRequirement]:
    """Load and fully validate one corpus file (deterministic order:
    requirements keep file order; IDs must be unique)."""
    if not path.is_file():
        raise CorpusError(
            f"regulatory corpus file is missing: {path};"
            " pass --regulations demo for the packaged synthetic demo corpus"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CorpusError(f"{path.name}: cannot read corpus file ({exc})") from exc

    requirements: list[RegulatoryRequirement] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorpusError(f"{path.name}: line {line_number}: invalid JSON ({exc.msg})") from exc
        if not isinstance(record, dict):
            raise CorpusError(f"{path.name}: line {line_number}: record is not a JSON object")
        try:
            requirement = RegulatoryRequirement.model_validate(record)
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first.get("loc", ())) or "(record)"
            raise CorpusError(
                f"{path.name}: line {line_number}: field '{location}':"
                f" {first.get('msg', 'invalid value')}"
            ) from exc
        _validate_requirement(requirement, path.name, line_number)
        if requirement.requirement_id in seen_ids:
            raise CorpusError(
                f"{path.name}: line {line_number}: duplicate requirement_id"
                f" {requirement.requirement_id!r}"
            )
        seen_ids.add(requirement.requirement_id)
        requirements.append(requirement)

    if not requirements:
        raise CorpusError(f"{path.name}: corpus contains no requirements")
    return requirements


def _validate_requirement(
    requirement: RegulatoryRequirement, file_name: str, line_number: int
) -> None:
    if requirement.corpus_version not in SUPPORTED_CORPUS_VERSIONS:
        raise CorpusError(
            f"{file_name}: line {line_number}: unsupported corpus_version"
            f" {requirement.corpus_version!r} (supported:"
            f" {', '.join(sorted(SUPPORTED_CORPUS_VERSIONS))})"
        )
    expected_hash = requirement_text_hash(requirement.requirement_text)
    if requirement.source_hash != expected_hash:
        raise CorpusError(
            f"{file_name}: line {line_number}: source_hash does not match"
            f" sha256(requirement_text) for {requirement.requirement_id!r} —"
            " the requirement text was altered after hashing"
        )
    if requirement.demo_only and requirement.is_authoritative:
        raise CorpusError(
            f"{file_name}: line {line_number}: {requirement.requirement_id!r}"
            " is demo_only and cannot be is_authoritative"
        )
    effective_from = (
        _parse_iso_date(requirement.effective_from, file_name, line_number, "effective_from")
        if requirement.effective_from is not None
        else None
    )
    effective_to = (
        _parse_iso_date(requirement.effective_to, file_name, line_number, "effective_to")
        if requirement.effective_to is not None
        else None
    )
    if effective_from is not None and effective_to is not None and effective_from > effective_to:
        raise CorpusError(
            f"{file_name}: line {line_number}: effective_from is after"
            f" effective_to for {requirement.requirement_id!r}"
        )
    if requirement.obligation_type == "required_document" and (
        requirement.required_document_type is None
    ):
        raise CorpusError(
            f"{file_name}: line {line_number}: {requirement.requirement_id!r}"
            " is a required_document requirement without required_document_type"
        )


def corpus_is_demo_only(requirements: list[RegulatoryRequirement]) -> bool:
    return all(r.demo_only for r in requirements)


def corpus_summary(requirements: list[RegulatoryRequirement]) -> dict[str, object]:
    corpora = sorted({(r.corpus_id, r.corpus_version) for r in requirements})
    return {
        "requirements_total": len(requirements),
        "corpora": [{"corpus_id": c, "corpus_version": v} for c, v in corpora],
        "authoritative": sum(1 for r in requirements if r.is_authoritative),
        "demo_only": sum(1 for r in requirements if r.demo_only),
        "by_obligation_type": {
            key: sum(1 for r in requirements if r.obligation_type == key)
            for key in sorted({r.obligation_type for r in requirements})
        },
        "with_effective_from": sum(1 for r in requirements if r.effective_from),
        "with_source_url": sum(1 for r in requirements if r.source_url),
    }
