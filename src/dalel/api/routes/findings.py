"""Findings listing (with filters) and finding detail."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from dalel.api.errors import ApiError, require_pillar_filter, require_project
from dalel.api.repository import get_store
from dalel.api.schemas import FindingDetail, FindingsPage
from dalel.api.services import build_finding_detail, build_findings_page, find_finding

router = APIRouter(tags=["findings"])


@router.get("/projects/{project_id}/findings", response_model=FindingsPage)
def list_findings(
    project_id: str,
    pillar: Annotated[str | None, Query(description="Ключ пиллара: p1 | p2 | p3")] = None,
    severity: Annotated[str | None, Query(description="high | medium | low | info")] = None,
    finding_type: Annotated[str | None, Query(description="Тип находки")] = None,
    document_id: Annotated[str | None, Query(description="Идентификатор документа")] = None,
    search: Annotated[str | None, Query(description="Поиск по заголовку/типу")] = None,
) -> FindingsPage:
    store = get_store()
    project = require_project(store, project_id)
    # Reject unsupported/unavailable pillar filters (p9, meta, arbitrary) with
    # a clean 404 — a valid but zero-findings pillar (p3) still returns 200.
    normalized_pillar = require_pillar_filter(store, pillar) if pillar else None
    return build_findings_page(
        store,
        str(project["project_id"]),
        pillar=normalized_pillar,
        severity=severity,
        finding_type=finding_type,
        document_id=document_id,
        search=search,
    )


@router.get(
    "/projects/{project_id}/findings/{finding_id}",
    response_model=FindingDetail,
)
def get_finding(project_id: str, finding_id: str) -> FindingDetail:
    store = get_store()
    project = require_project(store, project_id)
    match = find_finding(store, str(project["project_id"]), finding_id)
    if match is None:
        raise ApiError(
            404,
            "finding_not_found",
            f"Находка «{finding_id}» не найдена в проекте «{project_id}».",
        )
    pillar, finding = match
    return build_finding_detail(store, pillar, finding)
