"""Prepared-replay demo endpoints: structured dossier -> animated analysis -> result.

Every job replays the accepted artifacts of a configured demo project; no
uploaded file content is read, stored or analyzed. See ``dalel.api.dossier``
for the section schema and manifest reconciliation and ``dalel.api.demo``
for the job-building logic and the honesty rationale.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header

from dalel.api.demo import (
    DemoJobCreatedResponse,
    DemoJobRequest,
    DemoJobResponse,
    build_demo_manifest_response,
    create_demo_job,
    get_demo_job,
)
from dalel.api.dossier import (
    DossierManifestResponse,
    DossierSchemaResponse,
    build_dossier_schema_response,
)
from dalel.api.repository import get_store

router = APIRouter(tags=["demo"])


@router.get("/demo/package-schema", response_model=DossierSchemaResponse)
def demo_package_schema() -> DossierSchemaResponse:
    """Canonical dossier section definitions (static configuration)."""
    return build_dossier_schema_response()


@router.get("/demo/manifest", response_model=DossierManifestResponse)
def demo_manifest() -> DossierManifestResponse:
    """Prepared demo dossier with reconciled per-file processing states."""
    return build_demo_manifest_response(get_store())


@router.post("/demo/jobs", response_model=DemoJobCreatedResponse)
def create_job(request: DemoJobRequest) -> DemoJobCreatedResponse:
    return create_demo_job(get_store(), request)


@router.get("/demo/jobs/{job_id}", response_model=DemoJobResponse)
def get_job(
    job_id: str,
    access_token: Annotated[str | None, Header(alias="X-Dalel-Job-Token")] = None,
) -> DemoJobResponse:
    return get_demo_job(job_id, access_token or "")
