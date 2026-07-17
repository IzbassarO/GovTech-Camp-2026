"""P5 asset inventory: collection, byte inspection and duplicate clustering.

Inputs are curated ``images.jsonl`` records (prepared datasets and job-local
live datasets share the contract) plus optional direct asset specs (live
uploads and label-source document images). Duplicate suppression is generic —
exact SHA-256, conservative perceptual near-duplicates, recurrence and
geometry — and never references filenames or asset numbering.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dalel.pillars.multimodal_visual_evidence.config import (
    HEADER_ASPECT_RATIO,
    HEADER_MIN_OCCURRENCES,
    LOGO_MAX_SIDE_PX,
    LOGO_MIN_DOCUMENTS,
    NEAR_DUPLICATE_DIM_TOLERANCE,
    NEAR_DUPLICATE_MAX_DISTANCE,
    SUPPORTED_MEDIA_TYPES,
    TINY_MIN_AREA_PX,
    TINY_MIN_SIDE_PX,
    UNIFORM_MAX_EXTREMA_SPAN,
    UNIFORM_MAX_STDDEV,
)
from dalel.pillars.multimodal_visual_evidence.input_contract import (
    P5InputError,
    safe_relative_path,
    validate_curated_image_record,
)
from dalel.pillars.multimodal_visual_evidence.schemas import (
    ClusterKind,
    ImageSourceRef,
    P5AssetRecord,
    P5DuplicateCluster,
    deterministic_id,
)


@dataclass
class DirectAssetSpec:
    """A non-curated raster fed by the live flow (upload / label-source image)."""

    key: str  # stable identity component, e.g. LIVEFILE__0003
    path: Path | None
    project_id: str
    document_id: str
    image_id: str
    extraction_origin: str  # uploaded_image | extracted_archive_image | label_source_image
    extraction_method: str
    provenance_reference: str
    source_reference: str
    workspace_relative_path: str | None = None
    document_type: str | None = None
    page_number: int | None = None
    docx_relationship: str | None = None
    bbox: dict[str, Any] | None = None
    dossier_section: str | None = None
    incoming_triage_state: str | None = None
    display_hint: str = ""


@dataclass
class InspectedAsset:
    """Asset record plus transient inspection state used by the pipeline."""

    record: P5AssetRecord
    path: Path | None
    display_hint: str = ""
    uniform: bool = False
    tiny: bool = False
    decode_failed: bool = False


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_media_type(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(16)
    except OSError:
        return None
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if prefix.startswith(b"GIF8"):
        return "image/gif"
    if prefix.startswith(b"BM"):
        return "image/bmp"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
        return "image/webp"
    return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records


def collect_curated_assets(
    dataset_dir: Path,
    *,
    job_id: str | None = None,
    document_types: dict[str, str] | None = None,
    dossier_sections: dict[str, str] | None = None,
    incoming_triage: dict[str, str] | None = None,
    project_filter: str | None = None,
) -> list[InspectedAsset]:
    """Inventory curated ``images.jsonl`` with provenance preserved."""
    dataset_dir = dataset_dir.resolve()
    rows = _read_jsonl(dataset_dir / "images.jsonl")
    violations: list[str] = []
    assets: list[InspectedAsset] = []
    for index, row in enumerate(rows, start=1):
        row_errors = validate_curated_image_record(index, row)
        if row_errors:
            violations.extend(row_errors)
            continue
        provenance: dict[str, Any] = row["provenance"]
        project_id = str(provenance["project_id"])
        if project_filter is not None and project_id != project_filter:
            continue
        document_id = str(provenance["document_id"])
        image_id = str(row["image_id"])
        relative = row.get("curated_image_path")
        path: Path | None = None
        limitations: list[str] = []
        if relative and safe_relative_path(str(relative)):
            candidate = (dataset_dir / str(relative)).resolve()
            try:
                candidate.relative_to(dataset_dir)
            except ValueError:
                violations.append(f"images.jsonl:{index}: path escapes the dataset directory")
                continue
            if candidate.is_file():
                path = candidate
            else:
                limitations.append("Curated image file is missing on disk.")
        else:
            limitations.append("Parser reported an image but did not provide image bytes.")

        recorded_sha = row.get("image_sha256")
        actual_sha = sha256_of(path) if path is not None else None
        if recorded_sha and actual_sha and recorded_sha != actual_sha:
            violations.append(
                f"images.jsonl:{index}: image bytes do not match recorded sha256"
                " (provenance mismatch)"
            )
            continue
        media_type = detect_media_type(path) if path is not None else None
        bbox_raw = provenance.get("bbox")
        record = P5AssetRecord(
            asset_id=deterministic_id(
                "P5A", project_id, document_id, image_id, actual_sha or "metadata-only"
            ),
            project_id=project_id,
            document_id=document_id,
            document_type=(document_types or {}).get(document_id)
            or (str(provenance.get("document_type")) if provenance.get("document_type") else None),
            job_id=job_id,
            image_id=image_id,
            page_number=row.get("page_number") if isinstance(row.get("page_number"), int) else None,
            bbox=bbox_raw if isinstance(bbox_raw, dict) else None,
            width_px=row.get("width_px") if isinstance(row.get("width_px"), int) else None,
            height_px=row.get("height_px") if isinstance(row.get("height_px"), int) else None,
            media_type=media_type,
            file_sha256=actual_sha,
            extraction_origin="embedded_document_image",
            extraction_method=str(provenance.get("extraction_method") or "p0.5_image_extraction"),
            provenance_reference=(
                f"{provenance.get('parser_name') or 'parser'}:"
                f"{provenance.get('source_sha256') or 'unknown'}"
            ),
            source_reference=f"curated:images.jsonl:{index}",
            image_source=(
                ImageSourceRef(root="curated", relative_path=str(relative))
                if path is not None and relative
                else None
            ),
            dossier_section=(dossier_sections or {}).get(document_id),
            incoming_triage_state=(incoming_triage or {}).get(image_id),
            triage_status="unsupported",
            triage_reason="Pending inspection.",
            limitations=limitations,
        )
        assets.append(InspectedAsset(record=record, path=path))
    if violations:
        raise P5InputError("; ".join(violations[:8]))
    return assets


def collect_direct_assets(specs: list[DirectAssetSpec]) -> list[InspectedAsset]:
    """Inventory live-only direct assets (uploads, label-source images)."""
    assets: list[InspectedAsset] = []
    for spec in sorted(specs, key=lambda item: (item.document_id, item.image_id, item.key)):
        limitations: list[str] = []
        path = spec.path
        if path is not None and not path.is_file():
            path = None
        if path is None:
            limitations.append("Image bytes are unavailable for this direct asset.")
        digest = sha256_of(path) if path is not None else None
        media_type = detect_media_type(path) if path is not None else None
        image_source = None
        if path is not None and spec.workspace_relative_path:
            if not safe_relative_path(spec.workspace_relative_path):
                raise P5InputError(f"direct asset {spec.key}: unsafe workspace-relative path")
            image_source = ImageSourceRef(
                root="workspace", relative_path=spec.workspace_relative_path
            )
        record = P5AssetRecord(
            asset_id=deterministic_id(
                "P5A",
                spec.project_id,
                spec.document_id,
                spec.image_id,
                digest or "metadata-only",
            ),
            project_id=spec.project_id,
            document_id=spec.document_id,
            document_type=spec.document_type,
            job_id=None,
            image_id=spec.image_id,
            page_number=spec.page_number,
            docx_relationship=spec.docx_relationship,
            bbox=spec.bbox if isinstance(spec.bbox, dict) else None,
            media_type=media_type,
            file_sha256=digest,
            extraction_origin=spec.extraction_origin,
            extraction_method=spec.extraction_method,
            provenance_reference=spec.provenance_reference,
            source_reference=spec.source_reference,
            image_source=image_source,
            dossier_section=spec.dossier_section,
            incoming_triage_state=spec.incoming_triage_state,
            display_name_hint=spec.display_hint or None,
            triage_status="unsupported",
            triage_reason="Pending inspection.",
            limitations=limitations,
        )
        assets.append(InspectedAsset(record=record, path=path, display_hint=spec.display_hint))
    return assets


def inspect_assets(assets: list[InspectedAsset]) -> None:
    """Decode bytes: dimensions, dHash, uniformity, tininess, media support."""
    for asset in assets:
        record = asset.record
        if asset.path is None:
            continue
        if record.media_type is not None and record.media_type not in SUPPORTED_MEDIA_TYPES:
            record.limitations.append(
                f"Unsupported media type {record.media_type}; bytes were not analyzed."
            )
            asset.decode_failed = True
            continue
        try:
            from PIL import Image, ImageStat

            with Image.open(asset.path) as image:
                image.load()
                record.width_px = int(image.width)
                record.height_px = int(image.height)
                grayscale = image.convert("L")
                thumb = grayscale.resize((9, 8))
                flattened = getattr(thumb, "get_flattened_data", None)
                pixels = list(flattened() if callable(flattened) else thumb.getdata())
                bits = 0
                for row in range(8):
                    offset = row * 9
                    for col in range(8):
                        bits = (bits << 1) | int(pixels[offset + col] > pixels[offset + col + 1])
                record.perceptual_hash = f"{bits:016x}"
                record.perceptual_hash_algorithm = "dhash64"
                extrema = grayscale.getextrema()
                stat = ImageStat.Stat(grayscale)
                deviation = float(stat.stddev[0]) if stat.stddev else 0.0
                span_ok = bool(
                    extrema
                    and isinstance(extrema[0], int)
                    and extrema[1] - extrema[0] <= UNIFORM_MAX_EXTREMA_SPAN
                )
                asset.uniform = span_ok or deviation <= UNIFORM_MAX_STDDEV
                asset.tiny = (
                    image.width < TINY_MIN_SIDE_PX
                    or image.height < TINY_MIN_SIDE_PX
                    or image.width * image.height < TINY_MIN_AREA_PX
                )
                record.near_uniform = asset.uniform
                record.tiny = asset.tiny
        except Exception:
            asset.decode_failed = True
            record.limitations.append(
                "Image bytes could not be decoded; dimensions and perceptual hash are unavailable."
            )


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _dims_compatible(a: P5AssetRecord, b: P5AssetRecord) -> bool:
    if None in (a.width_px, a.height_px, b.width_px, b.height_px):
        return False
    assert a.width_px and a.height_px and b.width_px and b.height_px
    for left, right in ((a.width_px, b.width_px), (a.height_px, b.height_px)):
        larger = max(left, right)
        if larger == 0 or abs(left - right) / larger > NEAR_DUPLICATE_DIM_TOLERANCE:
            return False
    return True


class _UnionFind:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            # Deterministic: the lexicographically smaller root wins.
            if root_right < root_left:
                root_left, root_right = root_right, root_left
            self.parent[root_right] = root_left


def cluster_duplicates(
    assets: list[InspectedAsset],
) -> tuple[list[P5DuplicateCluster], dict[str, str]]:
    """Union exact-hash and conservative perceptual links into clusters.

    Returns the cluster records (without OCR evidence yet) and a mapping of
    ``asset_id -> cluster_id``. Only clusters with two or more members are
    materialized. The representative is the usable member with the smallest
    ``asset_id`` (stable under re-runs because IDs are content-derived).
    """
    # Filter is replayable from the serialized records alone: every decoded
    # asset carries a perceptual hash, every undecodable one does not.
    usable = [
        asset
        for asset in assets
        if asset.record.file_sha256 is not None and asset.record.perceptual_hash is not None
    ]
    ordered = sorted(usable, key=lambda item: item.record.asset_id)
    union = _UnionFind([asset.record.asset_id for asset in ordered])

    # Clusters are project-scoped; identical bytes shared across projects are
    # handled by the dedicated cross-document reuse check, not by exclusion.
    by_sha: dict[tuple[str, str], list[InspectedAsset]] = {}
    for asset in ordered:
        assert asset.record.file_sha256 is not None
        key = (asset.record.project_id, asset.record.file_sha256)
        by_sha.setdefault(key, []).append(asset)
    for group in by_sha.values():
        for other in group[1:]:
            union.union(group[0].record.asset_id, other.record.asset_id)

    # Conservative near-duplicate linking between exact-group anchors: same
    # project, compatible dimensions, small dHash distance, usable images.
    anchors = [group[0] for group in by_sha.values()]
    anchors.sort(key=lambda item: item.record.asset_id)
    for index, left in enumerate(anchors):
        left_record = left.record
        if left_record.perceptual_hash is None or left.uniform:
            continue
        for right in anchors[index + 1 :]:
            right_record = right.record
            if right_record.perceptual_hash is None or right.uniform:
                continue
            if left_record.project_id != right_record.project_id:
                continue
            if not _dims_compatible(left_record, right_record):
                continue
            if (
                _hamming(left_record.perceptual_hash, right_record.perceptual_hash)
                <= NEAR_DUPLICATE_MAX_DISTANCE
            ):
                union.union(left_record.asset_id, right_record.asset_id)

    groups: dict[str, list[InspectedAsset]] = {}
    for asset in ordered:
        groups.setdefault(union.find(asset.record.asset_id), []).append(asset)

    clusters: list[P5DuplicateCluster] = []
    membership: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda item: item.record.asset_id)
        representative = members[0]
        member_ids = [asset.record.asset_id for asset in members]
        sha_values = sorted({m.record.file_sha256 for m in members if m.record.file_sha256})
        document_ids = sorted({m.record.document_id for m in members})
        pages = sorted({m.record.page_number for m in members if m.record.page_number is not None})
        kind, exclusion_reason, evidence = _cluster_kind(members, sha_values, document_ids)
        cluster_id = deterministic_id("P5D", representative.record.project_id, *member_ids)
        clusters.append(
            P5DuplicateCluster(
                cluster_id=cluster_id,
                project_id=representative.record.project_id,
                kind=kind,
                representative_asset_id=representative.record.asset_id,
                member_asset_ids=member_ids,
                member_count=len(member_ids),
                document_ids=document_ids,
                page_numbers=[p for p in pages if isinstance(p, int)],
                exact_sha256_values=sha_values,
                linking_evidence=evidence,
                exclusion_reason=exclusion_reason,
            )
        )
        for member_id in member_ids:
            membership[member_id] = cluster_id
    clusters.sort(key=lambda item: item.cluster_id)
    return clusters, membership


def _cluster_kind(
    members: list[InspectedAsset], sha_values: list[str], document_ids: list[str]
) -> tuple[ClusterKind, str, list[str]]:
    representative = members[0].record
    evidence = ["exact_sha256" if len(sha_values) < len(members) else "distinct_bytes"]
    if len(sha_values) > 1:
        evidence.append("perceptual_dhash")
    width, height = representative.width_px, representative.height_px
    wide_banner = width is not None and height is not None and width >= HEADER_ASPECT_RATIO * height
    recurring = len(members) >= HEADER_MIN_OCCURRENCES or len(document_ids) > 1
    small = width is not None and height is not None and max(width, height) <= LOGO_MAX_SIDE_PX
    if wide_banner and recurring:
        evidence.append("wide_short_geometry")
        evidence.append("recurrence")
        return (
            "repeated_text_header",
            "Широкий низкий растр, повторяющийся на многих страницах: это"
            " повторяемый текстовый колонтитул, а не экологическое изображение.",
            sorted(evidence),
        )
    if small and len(document_ids) >= LOGO_MIN_DOCUMENTS:
        evidence.append("small_raster_across_documents")
        return (
            "logo_or_branding",
            "Небольшой растр повторяется в нескольких документах: вероятный"
            " логотип или элемент оформления.",
            sorted(evidence),
        )
    if len(sha_values) == 1:
        return (
            "exact_duplicate",
            "Точная копия (SHA-256) одного изображения; повторы не считаются"
            " независимыми доказательствами.",
            sorted(evidence),
        )
    return (
        "near_duplicate",
        "Перцептивно почти идентичные изображения (dHash); повторы не"
        " считаются независимыми доказательствами.",
        sorted(evidence),
    )
