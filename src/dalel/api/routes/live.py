"""Authenticated multipart endpoints for genuinely new project analysis."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Header, Request, UploadFile, status
from starlette.datastructures import UploadFile as StarletteUploadFile

from dalel.api.errors import ApiError
from dalel.api.live import (
    LIVE_JOB_TOKEN_HEADER,
    MAX_FILE_COUNT,
    LiveJobCreatedResponse,
    LiveJobEventsResponse,
    LiveJobResponse,
    LivePackageSchemaResponse,
    build_live_package_schema,
    get_live_job_manager,
    parse_live_request,
)

router = APIRouter(tags=["live-analysis"])


@router.get("/live/package-schema", response_model=LivePackageSchemaResponse)
def live_package_schema() -> LivePackageSchemaResponse:
    return build_live_package_schema()


@router.post(
    "/live/jobs",
    response_model=LiveJobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["request", "files"],
                        "properties": {
                            "request": {"type": "string", "description": "LiveJobRequest JSON"},
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            },
                        },
                    }
                }
            },
        }
    },
)
async def create_live_job(http_request: Request) -> LiveJobCreatedResponse:
    # These parser limits apply while Starlette is receiving/spooling parts,
    # before endpoint-level byte/signature validation. They prevent a request
    # containing hundreds of tiny file parts from consuming descriptors.
    async with http_request.form(
        max_files=MAX_FILE_COUNT,
        max_fields=1,
        max_part_size=64 * 1024,
    ) as form:
        raw_requests: list[str] = []
        files: list[UploadFile] = []
        for field_name, value in form.multi_items():
            if field_name == "request" and isinstance(value, str):
                raw_requests.append(value)
            elif field_name == "files" and isinstance(value, StarletteUploadFile):
                files.append(cast(UploadFile, value))
            else:
                raise ApiError(
                    422,
                    "unexpected_multipart_part",
                    "Multipart-запрос содержит неизвестную часть.",
                )
        if len(raw_requests) != 1:
            raise ApiError(
                422,
                "invalid_live_request",
                "Multipart-запрос должен содержать одно поле request.",
            )
        parsed = await parse_live_request(raw_requests[0])
        return await get_live_job_manager().create_job(parsed, files)


@router.get("/live/jobs/{job_id}", response_model=LiveJobResponse)
def get_live_job(
    job_id: str,
    access_token: Annotated[str | None, Header(alias=LIVE_JOB_TOKEN_HEADER)] = None,
) -> LiveJobResponse:
    return get_live_job_manager().get_job(job_id, access_token or "")


@router.get("/live/jobs/{job_id}/events", response_model=LiveJobEventsResponse)
def get_live_job_events(
    job_id: str,
    access_token: Annotated[str | None, Header(alias=LIVE_JOB_TOKEN_HEADER)] = None,
) -> LiveJobEventsResponse:
    return get_live_job_manager().get_events(job_id, access_token or "")


@router.delete(
    "/live/jobs/{job_id}",
    response_model=LiveJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_live_job(
    job_id: str,
    access_token: Annotated[str | None, Header(alias=LIVE_JOB_TOKEN_HEADER)] = None,
) -> LiveJobResponse:
    return get_live_job_manager().cancel_job(job_id, access_token or "")
