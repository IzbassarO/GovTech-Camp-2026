"""P5 Multimodal Visual Evidence: pillar, checks, scoring and validation.

Model and OCR are deterministic test doubles — no weights, no network. The
synthetic curated dataset exercises the generic duplicate/header/logo rules,
caption/context linkage, the conservative checks and the independent
validator's tamper detection.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from dalel.pillars.multimodal_visual_evidence.assets import DirectAssetSpec
from dalel.pillars.multimodal_visual_evidence.embeddings import (
    DeterministicStubBackend,
    UnavailableBackend,
)
from dalel.pillars.multimodal_visual_evidence.input_contract import P5InputError
from dalel.pillars.multimodal_visual_evidence.ocr import StubOcrEngine
from dalel.pillars.multimodal_visual_evidence.pipeline import (
    P5Options,
    P5RunResult,
    run_p5,
)
from dalel.pillars.multimodal_visual_evidence.validation import validate_p5_outputs

PROJECT_A = "project_101_testa"
PROJECT_B = "project_102_testb"
DOC_A = f"{PROJECT_A}__ndv__001"
DOC_B = f"{PROJECT_A}__pek__001"
DOC_C = f"{PROJECT_A}__action_plan__001"
DOC_OTHER = f"{PROJECT_B}__ndv__001"

MAP_VEC = [1.0, 0.0, 0.0, 0.0]
PHOTO_VEC = [0.0, 1.0, 0.0, 0.0]
CHART_VEC = [0.0, 0.0, 1.0, 0.0]
DEFAULT_VEC = [0.0, 0.0, 0.0, 1.0]
AMBIGUOUS_VEC = [0.7071, 0.7071, 0.0, 0.0]


def _png(width: int, height: int, seed: int, *, uniform: bool = False) -> bytes:
    image = Image.new("RGB", (width, height), (240, 240, 240) if uniform else "white")
    if not uniform:
        draw = ImageDraw.Draw(image)
        for index in range(0, width, 12):
            shade = (index * 7 + seed * 31) % 255
            draw.line([(index, 0), (index, height)], fill=(shade, 128, 255 - shade), width=3)
        draw.ellipse(
            [width // 4, height // 4, 3 * width // 4, 3 * height // 4],
            outline=(seed * 13 % 255, 40, 90),
            width=4,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _near_variant(payload: bytes) -> bytes:
    """Perceptually identical PNG with a one-pixel difference."""
    with Image.open(io.BytesIO(payload)) as image:
        copy = image.copy()
    pixel = copy.getpixel((0, 0))
    assert isinstance(pixel, tuple)
    copy.putpixel((0, 0), tuple(min(255, value + 2) for value in pixel[:3]))
    buffer = io.BytesIO()
    copy.save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class MiniDataset:
    dataset_dir: Path
    annotations_root: Path
    output_dir: Path
    p4_dir: Path
    p3_dir: Path


def build_dataset(root: Path) -> MiniDataset:
    dataset_dir = root / "data" / "curated" / "v1"
    images_dir = dataset_dir / "images"
    images_dir.mkdir(parents=True)
    annotations_root = root / "data" / "annotations"
    output_dir = root / "data" / "results" / "p5" / "v1"
    p4_dir = root / "data" / "results" / "p4" / "v1"
    p3_dir = root / "data" / "results" / "p3" / "v1"
    for directory in (annotations_root, p4_dir, p3_dir):
        directory.mkdir(parents=True)

    projects = [
        {"project_id": PROJECT_A, "region": "pavlodar", "industry": "food_production"},
        {"project_id": PROJECT_B, "region": "aktobe", "industry": "mining"},
    ]
    documents = [
        {"project_id": PROJECT_A, "document_id": DOC_A, "document_type": "ndv"},
        {"project_id": PROJECT_A, "document_id": DOC_B, "document_type": "pek"},
        {"project_id": PROJECT_A, "document_id": DOC_C, "document_type": "action_plan"},
        {"project_id": PROJECT_B, "document_id": DOC_OTHER, "document_type": "ndv"},
    ]

    banner = _png(480, 60, seed=5)
    banner_variant = _near_variant(banner)
    map_png = _png(500, 400, seed=1)
    photo = _png(420, 320, seed=2)
    chart = _png(400, 300, seed=3)
    logo = _png(100, 100, seed=4)
    tiny = _png(16, 16, seed=6)
    blank = _png(200, 200, seed=7, uniform=True)
    mismatch_photo = _png(430, 330, seed=8)

    files: list[tuple[str, str, int, bytes]] = [
        # (document_id, image_id, page_number, payload)
        (DOC_A, "img_map", 1, map_png),
        (DOC_A, "img_banner_1", 2, banner),
        (DOC_A, "img_banner_2", 3, banner),
        (DOC_A, "img_banner_3", 4, banner),
        (DOC_A, "img_banner_4", 5, banner),
        (DOC_A, "img_banner_5", 6, banner_variant),
        (DOC_A, "img_tiny", 7, tiny),
        (DOC_A, "img_blank", 7, blank),
        (DOC_A, "img_logo", 8, logo),
        (DOC_A, "img_photo", 9, photo),
        (DOC_B, "img_logo_b", 1, logo),
        (DOC_B, "img_photo_dup", 2, photo),
        (DOC_B, "img_chart_1", 3, chart),
        (DOC_B, "img_chart_2", 4, chart),
        (DOC_B, "img_chart_3", 5, chart),
        (DOC_B, "img_chart_4", 6, chart),
        (DOC_B, "img_chart_5", 7, chart),
        (DOC_B, "img_mismatch", 8, mismatch_photo),
    ]

    image_rows: list[dict[str, object]] = []
    for document_id, image_id, page_number, payload in files:
        relative = f"images/{document_id}/{image_id}.png"
        target = dataset_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
        project_id = PROJECT_A if document_id != DOC_OTHER else PROJECT_B
        image_rows.append(
            {
                "schema_version": "1.0.0",
                "image_id": image_id,
                "page_number": page_number,
                "width_px": width,
                "height_px": height,
                "curated_image_path": relative,
                "image_sha256": hashlib.sha256(payload).hexdigest(),
                "provenance": {
                    "project_id": project_id,
                    "document_id": document_id,
                    "document_type": document_id.rsplit("__", 2)[1],
                    "extraction_method": "docling",
                    "parser_name": "docling",
                    "source_sha256": "0" * 64,
                },
            }
        )

    pages = [
        {
            "page_number": 1,
            "text": (
                "ТОО «Тестовый оператор» подготовило материалы. См. рис. 1.\n"
                "Рисунок 1 — Карта расположения объекта"
            ),
            "provenance": {"document_id": DOC_A},
        },
        {
            "page_number": 9,
            "text": "Сведения о мероприятиях и отчетность за период.",
            "provenance": {"document_id": DOC_A},
        },
        {
            "page_number": 8,
            "text": "Рисунок 2 — Карта санитарной зоны объекта",
            "provenance": {"document_id": DOC_B},
        },
        {
            "page_number": 1,
            "text": "Как показано на рисунок 1 и рисунок 2, план мероприятий утверждён.",
            "provenance": {"document_id": DOC_C},
        },
        {
            "page_number": 2,
            "text": "Дополнительно см. схема 3 с границами участка.",
            "provenance": {"document_id": DOC_C},
        },
    ]
    sections = [
        {
            "section_id": f"{DOC_A}__sec_0001",
            "title": "Общие сведения",
            "page_start": 1,
            "page_end": 9,
            "provenance": {"document_id": DOC_A},
        }
    ]

    def _write_jsonl(name: str, rows: list[dict[str, object]]) -> None:
        with (dataset_dir / name).open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False))
                handle.write("\n")

    _write_jsonl("projects.jsonl", projects)
    _write_jsonl("documents.jsonl", documents)
    _write_jsonl("images.jsonl", image_rows)
    _write_jsonl("pages.jsonl", pages)
    _write_jsonl("sections.jsonl", sections)

    checksums = []
    for name in ("projects.jsonl", "documents.jsonl", "images.jsonl", "pages.jsonl"):
        checksums.append(
            {
                "file": name,
                "sha256": hashlib.sha256((dataset_dir / name).read_bytes()).hexdigest(),
            }
        )
    _write_jsonl("checksums.jsonl", checksums)
    (dataset_dir / "build_report.json").write_text(
        json.dumps({"input_fingerprint": "f" * 64}) + "\n", encoding="utf-8"
    )

    (p4_dir / "entities.jsonl").write_text(
        json.dumps(
            {
                "entity_id": "P4E__000000000001",
                "project_id": PROJECT_A,
                "entity_type": "organization",
                "canonical_label": "ТОО «Тестовый оператор»",
                "aliases": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (p3_dir / "mentions.jsonl").write_text(
        json.dumps(
            {
                "mention_id": "P3Q__000000000001",
                "project_id": PROJECT_A,
                "document_id": DOC_A,
                "location": {"source_kind": "section_text", "page_number": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return MiniDataset(dataset_dir, annotations_root, output_dir, p4_dir, p3_dir)


def stub_backend() -> DeterministicStubBackend:
    return DeterministicStubBackend(
        image_vectors={
            "img_map": MAP_VEC,
            "img_photo": PHOTO_VEC,
            "img_photo_dup": PHOTO_VEC,
            "img_chart": CHART_VEC,
            "img_mismatch": PHOTO_VEC,
            "img_ambiguous": AMBIGUOUS_VEC,
            "img_upload": PHOTO_VEC,
        },
        text_vectors={
            "карта": MAP_VEC,
            "map": MAP_VEC,
            "фотография промышленной площадки": PHOTO_VEC,
            "фотография территории": PHOTO_VEC,
            "photograph of an industrial": PHOTO_VEC,
            "график": CHART_VEC,
            "диаграмма": CHART_VEC,
            "chart with axes": CHART_VEC,
            "таблица": [0.0, 0.0, 0.9, 0.1],
        },
        default=DEFAULT_VEC,
    )


def stub_ocr() -> StubOcrEngine:
    return StubOcrEngine(
        texts={
            "img_map": "Карта расположения объекта без легенды",
            "img_chart": "Выбросы мг/м3 25 30 45",
            "img_banner": 'ФЛ "Тестовый заявитель"',
        }
    )


def run_pipeline(root: Path, **overrides: object) -> tuple[MiniDataset, P5RunResult]:
    dataset = build_dataset(root)
    options = P5Options(
        dataset_dir=dataset.dataset_dir,
        output_dir=dataset.output_dir,
        annotations_root=dataset.annotations_root,
        p3_dir=dataset.p3_dir,
        p4_dir=dataset.p4_dir,
        backend=stub_backend(),
        ocr_engine=stub_ocr(),
    )
    for key, value in overrides.items():
        setattr(options, key, value)
    return dataset, run_p5(options)


@pytest.fixture(scope="module")
def shared(tmp_path_factory: pytest.TempPathFactory) -> tuple[MiniDataset, P5RunResult]:
    return run_pipeline(tmp_path_factory.mktemp("p5"))


def _by_image(result: P5RunResult) -> dict[str, object]:
    return {asset.image_id: asset for asset in result.assets}


# --- assets and provenance ----------------------------------------------------


def test_asset_ids_content_derived_and_unique(shared) -> None:
    _, result = shared
    ids = [asset.asset_id for asset in result.assets]
    assert len(set(ids)) == len(ids)
    assert all(identifier.startswith("P5A__") for identifier in ids)
    assets = _by_image(result)
    map_asset = assets["img_map"]
    assert map_asset.document_id == DOC_A
    assert map_asset.page_number == 1
    assert map_asset.file_sha256 is not None
    assert map_asset.image_source is not None
    assert map_asset.image_source.root == "curated"
    assert not map_asset.image_source.relative_path.startswith("/")


def test_unsafe_curated_path_rejected(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    rows = (dataset.dataset_dir / "images.jsonl").read_text().splitlines()
    row = json.loads(rows[0])
    row["curated_image_path"] = "../../../etc/passwd"
    rows[0] = json.dumps(row, ensure_ascii=False)
    (dataset.dataset_dir / "images.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(P5InputError, match="unsafe"):
        run_p5(
            P5Options(
                dataset_dir=dataset.dataset_dir,
                output_dir=dataset.output_dir,
                annotations_root=dataset.annotations_root,
                backend=stub_backend(),
                ocr_engine=stub_ocr(),
            )
        )


def test_provenance_sha_mismatch_rejected(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    rows = (dataset.dataset_dir / "images.jsonl").read_text().splitlines()
    row = json.loads(rows[0])
    row["image_sha256"] = "a" * 64
    rows[0] = json.dumps(row, ensure_ascii=False)
    (dataset.dataset_dir / "images.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(P5InputError, match="sha256"):
        run_p5(
            P5Options(
                dataset_dir=dataset.dataset_dir,
                output_dir=dataset.output_dir,
                annotations_root=dataset.annotations_root,
                backend=stub_backend(),
                ocr_engine=stub_ocr(),
            )
        )


def test_direct_upload_asset_analyzed(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    upload_dir = tmp_path / "workspace" / "input"
    upload_dir.mkdir(parents=True)
    payload = _png(300, 220, seed=9)
    (upload_dir / "img_upload.png").write_bytes(payload)
    spec = DirectAssetSpec(
        key="LIVEFILE__0001",
        path=upload_dir / "img_upload.png",
        project_id=PROJECT_A,
        document_id="LIVEFILE__0001",
        image_id="img_upload",
        extraction_origin="uploaded_image",
        extraction_method="direct_upload",
        provenance_reference="upload:LIVEFILE__0001",
        source_reference="intake:LIVEFILE__0001",
        workspace_relative_path="input/img_upload.png",
        dossier_section="visual_geographic_materials",
        display_hint="фото площадки.png",
    )
    _, result = (
        dataset,
        run_p5(
            P5Options(
                dataset_dir=dataset.dataset_dir,
                output_dir=dataset.output_dir,
                annotations_root=dataset.annotations_root,
                direct_assets=[spec],
                backend=stub_backend(),
                ocr_engine=stub_ocr(),
            )
        ),
    )
    uploaded = _by_image(result)["img_upload"]
    assert uploaded.extraction_origin == "uploaded_image"
    assert uploaded.triage_status == "analyzed_representative"
    assert uploaded.image_source is not None and uploaded.image_source.root == "workspace"
    classification = {c.asset_id: c for c in result.classifications}[uploaded.asset_id]
    assert classification.predicted_class == "site_photo"


# --- duplicates ---------------------------------------------------------------


def test_repeated_banner_clusters_with_near_duplicate(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    banner_ids = {assets[f"img_banner_{i}"].asset_id for i in range(1, 6)}
    clusters = [c for c in result.clusters if banner_ids & set(c.member_asset_ids)]
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.kind == "repeated_text_header"
    assert cluster.member_count == 5  # 4 exact copies + 1 near-duplicate variant
    assert "wide_short_geometry" in cluster.linking_evidence
    assert cluster.repeated_ocr_text is not None
    representative = assets[
        next(
            i
            for i in (
                "img_banner_1",
                "img_banner_2",
                "img_banner_3",
                "img_banner_4",
                "img_banner_5",
            )
            if assets[i].asset_id == cluster.representative_asset_id
        )
    ]
    assert representative.triage_status == "excluded_repeated_header"
    members = [a for a in result.assets if a.asset_id in cluster.member_asset_ids]
    duplicates = [a for a in members if a.triage_status == "excluded_duplicate"]
    assert len(duplicates) == 4
    assert all(d.duplicate_of_asset_id == cluster.representative_asset_id for d in duplicates)


def test_logo_across_documents_excluded(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    logo_cluster = next(
        c for c in result.clusters if assets["img_logo"].asset_id in c.member_asset_ids
    )
    assert logo_cluster.kind == "logo_or_branding"
    assert set(logo_cluster.document_ids) == {DOC_A, DOC_B}
    representative = next(
        a for a in result.assets if a.asset_id == logo_cluster.representative_asset_id
    )
    assert representative.triage_status == "excluded_logo_or_branding"


def test_low_information_exclusions(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    assert assets["img_tiny"].triage_status == "excluded_low_information"
    assert assets["img_blank"].triage_status == "excluded_low_information"


def test_representative_stability_across_runs(tmp_path: Path) -> None:
    _, first = run_pipeline(tmp_path / "one")
    _, second = run_pipeline(tmp_path / "two")
    reps_first = sorted(c.representative_asset_id for c in first.clusters)
    reps_second = sorted(c.representative_asset_id for c in second.clusters)
    assert reps_first == reps_second


def test_duplicates_do_not_inflate_priority(shared) -> None:
    _, result = shared
    score = next(s for s in result.project_scores if s.project_id == PROJECT_A)
    # 5 chart copies contribute at most one duplicate-inflation finding, and
    # excluded duplicates never enter the analyzed pool.
    inflation = [f for f in result.findings if f.finding_type == "duplicate_visual_inflation"]
    assert len(inflation) == 1
    assert score.excluded_duplicate_count >= 8  # banners + charts + photo + logo copies
    assert score.analyzed_representative_count == len(
        [a for a in result.assets if a.triage_status == "analyzed_representative"]
    )


# --- classification -----------------------------------------------------------


def test_map_and_chart_classified_by_model(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    classifications = {c.asset_id: c for c in result.classifications}
    map_classification = classifications[assets["img_map"].asset_id]
    assert map_classification.predicted_class == "map"
    assert map_classification.decision_path == "model_zero_shot"
    assert map_classification.classification_confidence is not None
    chart_representative = next(
        c for c in result.clusters if assets["img_chart_1"].asset_id in c.member_asset_ids
    ).representative_asset_id
    assert classifications[chart_representative].predicted_class == "chart"


def test_unknown_without_model(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    result = run_p5(
        P5Options(
            dataset_dir=dataset.dataset_dir,
            output_dir=dataset.output_dir,
            annotations_root=dataset.annotations_root,
            backend=UnavailableBackend(reason="test"),
            ocr_engine=stub_ocr(),
        )
    )
    assert all(c.model_status == "unavailable" for c in result.classifications)
    assert all(c.predicted_class == "unknown" for c in result.classifications)
    assert result.metrics["model_status"] == "unavailable"
    score = next(s for s in result.project_scores if s.project_id == PROJECT_A)
    assert score.model_status == "unavailable"
    assert score.visual_coverage == 0.0
    # Degraded runs still validate end to end.
    validation = validate_p5_outputs(dataset.dataset_dir, dataset.output_dir)
    assert validation.ok, validation.errors


def test_procedural_direct_asset_separated(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    upload_dir = tmp_path / "workspace" / "input"
    upload_dir.mkdir(parents=True)
    (upload_dir / "img_upload.png").write_bytes(_png(600, 800, seed=11))
    spec = DirectAssetSpec(
        key="LIVEFILE__0002",
        path=upload_dir / "img_upload.png",
        project_id=PROJECT_A,
        document_id="LIVEFILE__0002",
        image_id="img_upload_notice",
        extraction_origin="uploaded_image",
        extraction_method="direct_upload",
        provenance_reference="upload:LIVEFILE__0002",
        source_reference="intake:LIVEFILE__0002",
        workspace_relative_path="input/img_upload.png",
        dossier_section="procedural_publication_evidence",
        display_hint="объявление.png",
    )
    result = run_p5(
        P5Options(
            dataset_dir=dataset.dataset_dir,
            output_dir=dataset.output_dir,
            annotations_root=dataset.annotations_root,
            direct_assets=[spec],
            backend=stub_backend(),
            ocr_engine=stub_ocr(),
        )
    )
    notice = _by_image(result)["img_upload_notice"]
    classification = {c.asset_id: c for c in result.classifications}[notice.asset_id]
    assert classification.predicted_class == "procedural_notice"
    assert classification.decision_path == "deterministic_supporting"
    assert notice.procedural_supporting_evidence is True
    # Procedural assets never enter the environmental checks.
    assert not any(f.asset_id == notice.asset_id for f in result.findings)


def test_ambiguous_image_is_honestly_unknown(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    ambiguous = _png(320, 260, seed=12)
    target = dataset.dataset_dir / "images" / DOC_A / "img_ambiguous.png"
    target.write_bytes(ambiguous)
    rows = (dataset.dataset_dir / "images.jsonl").read_text().splitlines()
    rows.append(
        json.dumps(
            {
                "image_id": "img_ambiguous",
                "page_number": 9,
                "width_px": 320,
                "height_px": 260,
                "curated_image_path": f"images/{DOC_A}/img_ambiguous.png",
                "image_sha256": hashlib.sha256(ambiguous).hexdigest(),
                "provenance": {"project_id": PROJECT_A, "document_id": DOC_A},
            },
            ensure_ascii=False,
        )
    )
    (dataset.dataset_dir / "images.jsonl").write_text("\n".join(rows) + "\n")
    # Refresh the checksum so the tamper check stays quiet.
    checksums = []
    for name in ("projects.jsonl", "documents.jsonl", "images.jsonl", "pages.jsonl"):
        checksums.append(
            {
                "file": name,
                "sha256": hashlib.sha256((dataset.dataset_dir / name).read_bytes()).hexdigest(),
            }
        )
    with (dataset.dataset_dir / "checksums.jsonl").open("w", encoding="utf-8") as handle:
        for row in checksums:
            handle.write(json.dumps(row) + "\n")

    result = run_p5(
        P5Options(
            dataset_dir=dataset.dataset_dir,
            output_dir=dataset.output_dir,
            annotations_root=dataset.annotations_root,
            backend=stub_backend(),
            ocr_engine=stub_ocr(),
        )
    )
    ambiguous_asset = _by_image(result)["img_ambiguous"]
    classification = {c.asset_id: c for c in result.classifications}[ambiguous_asset.asset_id]
    # Equal similarity to map and photo prompts: margin below threshold.
    assert classification.predicted_class == "unknown"
    assert classification.decision_path == "unknown_fallback"


# --- context ------------------------------------------------------------------


def test_caption_heading_and_entity_linkage(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    context = {c.asset_id: c for c in result.contexts}[assets["img_map"].asset_id]
    assert context.caption is not None and context.caption.startswith("Рисунок 1")
    assert context.nearest_heading == "Общие сведения"
    assert context.page_text_excerpt
    assert "тоо «тестовый оператор" in context.entity_terms_matched
    assert context.quantitative_mentions_on_page == 1
    assert context.image_caption_similarity is not None
    assert context.image_caption_similarity > 0.9  # map image vs «Карта…» caption


def test_absent_context_recorded(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    context = {c.asset_id: c for c in result.contexts}[assets["img_mismatch"].asset_id]
    # Page text exists for page 8 of DOC_B; caption comes from that page.
    assert context.caption is not None
    photo_context = {c.asset_id: c for c in result.contexts}[assets["img_photo"].asset_id]
    assert photo_context.caption is None
    assert photo_context.caption_source == "none"


# --- findings -----------------------------------------------------------------


def test_caption_image_mismatch_finding(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    mismatch = [
        f
        for f in result.findings
        if f.finding_type == "caption_image_mismatch"
        and f.asset_id == assets["img_mismatch"].asset_id
    ]
    assert len(mismatch) == 1
    finding = mismatch[0]
    assert finding.severity == "low"
    assert finding.legal_conclusion is False
    assert any(e.kind == "caption" and e.quote for e in finding.evidence)
    assert finding.limitations


def test_missing_referenced_visual_finding(shared) -> None:
    _, result = shared
    findings = [
        f
        for f in result.findings
        if f.finding_type == "missing_referenced_visual" and f.document_id == DOC_C
    ]
    assert len(findings) == 1
    assert findings[0].severity == "low"
    assert any(e.kind == "page_text" for e in findings[0].evidence)


def test_map_completeness_cue_finding(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    cues = [
        f
        for f in result.findings
        if f.finding_type == "map_completeness_cue" and f.asset_id == assets["img_map"].asset_id
    ]
    assert len(cues) == 1
    assert cues[0].severity == "info"
    assert any(signal.startswith("cue_absent:") for signal in cues[0].deterministic_signals)


def test_cross_document_reuse_finding(shared) -> None:
    _, result = shared
    reuse = [f for f in result.findings if f.finding_type == "cross_document_visual_reuse"]
    assert len(reuse) == 1
    finding = reuse[0]
    assert finding.severity == "low"
    assert finding.document_id is None  # package-level
    assert finding.duplicate_cluster_id is not None


def test_no_high_severity_and_no_legal_conclusions(shared) -> None:
    _, result = shared
    assert result.findings, "the synthetic corpus must produce findings"
    assert all(f.severity in {"medium", "low", "info"} for f in result.findings)
    assert all(f.legal_conclusion is False for f in result.findings)
    assert all(f.limitations.strip() for f in result.findings)
    assert all(f.evidence for f in result.findings)


def test_relevance_review_requires_double_low_similarity(shared) -> None:
    _, result = shared
    assets = _by_image(result)
    relevance = [f for f in result.findings if f.finding_type == "visual_relevance_review"]
    # img_photo: photo embedding vs unrelated page text (zero cosine).
    assert any(f.asset_id == assets["img_photo"].asset_id for f in relevance)
    # img_map is well aligned with its caption: never flagged.
    assert all(f.asset_id != assets["img_map"].asset_id for f in relevance)


# --- scoring / artifacts ------------------------------------------------------


def test_scores_and_meta_integration_status(shared) -> None:
    _, result = shared
    score = next(s for s in result.project_scores if s.project_id == PROJECT_A)
    assert score.meta_integration_status == "pending_p6_meta_v2"
    assert 0 <= score.visual_evidence_review_priority_score <= 100
    assert score.visual_coverage == 1.0
    assert 0.05 <= score.assessment_confidence <= 0.95
    assert score.model_status == "available"
    # Project B has no assets at all: honest empty coverage.
    other = next(s for s in result.project_scores if s.project_id == PROJECT_B)
    assert other.total_asset_count == 0
    assert other.visual_coverage is None


def test_artifacts_have_no_absolute_paths(shared) -> None:
    dataset, _ = shared
    for name in ("assets.jsonl", "findings.jsonl", "asset_contexts.jsonl", "report.md"):
        text = (dataset.output_dir / name).read_text(encoding="utf-8")
        assert "/Users/" not in text and "/home/" not in text


def test_review_template_written_and_merge_preserves_labels(tmp_path: Path) -> None:
    dataset, _result = run_pipeline(tmp_path)
    template = dataset.annotations_root / "p5_review_template.jsonl"
    rows = [json.loads(line) for line in template.read_text().splitlines()]
    assert rows and all("asset_id" in row and "predicted_class" in row for row in rows)
    # Expert fills one row; a re-run must keep the human decision.
    rows[0]["reviewed_class"] = "map"
    rows[0]["useful_for_p5"] = True
    rows[0]["reviewer_note"] = "проверено"
    with template.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    rerun = run_p5(
        P5Options(
            dataset_dir=dataset.dataset_dir,
            output_dir=dataset.output_dir,
            annotations_root=dataset.annotations_root,
            p3_dir=dataset.p3_dir,
            p4_dir=dataset.p4_dir,
            backend=stub_backend(),
            ocr_engine=stub_ocr(),
        )
    )
    assert rerun.review_template_preserved_decisions == 1
    merged = [json.loads(line) for line in template.read_text().splitlines()]
    kept = next(row for row in merged if row["asset_id"] == rows[0]["asset_id"])
    assert kept["reviewed_class"] == "map"
    assert kept["reviewer_note"] == "проверено"
    # Labels now exist: metrics must expose the evaluation honestly.
    assert rerun.metrics["expert_evaluation"]["status"] == "labels_available"
    assert rerun.metrics["expert_evaluation"]["labeled_rows"] == 1


# --- validation ---------------------------------------------------------------


def test_validate_clean_run(shared) -> None:
    dataset, _ = shared
    validation = validate_p5_outputs(dataset.dataset_dir, dataset.output_dir)
    assert validation.ok, validation.errors
    assert validation.counts["assets"] == 18


@pytest.mark.parametrize(
    ("filename", "mutate", "expected"),
    [
        (
            "classifications.jsonl",
            lambda row: {
                **row,
                "predicted_class": "map" if row["predicted_class"] != "map" else "chart",
            },
            "does not replay",
        ),
        (
            "project_scores.jsonl",
            lambda row: {
                **row,
                "visual_evidence_review_priority_score": min(
                    100, row["visual_evidence_review_priority_score"] + 10
                ),
            },
            "does not recompute",
        ),
        (
            "assets.jsonl",
            lambda row: {**row, "file_sha256": "b" * 64},
            "does not recompute",
        ),
        (
            "findings.jsonl",
            lambda row: {**row, "severity": "high", "priority_score": 25},
            "not permitted",
        ),
    ],
)
def test_validator_rejects_tampering(tmp_path: Path, filename: str, mutate, expected: str) -> None:
    dataset, _ = run_pipeline(tmp_path)
    path = dataset.output_dir / filename
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows, f"{filename} must not be empty for the tamper test"
    rows[0] = mutate(rows[0])
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    validation = validate_p5_outputs(dataset.dataset_dir, dataset.output_dir)
    assert not validation.ok
    assert any(expected in error for error in validation.errors), validation.errors


def test_validator_rejects_swapped_representative(tmp_path: Path) -> None:
    dataset, _result = run_pipeline(tmp_path)
    path = dataset.output_dir / "duplicate_clusters.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    target = next(row for row in rows if row["member_count"] >= 3)
    other_member = next(
        m for m in target["member_asset_ids"] if m != target["representative_asset_id"]
    )
    target["representative_asset_id"] = other_member
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    validation = validate_p5_outputs(dataset.dataset_dir, dataset.output_dir)
    assert not validation.ok
