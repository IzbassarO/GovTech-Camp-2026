"""Per-project, per-pillar report (synthesized markdown summary)."""

from __future__ import annotations

from fastapi import APIRouter

from dalel.api.errors import require_pillar, require_project
from dalel.api.repository import get_store
from dalel.api.schemas import ReportResponse
from dalel.api.services import build_report

router = APIRouter(tags=["reports"])


@router.get("/projects/{project_id}/reports/{pillar}", response_model=ReportResponse)
def get_report(project_id: str, pillar: str) -> ReportResponse:
    store = get_store()
    project = require_project(store, project_id)
    descriptor = require_pillar(store, pillar)
    return build_report(store, project, descriptor.descriptor.key)
