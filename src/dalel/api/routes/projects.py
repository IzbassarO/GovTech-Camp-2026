"""Project listing, detail, summary and pillar endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from dalel.api.errors import require_project
from dalel.api.repository import get_store
from dalel.api.schemas import (
    DocumentInfo,
    PillarSummary,
    ProjectDetail,
    ProjectListItem,
    ProjectSummary,
)
from dalel.api.services import (
    build_pillar_summary,
    build_project_detail,
    build_project_list,
    build_project_summary,
)

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectListItem])
def list_projects() -> list[ProjectListItem]:
    return build_project_list(get_store())


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str) -> ProjectDetail:
    store = get_store()
    project = require_project(store, project_id)
    return build_project_detail(store, project)


@router.get("/projects/{project_id}/summary", response_model=ProjectSummary)
def get_project_summary(project_id: str) -> ProjectSummary:
    store = get_store()
    project = require_project(store, project_id)
    return build_project_summary(store, project)


@router.get("/projects/{project_id}/pillars", response_model=list[PillarSummary])
def get_project_pillars(project_id: str) -> list[PillarSummary]:
    store = get_store()
    project = require_project(store, project_id)
    project_id = str(project["project_id"])
    return [build_pillar_summary(store, store.pillars[key], project_id) for key in store.pillars]


@router.get("/projects/{project_id}/documents", response_model=list[DocumentInfo])
def get_project_documents(project_id: str) -> list[DocumentInfo]:
    store = get_store()
    project = require_project(store, project_id)
    return build_project_detail(store, project).documents
