"""Health and readiness."""

from __future__ import annotations

from fastapi import APIRouter

from dalel.api import API_VERSION
from dalel.api.repository import get_store
from dalel.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    store = get_store()
    available = [
        pillar.descriptor.pillar_id for pillar in store.pillars.values() if pillar.available
    ]
    if store.meta.available:
        available.append("META")
    return HealthResponse(
        status="ok",
        api_version=API_VERSION,
        projects_available=len(store.projects),
        pillars_available=available,
        meta_available=store.meta.available,
        data_ready=bool(store.projects) and bool(available),
    )
