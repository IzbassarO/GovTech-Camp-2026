"""P5 input contract: structural validation of visual-asset inputs.

Rejects (as hard errors) inputs that would poison the inventory: missing
source-document references, unsafe or absolute image paths, duplicated
identities, invalid dimensions, malformed hashes and provenance mismatches.
Soft per-asset problems (missing bytes, undecodable images, unsupported media
types) are NOT rejections — they become ``unsupported`` assets with recorded
limitations so the exclusion stays auditable.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class P5InputError(Exception):
    """Blocking P5 input violation."""


def safe_relative_path(value: str) -> bool:
    """True when ``value`` is a safe relative POSIX path (no traversal)."""
    if not value or "\\" in value or value.startswith("/"):
        return False
    path = PurePosixPath(value)
    return not any(part in {"", ".", ".."} for part in path.parts)


def validate_curated_image_record(index: int, record: dict[str, Any]) -> list[str]:
    """Return violation messages for one curated ``images.jsonl`` record."""
    errors: list[str] = []
    where = f"images.jsonl:{index}"
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        errors.append(f"{where}: provenance object is missing")
        return errors
    if not provenance.get("document_id"):
        errors.append(f"{where}: provenance.document_id is missing")
    if not provenance.get("project_id"):
        errors.append(f"{where}: provenance.project_id is missing")
    if not record.get("image_id"):
        errors.append(f"{where}: image_id is missing")
    relative = record.get("curated_image_path")
    if relative is not None and not safe_relative_path(str(relative)):
        errors.append(f"{where}: unsafe curated_image_path {relative!r}")
    sha = record.get("image_sha256")
    if sha is not None and not _SHA256_RE.match(str(sha)):
        errors.append(f"{where}: malformed image_sha256")
    for dimension in ("width_px", "height_px"):
        value = record.get(dimension)
        if value is not None and (not isinstance(value, int) or value < 1):
            errors.append(f"{where}: invalid {dimension} {value!r}")
    page = record.get("page_number")
    if page is not None and (not isinstance(page, int) or page < 1):
        errors.append(f"{where}: invalid page_number {page!r}")
    return errors


def check_unique_asset_ids(asset_ids: list[str]) -> None:
    seen: set[str] = set()
    for asset_id in asset_ids:
        if asset_id in seen:
            raise P5InputError(f"duplicate asset identity {asset_id}")
        seen.add(asset_id)


def check_document_membership(
    asset_document_ids: set[str], known_document_ids: set[str], *, allow_extra: set[str]
) -> None:
    """Every asset must reference a known document (or declared direct input)."""
    unknown = sorted(asset_document_ids - known_document_ids - allow_extra)
    if unknown:
        raise P5InputError(
            "assets reference documents absent from the dataset: " + ", ".join(unknown[:5])
        )
