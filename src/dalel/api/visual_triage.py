"""Deterministic, job-local visual asset inventory for live analysis.

This is preparation for a future P5, not visual risk scoring.  It inventories
uploaded and P0.5-extracted raster bytes, preserves provenance, and applies
only conservative triage rules.  Every candidate remains explicitly
``visual_analysis_status = "not_available"``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

TriageState = Literal[
    "candidate_map",
    "candidate_site_photo",
    "candidate_technical_diagram",
    "candidate_chart",
    "candidate_table",
    "procedural_notice",
    "repeated_text_header",
    "logo_or_branding",
    "stamp_or_signature",
    "qr_code",
    "duplicate",
    "low_information",
    "unknown",
]

_DIRECT_IMAGE_TYPES = {"jpg", "jpeg", "png"}
_PROCEDURAL_SECTIONS = {"procedural_publication_evidence"}
_VISUAL_SECTIONS = {"visual_geographic_materials"}
_DHASH_DISTANCE = 4
# A recurring raster at least this many times wider than tall is a banner-like
# text header (e.g. a scanned applicant-name line repeated on every page), not
# environmental imagery. Detected generically — never by page numbers.
_HEADER_ASPECT_RATIO = 3.0
_REVIEW_TEMPLATE_LOW_INFORMATION_SEED = 5
_REVIEW_TEMPLATE_MAX_ROWS = 25


class VisualAssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    source_document_id: str
    source_file_id: str | None = None
    section_id: str | None = None
    page_number: int | None = None
    docx_relationship: str | None = None
    bbox: dict[str, Any] | None = None
    width_px: int | None = Field(default=None, ge=1)
    height_px: int | None = Field(default=None, ge=1)
    file_sha256: str | None = None
    perceptual_hash: str | None = None
    perceptual_hash_algorithm: Literal["dhash64"] | None = None
    media_type: str | None = None
    extraction_method: str
    extraction_origin: str
    provenance_reference: str
    triage_state: TriageState = "unknown"
    triage_confidence: Literal["high", "medium", "low"] = "low"
    triage_reason: str
    duplicate_of_asset_id: str | None = None
    duplicate_cluster_id: str | None = None
    procedural_supporting_evidence: bool = False
    eligible_for_future_p5: bool = False
    visual_analysis_status: Literal["not_available"] = "not_available"
    limitations: list[str] = Field(default_factory=list)


@dataclass
class _Candidate:
    record: VisualAssetRecord
    path: Path | None
    hint: str
    uniform: bool = False
    tiny: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _media_type(path: Path) -> str | None:
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


def _inspect(candidate: _Candidate) -> None:
    if candidate.path is None:
        return
    try:
        from PIL import Image, ImageStat

        with Image.open(candidate.path) as image:
            image.load()
            candidate.record.width_px = int(image.width)
            candidate.record.height_px = int(image.height)
            grayscale = image.convert("L")
            thumb = grayscale.resize((9, 8))
            flattened = getattr(thumb, "get_flattened_data", None)
            pixels = list(flattened() if callable(flattened) else thumb.getdata())
            bits = 0
            for row in range(8):
                offset = row * 9
                for col in range(8):
                    bits = (bits << 1) | int(pixels[offset + col] > pixels[offset + col + 1])
            candidate.record.perceptual_hash = f"{bits:016x}"
            candidate.record.perceptual_hash_algorithm = "dhash64"

            extrema = cast(tuple[int, int] | None, grayscale.getextrema())
            stat = ImageStat.Stat(grayscale)
            deviation = float(stat.stddev[0]) if stat.stddev else 0.0
            candidate.uniform = bool(extrema and extrema[1] - extrema[0] <= 3) or deviation <= 2.0
            candidate.tiny = (
                image.width < 64 or image.height < 64 or image.width * image.height < 8_192
            )
    except Exception:
        candidate.record.limitations.append(
            "Image bytes could not be decoded; dimensions and perceptual hash are unavailable."
        )


def _asset_id(job_id: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join((job_id, *parts)).encode()).hexdigest()[:20]
    return f"visual_{digest}"


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


def _direct_candidates(
    workspace: Path, job_id: str, inventory: list[dict[str, Any]]
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for item in sorted(inventory, key=lambda row: str(row.get("file_id", ""))):
        media = str(item.get("media_type") or "").lower()
        if media not in _DIRECT_IMAGE_TYPES:
            continue
        internal = str(item.get("internal_path") or "")
        path = _safe_path(workspace, internal)
        if path is None or not path.is_file():
            continue
        file_id = str(item.get("file_id") or "")
        digest = _sha256(path)
        from_archive = item.get("source_origin") == "extracted_archive"
        provenance_reference = (
            f"archive:{item.get('extracted_from')}:{file_id}"
            if from_archive
            else f"upload:{file_id}"
        )
        record = VisualAssetRecord(
            asset_id=_asset_id(job_id, file_id, digest, "direct"),
            source_document_id=file_id,
            source_file_id=file_id,
            section_id=str(item.get("section_id") or "") or None,
            file_sha256=digest,
            media_type=_media_type(path),
            extraction_method=("archive_stream_extraction" if from_archive else "direct_upload"),
            extraction_origin=("extracted_archive_image" if from_archive else "uploaded_image"),
            provenance_reference=provenance_reference,
            triage_reason="No reliable semantic triage rule matched.",
        )
        candidates.append(
            _Candidate(record=record, path=path, hint=str(item.get("display_filename") or ""))
        )
    return candidates


def _curated_candidates(
    workspace: Path,
    job_id: str,
    curated_dir: Path,
    document_sections: dict[str, str],
    document_hints: dict[str, str],
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for index, item in enumerate(_read_jsonl(curated_dir / "images.jsonl"), start=1):
        raw_provenance = item.get("provenance")
        provenance: dict[str, Any] = raw_provenance if isinstance(raw_provenance, dict) else {}
        document_id = str(provenance.get("document_id") or "unknown")
        relative = item.get("curated_image_path")
        path = _safe_path(curated_dir, str(relative)) if relative else None
        if path is not None:
            try:
                path.resolve().relative_to(workspace.resolve())
            except ValueError:
                path = None
        digest = _sha256(path) if path is not None and path.is_file() else None
        image_id = str(item.get("image_id") or f"image_{index}")
        record = VisualAssetRecord(
            asset_id=_asset_id(job_id, document_id, image_id, digest or "metadata-only"),
            source_document_id=document_id,
            section_id=document_sections.get(document_id),
            page_number=item.get("page_number")
            if isinstance(item.get("page_number"), int)
            else None,
            bbox=provenance.get("bbox") if isinstance(provenance.get("bbox"), dict) else None,
            width_px=item.get("width_px") if isinstance(item.get("width_px"), int) else None,
            height_px=item.get("height_px") if isinstance(item.get("height_px"), int) else None,
            file_sha256=digest,
            media_type=_media_type(path) if path is not None and path.is_file() else None,
            extraction_method=str(provenance.get("extraction_method") or "p0.5_image_extraction"),
            extraction_origin="embedded_document_image",
            provenance_reference=f"curated:images.jsonl:{index}",
            triage_reason="No reliable semantic triage rule matched.",
            limitations=(
                [] if digest else ["Parser reported an image but did not provide image bytes."]
            )
            + (
                ["DOCX relationship identifier is unavailable from parser output."]
                if "python-docx" in str(provenance.get("parser_name") or "")
                else []
            ),
        )
        candidates.append(
            _Candidate(record=record, path=path, hint=document_hints.get(document_id, ""))
        )
    return candidates


def _processed_candidates(
    workspace: Path,
    job_id: str,
    processed_root: Path,
    project_id: str,
    document_sections: dict[str, str],
    document_hints: dict[str, str],
    document_roles: dict[str, str],
) -> list[_Candidate]:
    """Inventory parser-extracted images from both leakage-separated trees.

    The curated dataset intentionally contains only model inputs. Reading the
    explicit job document map here also inventories images extracted from
    supporting/label-source documents without allowing their text or tables to
    enter P1--P4 or Meta.
    """
    candidates: list[_Candidate] = []
    for document_id in sorted(document_roles):
        role = document_roles[document_id]
        dirname = "model_inputs" if role == "model_input" else "label_sources"
        document_dir = processed_root / dirname / project_id / document_id
        records_path = document_dir / "images.jsonl"
        for index, item in enumerate(_read_jsonl(records_path), start=1):
            raw_provenance = item.get("provenance")
            provenance: dict[str, Any] = raw_provenance if isinstance(raw_provenance, dict) else {}
            relative = item.get("image_path")
            path = _safe_path(document_dir, str(relative)) if relative else None
            if path is not None:
                try:
                    path.resolve().relative_to(workspace.resolve())
                except ValueError:
                    path = None
            digest = _sha256(path) if path is not None and path.is_file() else None
            image_id = str(item.get("image_id") or f"image_{index}")
            record = VisualAssetRecord(
                asset_id=_asset_id(job_id, document_id, image_id, digest or "metadata-only"),
                source_document_id=document_id,
                section_id=document_sections.get(document_id),
                page_number=(
                    item.get("page_number") if isinstance(item.get("page_number"), int) else None
                ),
                bbox=provenance.get("bbox") if isinstance(provenance.get("bbox"), dict) else None,
                width_px=item.get("width_px") if isinstance(item.get("width_px"), int) else None,
                height_px=item.get("height_px") if isinstance(item.get("height_px"), int) else None,
                file_sha256=digest,
                media_type=_media_type(path) if path is not None and path.is_file() else None,
                extraction_method=str(
                    provenance.get("extraction_method") or "p0.5_image_extraction"
                ),
                extraction_origin="embedded_document_image",
                provenance_reference=f"processed:{dirname}:{document_id}:images.jsonl:{index}",
                triage_reason="No reliable semantic triage rule matched.",
                limitations=(
                    [] if digest else ["Parser reported an image but did not provide image bytes."]
                )
                + (
                    ["DOCX relationship identifier is unavailable from parser output."]
                    if "python-docx" in str(provenance.get("parser_name") or "")
                    else []
                ),
            )
            candidates.append(
                _Candidate(
                    record=record,
                    path=path,
                    hint=document_hints.get(document_id, ""),
                )
            )
    return candidates


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _hint_state(hint: str) -> TriageState | None:
    value = hint.casefold()
    hints: tuple[tuple[TriageState, tuple[str, ...]], ...] = (
        ("candidate_map", ("карта", "map", "генплан", "ситуационн")),
        ("candidate_site_photo", ("фото", "photo", "site image", "объект")),
        ("candidate_technical_diagram", ("чертеж", "схема", "diagram", "drawing")),
        ("candidate_chart", ("график", "chart", "plot")),
        ("candidate_table", ("таблиц", "table")),
        ("qr_code", ("qr-", "qr_", "qrcode", "qr.", "qr ", "куар")),
        ("stamp_or_signature", ("печать", "подпись", "stamp", "signature")),
    )
    for state, words in hints:
        if any(word in value for word in words):
            return state
    return None


def _classify(candidates: list[_Candidate]) -> None:
    for candidate in candidates:
        _inspect(candidate)

    by_hash: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.record.file_sha256:
            by_hash.setdefault(candidate.record.file_sha256, []).append(candidate)

    for sha, group in by_hash.items():
        ordered = sorted(group, key=lambda item: item.record.asset_id)
        canonical = ordered[0]
        repeated_across_docs = len({item.record.source_document_id for item in ordered}) > 1
        if len(ordered) > 1:
            cluster_id = f"cluster_{sha[:16]}"
            for member in ordered:
                member.record.duplicate_cluster_id = cluster_id
        if repeated_across_docs and canonical.tiny:
            canonical.record.triage_state = "logo_or_branding"
            canonical.record.triage_confidence = "medium"
            canonical.record.triage_reason = (
                "The same small raster occurs in more than one source document; "
                "treated as likely branding."
            )
        for duplicate in ordered[1:]:
            duplicate.record.triage_state = "duplicate"
            duplicate.record.triage_confidence = "high"
            duplicate.record.triage_reason = (
                "Exact SHA-256 duplicate of another job-local visual asset."
            )
            duplicate.record.duplicate_of_asset_id = canonical.record.asset_id

    # Conservative near-duplicate detection: identical dimensions, usable
    # non-uniform images, and at most four differing dHash bits.
    ordered = sorted(candidates, key=lambda item: item.record.asset_id)
    for index, candidate in enumerate(ordered):
        if candidate.record.triage_state == "duplicate" or candidate.uniform or candidate.tiny:
            continue
        phash = candidate.record.perceptual_hash
        dimensions = (candidate.record.width_px, candidate.record.height_px)
        if phash is None or None in dimensions:
            continue
        for earlier in ordered[:index]:
            if earlier.uniform or earlier.tiny or earlier.record.perceptual_hash is None:
                continue
            if candidate.record.section_id != earlier.record.section_id:
                continue
            if dimensions != (earlier.record.width_px, earlier.record.height_px):
                continue
            if _hamming(phash, earlier.record.perceptual_hash) <= _DHASH_DISTANCE:
                candidate.record.triage_state = "duplicate"
                candidate.record.triage_confidence = "medium"
                candidate.record.triage_reason = (
                    "Conservative dHash near-duplicate match with identical pixel dimensions."
                )
                candidate.record.duplicate_of_asset_id = earlier.record.asset_id
                if earlier.record.duplicate_cluster_id is None:
                    earlier.record.duplicate_cluster_id = (
                        f"cluster_{earlier.record.asset_id.removeprefix('visual_')}"
                    )
                candidate.record.duplicate_cluster_id = earlier.record.duplicate_cluster_id
                break

    # Repeated banner-like text headers: a cluster that recurs (three or more
    # occurrences, or across documents) whose representative is much wider
    # than tall is procedural page furniture (e.g. a repeated applicant-name
    # line), never an environmental visual signal. Generic by construction —
    # driven only by recurrence and shape, never by asset numbering.
    clusters: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.record.duplicate_cluster_id is not None:
            clusters.setdefault(candidate.record.duplicate_cluster_id, []).append(candidate)
    for members in clusters.values():
        representatives = [m for m in members if m.record.triage_state != "duplicate"]
        canonical = min(representatives or members, key=lambda item: item.record.asset_id)
        width = canonical.record.width_px
        height = canonical.record.height_px
        spans_documents = len({m.record.source_document_id for m in members}) > 1
        if (
            width is not None
            and height is not None
            and width >= _HEADER_ASPECT_RATIO * height
            and (len(members) >= 3 or spans_documents)
            and canonical.record.triage_state in {"unknown", "logo_or_branding", "low_information"}
        ):
            canonical.record.triage_state = "repeated_text_header"
            canonical.record.triage_confidence = "medium"
            canonical.record.triage_reason = (
                "Wide, short raster repeated across pages or documents; treated as a "
                "repeated text header, not environmental imagery."
            )

    for candidate in candidates:
        record = candidate.record
        if record.section_id in _PROCEDURAL_SECTIONS:
            record.procedural_supporting_evidence = True
        if record.triage_state in {"duplicate", "logo_or_branding", "repeated_text_header"}:
            continue
        if candidate.uniform or candidate.tiny:
            record.triage_state = "low_information"
            record.triage_confidence = "high" if candidate.uniform else "medium"
            record.triage_reason = (
                "Raster is blank or near-uniform."
                if candidate.uniform
                else "Raster is too small for reliable downstream visual analysis."
            )
            continue
        if record.section_id in _PROCEDURAL_SECTIONS:
            record.triage_state = "procedural_notice"
            record.triage_confidence = "high"
            record.triage_reason = (
                "Source dossier section is procedural publication evidence, "
                "not environmental imagery."
            )
            continue
        hinted = _hint_state(candidate.hint)
        if record.section_id in _VISUAL_SECTIONS and hinted is not None:
            record.triage_state = hinted
            record.triage_confidence = "low"
            record.triage_reason = (
                "Low-confidence filename hint within the visual/geographic dossier section."
            )
        elif hinted in {"stamp_or_signature", "qr_code"}:
            record.triage_state = hinted
            record.triage_confidence = "low"
            record.triage_reason = "Low-confidence filename hint; no semantic model was used."
        record.eligible_for_future_p5 = record.triage_state in {
            "candidate_map",
            "candidate_site_photo",
            "candidate_technical_diagram",
            "candidate_chart",
            "candidate_table",
        }


def _review_template_rows(records: list[VisualAssetRecord]) -> list[dict[str, Any]]:
    """Seed rows for optional expert review of the deterministic triage.

    A small representative sample — cluster representatives, every retained
    candidate, and a few excluded examples — so an expert can correct the
    conservative predictions without labelling every raster. Written only
    into the ephemeral job workspace; never into tracked annotations.
    """
    seeds: list[VisualAssetRecord] = []
    seen: set[str] = set()

    def add(record: VisualAssetRecord) -> None:
        if record.asset_id not in seen and len(seeds) < _REVIEW_TEMPLATE_MAX_ROWS:
            seen.add(record.asset_id)
            seeds.append(record)

    cluster_seen: set[str] = set()
    for record in records:
        if record.triage_state in {
            "candidate_map",
            "candidate_site_photo",
            "candidate_technical_diagram",
            "candidate_chart",
            "candidate_table",
            "repeated_text_header",
            "logo_or_branding",
            "stamp_or_signature",
            "qr_code",
            "procedural_notice",
        }:
            add(record)
        if record.duplicate_cluster_id and record.duplicate_cluster_id not in cluster_seen:
            cluster_seen.add(record.duplicate_cluster_id)
            add(record)
    low_information_added = 0
    for record in records:
        if record.triage_state == "low_information":
            add(record)
            low_information_added += 1
            if low_information_added >= _REVIEW_TEMPLATE_LOW_INFORMATION_SEED:
                break

    return [
        {
            "asset_id": record.asset_id,
            "predicted_category": record.triage_state,
            "reviewed_category": None,
            "is_useful_for_p5": None,
            "duplicate_cluster_id": record.duplicate_cluster_id,
            "reviewer_note": None,
        }
        for record in sorted(seeds, key=lambda item: item.asset_id)
    ]


def build_visual_inventory(
    workspace: Path,
    *,
    job_id: str,
    curated_dir: Path | None,
    inventory: list[dict[str, Any]],
    processed_root: Path | None = None,
    project_id: str | None = None,
    document_sections: dict[str, str] | None = None,
    document_hints: dict[str, str] | None = None,
    document_roles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build and persist a deterministic job-local visual inventory."""
    workspace = workspace.resolve()
    candidates = _direct_candidates(workspace, job_id, inventory)
    if (
        processed_root is not None
        and project_id is not None
        and processed_root.is_dir()
        and document_roles
    ):
        candidates.extend(
            _processed_candidates(
                workspace,
                job_id,
                processed_root.resolve(),
                project_id,
                document_sections or {},
                document_hints or {},
                document_roles,
            )
        )
    elif curated_dir is not None and curated_dir.is_dir():
        candidates.extend(
            _curated_candidates(
                workspace,
                job_id,
                curated_dir.resolve(),
                document_sections or {},
                document_hints or {},
            )
        )
    _classify(candidates)
    records = sorted((item.record for item in candidates), key=lambda item: item.asset_id)

    output_dir = workspace / "visual"
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "visual_assets.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")
    review_rows = _review_template_rows(records)
    with (output_dir / "review_template.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in review_rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
    by_state: dict[str, int] = {}
    for record in records:
        by_state[record.triage_state] = by_state.get(record.triage_state, 0) + 1
    cluster_ids = {record.duplicate_cluster_id for record in records if record.duplicate_cluster_id}
    header_clusters = {
        record.duplicate_cluster_id
        for record in records
        if record.duplicate_cluster_id and record.triage_state == "repeated_text_header"
    }
    summary = {
        "assets_total": len(records),
        "assets_with_bytes": sum(record.file_sha256 is not None for record in records),
        "exact_or_near_duplicates": sum(record.triage_state == "duplicate" for record in records),
        "duplicate_clusters": len(cluster_ids),
        "repeated_header_clusters": len(header_clusters),
        "review_template_rows": len(review_rows),
        "by_triage_state": dict(sorted(by_state.items())),
        "visual_analysis_status": "not_available",
        "geospatial_analysis_status": "not_available",
        "limitations": [
            "Triage is deterministic metadata filtering, not semantic visual analysis.",
            "Filename-derived candidate labels are low-confidence hints only.",
            "Procedural notices are supporting evidence and are not environmental-risk imagery.",
            "The review template is an optional seed sample, not a complete labelling task.",
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        **summary,
        "assets": [record.model_dump(mode="json") for record in records],
    }
