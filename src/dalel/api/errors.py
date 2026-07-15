"""Client-facing API errors and resource lookups.

Kept separate from ``app.py`` so routes and the app factory can share it
without a circular import. Every lookup raises a clean ``ApiError`` (JSON,
no traceback, no path) when a resource is missing.
"""

from __future__ import annotations

from typing import Any

from dalel.api.repository import ArtifactStore, PillarArtifacts


class ApiError(Exception):
    """Expected, client-facing error rendered as ``{error, detail}`` JSON."""

    def __init__(self, status_code: int, error: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail


def require_project(store: ArtifactStore, project_id: str) -> dict[str, Any]:
    project = store.project(project_id)
    if project is None:
        raise ApiError(
            404,
            "project_not_found",
            f"Проект «{project_id}» не найден.",
        )
    return project


def require_pillar(store: ArtifactStore, pillar_key: str) -> PillarArtifacts:
    pillar = store.pillar(pillar_key.lower())
    if pillar is None:
        available = ", ".join(store.pillars)
        raise ApiError(
            404,
            "pillar_not_found",
            f"Пиллар «{pillar_key}» не найден. Доступны: {available}.",
        )
    return pillar


def require_pillar_filter(store: ArtifactStore, pillar_key: str) -> str:
    """Validate a ``?pillar=`` finding filter against the available,
    implemented pillars (p1/p2/p3). Unknown or unavailable values — including
    roadmap pillars (p4/meta) and arbitrary strings — get a clean 404.
    Returns the normalized (lower-case) key."""
    normalized = pillar_key.strip().lower()
    pillar = store.pillar(normalized)
    if pillar is None or not pillar.available or not pillar.descriptor.implemented:
        raise ApiError(404, "pillar_not_found", f"Unknown pillar: {pillar_key}")
    return normalized
