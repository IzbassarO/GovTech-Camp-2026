"""P5 Multimodal Visual Evidence endpoints (prepared projects + live jobs).

Prepared endpoints serve accepted ``data/results/p5/v1`` artifacts read-only.
Live endpoints require the job token and serve ONLY that job's workspace
artifacts. Thumbnails are re-encoded bounded JPEGs addressed by asset id —
no filesystem path ever appears in a URL or response.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Response

from dalel.api.errors import require_project
from dalel.api.live import LIVE_JOB_TOKEN_HEADER, get_live_job_manager
from dalel.api.p5_service import (
    P5AssetDetailResponse,
    P5AssetsResponse,
    P5FindingsResponse,
    P5ProjectResponse,
    build_asset_detail,
    build_assets_response,
    build_findings_response,
    build_project_response,
    get_prepared_bundle,
    load_p5_bundle,
    render_thumbnail,
    resolve_asset_image,
)
from dalel.api.repository import get_store

router = APIRouter(tags=["p5-visual-evidence"])

_THUMBNAIL_HEADERS = {
    "Cache-Control": "private, max-age=300",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/projects/{project_id}/p5", response_model=P5ProjectResponse)
def get_project_p5(project_id: str) -> P5ProjectResponse:
    require_project(get_store(), project_id)
    return build_project_response(get_prepared_bundle(), project_id)


@router.get("/projects/{project_id}/p5/assets", response_model=P5AssetsResponse)
def get_project_p5_assets(project_id: str) -> P5AssetsResponse:
    require_project(get_store(), project_id)
    return build_assets_response(get_prepared_bundle(), project_id)


@router.get("/projects/{project_id}/p5/assets/{asset_id}", response_model=P5AssetDetailResponse)
def get_project_p5_asset(project_id: str, asset_id: str) -> P5AssetDetailResponse:
    require_project(get_store(), project_id)
    return build_asset_detail(get_prepared_bundle(), project_id, asset_id)


@router.get(
    "/projects/{project_id}/p5/assets/{asset_id}/thumbnail",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def get_project_p5_thumbnail(project_id: str, asset_id: str) -> Response:
    require_project(get_store(), project_id)
    from dalel.api.config import get_settings

    path = resolve_asset_image(
        get_prepared_bundle(),
        project_id,
        asset_id,
        curated_root=get_settings().curated_dir,
        workspace_root=None,
    )
    payload, media_type = render_thumbnail(path)
    return Response(content=payload, media_type=media_type, headers=_THUMBNAIL_HEADERS)


@router.get("/projects/{project_id}/p5/findings", response_model=P5FindingsResponse)
def get_project_p5_findings(project_id: str) -> P5FindingsResponse:
    require_project(get_store(), project_id)
    return build_findings_response(get_prepared_bundle(), project_id)


@router.get(
    "/live/jobs/{job_id}/p5/assets/{asset_id}/thumbnail",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def get_live_p5_thumbnail(
    job_id: str,
    asset_id: str,
    access_token: Annotated[str | None, Header(alias=LIVE_JOB_TOKEN_HEADER)] = None,
) -> Response:
    workspace = get_live_job_manager().get_p5_workspace(job_id, access_token or "")
    bundle = load_p5_bundle(workspace / "data" / "results" / "p5")
    project_id = next(iter(bundle.project_scores), "") if bundle.available else ""
    # Curated-rooted assets in a live job resolve against the JOB-LOCAL
    # curated dataset — never against the prepared corpus.
    path = resolve_asset_image(
        bundle,
        project_id,
        asset_id,
        curated_root=workspace / "data" / "curated" / "v1",
        workspace_root=workspace,
    )
    payload, media_type = render_thumbnail(path)
    return Response(content=payload, media_type=media_type, headers=_THUMBNAIL_HEADERS)
