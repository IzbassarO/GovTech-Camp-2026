"""Read-only P5 service layer: prepared artifacts, asset views, thumbnails.

Serves accepted ``data/results/p5/v1`` artifacts for prepared projects and
job-local ``workspace/data/results/p5`` artifacts for live jobs. Image bytes
are resolved ONLY through validated ``image_source`` references (root-keyed
relative paths) and re-encoded as bounded JPEG thumbnails — original
filesystem paths never leave the server.
"""

from __future__ import annotations

import io
import json
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dalel.api.config import Settings, get_settings
from dalel.api.errors import ApiError

P5_RESULTS_SUBDIR = "p5/v1"
P5_TITLE = "Мультимодальный анализ визуальных доказательств"
P5_SCORE_LABEL = "Приоритет проверки визуальных доказательств"
THUMBNAIL_MAX_SIDE = 512
_THUMBNAIL_JPEG_QUALITY = 82

META_INTEGRATION_NOTICE = (
    "P5 отображается отдельно и будет включён в интегральную оценку после реализации P6 и Meta v2."
)
MODEL_UNAVAILABLE_NOTICE = (
    "Визуальные материалы зарегистрированы, но мультимодальная модель недоступна."
)

# Gallery grouping is presentation logic shared by prepared and live views.
GALLERY_GROUPS: dict[str, str] = {
    "map": "maps",
    "site_plan": "maps",
    "impact_zone_diagram": "maps",
    "satellite_or_aerial_image": "maps",
    "site_photo": "site_photos",
    "industrial_equipment_photo": "site_photos",
    "technical_diagram": "diagrams",
    "process_flow_diagram": "diagrams",
    "chart": "charts_tables",
    "table": "charts_tables",
    "procedural_notice": "procedural",
}


# --- response models ----------------------------------------------------------


class P5SummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_asset_count: int = 0
    assets_with_bytes_count: int = 0
    eligible_asset_count: int = 0
    analyzed_representative_count: int = 0
    excluded_duplicate_count: int = 0
    excluded_low_information_count: int = 0
    excluded_header_or_logo_count: int = 0
    unsupported_asset_count: int = 0
    procedural_asset_count: int = 0
    duplicate_cluster_count: int = 0
    findings_count: int = 0
    review_priority: int = 0
    visual_coverage: float | None = None
    assessment_confidence: float | None = None
    model_status: str = "unavailable"


class P5AssetView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    document_id: str
    document_type: str | None = None
    image_id: str
    page_number: int | None = None
    width_px: int | None = None
    height_px: int | None = None
    triage_status: str
    triage_reason: str
    predicted_class: str | None = None
    classification_confidence: float | None = None
    decision_path: str | None = None
    gallery_group: str
    duplicate_cluster_id: str | None = None
    duplicate_of_asset_id: str | None = None
    procedural_supporting_evidence: bool = False
    eligible_for_analysis: bool = False
    caption: str | None = None
    thumbnail_available: bool = False


class P5ClusterView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    kind: str
    representative_asset_id: str
    member_count: int
    document_ids: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    exclusion_reason: str
    repeated_ocr_text: str | None = None
    linking_evidence: list[str] = Field(default_factory=list)


class P5ProjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    available: bool
    status_reason: str | None = None
    title: str = P5_TITLE
    score_label: str = P5_SCORE_LABEL
    summary: P5SummaryView | None = None
    classifications_by_class: dict[str, int] = Field(default_factory=dict)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    meta_integration_status: str = "pending_p6_meta_v2"
    meta_integration_notice: str = META_INTEGRATION_NOTICE
    limitations: list[str] = Field(default_factory=list)


class P5AssetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    assets: list[P5AssetView] = Field(default_factory=list)
    clusters: list[P5ClusterView] = Field(default_factory=list)


class P5AssetDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    asset: dict[str, Any]
    context: dict[str, Any] | None = None
    classification: dict[str, Any] | None = None
    cluster: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    thumbnail_available: bool = False


class P5FindingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    suppressions: list[dict[str, Any]] = Field(default_factory=list)


# --- artifact bundle ----------------------------------------------------------


@dataclass
class P5Bundle:
    """Parsed P5 artifacts for one results directory (prepared or live)."""

    available: bool
    status_reason: str | None = None
    assets: list[dict[str, Any]] = field(default_factory=list)
    contexts: dict[str, dict[str, Any]] = field(default_factory=dict)
    classifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    suppressions: list[dict[str, Any]] = field(default_factory=list)
    project_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    model_metadata: dict[str, Any] = field(default_factory=dict)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_p5_bundle(results_dir: Path) -> P5Bundle:
    """Load one P5 artifact directory; degrade to unavailable on any defect."""
    required = (
        "assets.jsonl",
        "asset_contexts.jsonl",
        "classifications.jsonl",
        "duplicate_clusters.jsonl",
        "findings.jsonl",
        "suppressions.jsonl",
        "project_scores.jsonl",
        "metrics.json",
        "model_metadata.json",
    )
    missing = [name for name in required if not (results_dir / name).is_file()]
    if missing:
        return P5Bundle(
            available=False,
            status_reason=f"P5 artifacts are missing: {', '.join(missing[:3])}",
        )
    try:
        assets = _read_jsonl(results_dir / "assets.jsonl")
        contexts = {
            str(row.get("asset_id")): row
            for row in _read_jsonl(results_dir / "asset_contexts.jsonl")
        }
        classifications = {
            str(row.get("asset_id")): row
            for row in _read_jsonl(results_dir / "classifications.jsonl")
        }
        clusters = _read_jsonl(results_dir / "duplicate_clusters.jsonl")
        findings = _read_jsonl(results_dir / "findings.jsonl")
        suppressions = _read_jsonl(results_dir / "suppressions.jsonl")
        project_scores = {
            str(row.get("project_id")): row
            for row in _read_jsonl(results_dir / "project_scores.jsonl")
        }
        metrics = json.loads((results_dir / "metrics.json").read_text(encoding="utf-8"))
        model_metadata = json.loads(
            (results_dir / "model_metadata.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return P5Bundle(
            available=False, status_reason=f"P5 artifacts are unreadable: {type(exc).__name__}"
        )
    return P5Bundle(
        available=True,
        assets=assets,
        contexts=contexts,
        classifications=classifications,
        clusters=clusters,
        findings=findings,
        suppressions=suppressions,
        project_scores=project_scores,
        metrics=metrics if isinstance(metrics, dict) else {},
        model_metadata=model_metadata if isinstance(model_metadata, dict) else {},
    )


_PREPARED_LOCK = threading.Lock()
_PREPARED_BUNDLE: P5Bundle | None = None


def get_prepared_bundle(settings: Settings | None = None) -> P5Bundle:
    global _PREPARED_BUNDLE
    with _PREPARED_LOCK:
        if _PREPARED_BUNDLE is None:
            resolved = settings or get_settings()
            _PREPARED_BUNDLE = load_p5_bundle(resolved.results_dir / P5_RESULTS_SUBDIR)
        return _PREPARED_BUNDLE


def reset_prepared_bundle() -> None:
    """Testing hook: drop the cached prepared bundle."""
    global _PREPARED_BUNDLE
    with _PREPARED_LOCK:
        _PREPARED_BUNDLE = None


# --- views --------------------------------------------------------------------


def gallery_group(asset: dict[str, Any], classification: dict[str, Any] | None) -> str:
    status = str(asset.get("triage_status") or "")
    if status == "excluded_duplicate":
        return "excluded_duplicates"
    if status in {
        "excluded_repeated_header",
        "excluded_logo_or_branding",
        "excluded_low_information",
        "unsupported",
    }:
        return "excluded_other"
    if asset.get("procedural_supporting_evidence"):
        return "procedural"
    predicted = str((classification or {}).get("predicted_class") or "unknown")
    return GALLERY_GROUPS.get(predicted, "unknown")


def _asset_view(bundle: P5Bundle, asset: dict[str, Any]) -> P5AssetView:
    asset_id = str(asset.get("asset_id"))
    classification = bundle.classifications.get(asset_id)
    context = bundle.contexts.get(asset_id)
    return P5AssetView(
        asset_id=asset_id,
        document_id=str(asset.get("document_id")),
        document_type=asset.get("document_type"),
        image_id=str(asset.get("image_id")),
        page_number=asset.get("page_number"),
        width_px=asset.get("width_px"),
        height_px=asset.get("height_px"),
        triage_status=str(asset.get("triage_status")),
        triage_reason=str(asset.get("triage_reason") or ""),
        predicted_class=(classification or {}).get("predicted_class"),
        classification_confidence=(classification or {}).get("classification_confidence"),
        decision_path=(classification or {}).get("decision_path"),
        gallery_group=gallery_group(asset, classification),
        duplicate_cluster_id=asset.get("duplicate_cluster_id"),
        duplicate_of_asset_id=asset.get("duplicate_of_asset_id"),
        procedural_supporting_evidence=bool(asset.get("procedural_supporting_evidence")),
        eligible_for_analysis=bool(asset.get("eligible_for_analysis")),
        caption=(context or {}).get("caption"),
        thumbnail_available=bool(asset.get("image_source")),
    )


def _project_assets(bundle: P5Bundle, project_id: str) -> list[dict[str, Any]]:
    return [a for a in bundle.assets if str(a.get("project_id")) == project_id]


def build_project_response(bundle: P5Bundle, project_id: str) -> P5ProjectResponse:
    if not bundle.available:
        return P5ProjectResponse(
            project_id=project_id,
            available=False,
            status_reason=bundle.status_reason
            or "P5 artifacts have not been generated for this dataset.",
            limitations=[MODEL_UNAVAILABLE_NOTICE],
        )
    score = bundle.project_scores.get(project_id)
    if score is None:
        return P5ProjectResponse(
            project_id=project_id,
            available=False,
            status_reason="P5 has no results for this project.",
        )
    project_assets = _project_assets(bundle, project_id)
    asset_ids = {str(a.get("asset_id")) for a in project_assets}
    by_class: dict[str, int] = {}
    for asset_id in asset_ids:
        classification = bundle.classifications.get(asset_id)
        if classification is not None:
            name = str(classification.get("predicted_class") or "unknown")
            by_class[name] = by_class.get(name, 0) + 1
    findings = [f for f in bundle.findings if str(f.get("project_id")) == project_id]
    by_severity: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "info")
        by_severity[severity] = by_severity.get(severity, 0) + 1
    model_status = str(score.get("model_status") or "unavailable")
    limitations = [
        "Классификация — модельная аффинность по сходству, а не подтверждённая точность.",
        "Низкое сходство изображения с текстом — сигнал для проверки, а не противоречие.",
        META_INTEGRATION_NOTICE,
    ]
    if model_status != "available":
        limitations.insert(0, MODEL_UNAVAILABLE_NOTICE)
    summary = P5SummaryView(
        total_asset_count=int(score.get("total_asset_count") or 0),
        assets_with_bytes_count=int(score.get("assets_with_bytes_count") or 0),
        eligible_asset_count=int(score.get("eligible_asset_count") or 0),
        analyzed_representative_count=int(score.get("analyzed_representative_count") or 0),
        excluded_duplicate_count=int(score.get("excluded_duplicate_count") or 0),
        excluded_low_information_count=int(score.get("excluded_low_information_count") or 0),
        excluded_header_or_logo_count=int(score.get("excluded_header_or_logo_count") or 0),
        unsupported_asset_count=int(score.get("unsupported_asset_count") or 0),
        procedural_asset_count=int(score.get("procedural_asset_count") or 0),
        duplicate_cluster_count=int(score.get("duplicate_cluster_count") or 0),
        findings_count=len(findings),
        review_priority=int(score.get("visual_evidence_review_priority_score") or 0),
        visual_coverage=score.get("visual_coverage"),
        assessment_confidence=score.get("assessment_confidence"),
        model_status=model_status,
    )
    return P5ProjectResponse(
        project_id=project_id,
        available=True,
        summary=summary,
        classifications_by_class=dict(sorted(by_class.items())),
        findings_by_severity=dict(sorted(by_severity.items())),
        model_metadata={
            "model_name": bundle.model_metadata.get("model_name"),
            "pretrained_tag": bundle.model_metadata.get("pretrained_tag"),
            "license": bundle.model_metadata.get("license"),
            "device": bundle.model_metadata.get("device"),
            "status": bundle.model_metadata.get("model_status"),
            "ocr": bundle.model_metadata.get("ocr"),
        },
        limitations=limitations,
    )


def build_assets_response(bundle: P5Bundle, project_id: str) -> P5AssetsResponse:
    _require_available(bundle, project_id)
    assets = [_asset_view(bundle, asset) for asset in _project_assets(bundle, project_id)]
    clusters = [
        P5ClusterView(
            cluster_id=str(c.get("cluster_id")),
            kind=str(c.get("kind")),
            representative_asset_id=str(c.get("representative_asset_id")),
            member_count=int(c.get("member_count") or 0),
            document_ids=[str(d) for d in c.get("document_ids") or []],
            page_numbers=[p for p in c.get("page_numbers") or [] if isinstance(p, int)],
            exclusion_reason=str(c.get("exclusion_reason") or ""),
            repeated_ocr_text=c.get("repeated_ocr_text"),
            linking_evidence=[str(v) for v in c.get("linking_evidence") or []],
        )
        for c in bundle.clusters
        if str(c.get("project_id")) == project_id
    ]
    return P5AssetsResponse(project_id=project_id, assets=assets, clusters=clusters)


def build_asset_detail(bundle: P5Bundle, project_id: str, asset_id: str) -> P5AssetDetailResponse:
    _require_available(bundle, project_id)
    asset = next(
        (
            a
            for a in bundle.assets
            if str(a.get("asset_id")) == asset_id and str(a.get("project_id")) == project_id
        ),
        None,
    )
    if asset is None:
        raise ApiError(404, "p5_asset_not_found", "Визуальный актив не найден.")
    cluster = next(
        (
            c
            for c in bundle.clusters
            if str(c.get("cluster_id")) == str(asset.get("duplicate_cluster_id"))
        ),
        None,
    )
    findings = [
        f
        for f in bundle.findings
        if str(f.get("asset_id")) == asset_id or asset_id in (f.get("related_asset_ids") or [])
    ]
    public_asset = dict(asset)
    public_asset.pop("image_source", None)
    return P5AssetDetailResponse(
        project_id=project_id,
        asset=public_asset,
        context=bundle.contexts.get(asset_id),
        classification=bundle.classifications.get(asset_id),
        cluster=cluster,
        findings=findings,
        thumbnail_available=bool(asset.get("image_source")),
    )


def build_findings_response(bundle: P5Bundle, project_id: str) -> P5FindingsResponse:
    _require_available(bundle, project_id)
    return P5FindingsResponse(
        project_id=project_id,
        findings=[f for f in bundle.findings if str(f.get("project_id")) == project_id],
        suppressions=[s for s in bundle.suppressions if str(s.get("project_id")) == project_id],
    )


def _require_available(bundle: P5Bundle, project_id: str) -> None:
    if not bundle.available or project_id not in bundle.project_scores:
        raise ApiError(404, "p5_unavailable", "Результаты P5 недоступны для этого проекта.")


# --- thumbnails ---------------------------------------------------------------


def resolve_asset_image(
    bundle: P5Bundle,
    project_id: str,
    asset_id: str,
    *,
    curated_root: Path | None,
    workspace_root: Path | None,
) -> Path:
    """Resolve the servable image path for an asset with strict confinement."""
    asset = next(
        (
            a
            for a in bundle.assets
            if str(a.get("asset_id")) == asset_id and str(a.get("project_id")) == project_id
        ),
        None,
    )
    source = (asset or {}).get("image_source")
    if not isinstance(source, dict):
        raise ApiError(404, "p5_thumbnail_not_found", "Изображение недоступно.")
    root_kind = str(source.get("root") or "")
    relative = str(source.get("relative_path") or "")
    root: Path | None
    if root_kind == "curated":
        root = curated_root
    elif root_kind == "workspace":
        root = workspace_root
    else:
        root = None
    if root is None or not relative or relative.startswith("/") or "\\" in relative:
        raise ApiError(404, "p5_thumbnail_not_found", "Изображение недоступно.")
    parts = Path(relative).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ApiError(404, "p5_thumbnail_not_found", "Изображение недоступно.")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise ApiError(404, "p5_thumbnail_not_found", "Изображение недоступно.") from None
    if not candidate.is_file():
        raise ApiError(404, "p5_thumbnail_not_found", "Изображение недоступно.")
    return candidate


@lru_cache(maxsize=256)
def _render_thumbnail_cached(path_str: str, mtime_ns: int, max_side: int) -> bytes:
    from PIL import Image

    with Image.open(path_str) as image:
        image.load()
        converted = image.convert("RGB")
        converted.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        converted.save(buffer, format="JPEG", quality=_THUMBNAIL_JPEG_QUALITY)
    return buffer.getvalue()


def render_thumbnail(path: Path, *, max_side: int = THUMBNAIL_MAX_SIDE) -> tuple[bytes, str]:
    try:
        stat = path.stat()
        return (
            _render_thumbnail_cached(str(path), stat.st_mtime_ns, max_side),
            "image/jpeg",
        )
    except ApiError:
        raise
    except Exception:
        raise ApiError(
            404, "p5_thumbnail_not_found", "Изображение не удалось подготовить."
        ) from None


def reset_thumbnail_cache() -> None:
    _render_thumbnail_cached.cache_clear()


ThumbnailScope = Literal["prepared", "live"]
