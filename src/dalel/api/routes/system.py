"""System-wide metrics (aggregate across all projects and pillars)."""

from __future__ import annotations

from fastapi import APIRouter

from dalel.api.repository import get_store
from dalel.api.schemas import SystemMetrics
from dalel.api.services import build_system_metrics

router = APIRouter(tags=["system"])


@router.get("/system/metrics", response_model=SystemMetrics)
def system_metrics() -> SystemMetrics:
    return build_system_metrics(get_store())
