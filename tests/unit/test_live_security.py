"""Live-mode security, archive-correctness and non-Bayterek fixture regressions.

Complements tests/unit/test_live_analysis.py: cryptographic job isolation,
log hygiene, hostile-archive handling, RAR honesty, TTL expiry, and the
required end-to-end synthetic PDF package with embedded visual assets.
"""

from __future__ import annotations

import io
import json
import logging
import time
import warnings
import zipfile
from collections.abc import Iterator
from typing import Any

import fitz
import pytest
from PIL import Image, ImageDraw

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from dalel.api.app import create_app
from dalel.api.job_store import JobNotFoundError, SecureJobStore
from dalel.api.live import reset_live_jobs

BAYTEREK = "project_003_bayterek"
PDF_MIME = "application/pdf"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    reset_live_jobs()
    value = TestClient(create_app())
    yield value
    reset_live_jobs()


# --- deterministic binary fixtures (no Bayterek content) ----------------------


def _png_bytes(width: int, height: int, painter) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    painter(ImageDraw.Draw(image))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _header_png() -> bytes:
    def painter(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle([4, 16, 392, 44], outline="black", width=2)
        draw.text((14, 22), "FIXTURE REPEATED HEADER", fill="black")

    return _png_bytes(400, 60, painter)


def _map_png() -> bytes:
    def painter(draw: ImageDraw.ImageDraw) -> None:
        draw.polygon([(40, 300), (200, 50), (430, 110), (560, 330), (300, 430)], outline="black")
        draw.line([(0, 210), (640, 250)], fill="blue", width=5)
        draw.rectangle([260, 200, 330, 260], outline="red", width=3)

    return _png_bytes(640, 480, painter)


def _diagram_png() -> bytes:
    def painter(draw: ImageDraw.ImageDraw) -> None:
        for x in range(0, 640, 64):
            draw.line([(x, 0), (x, 480)], fill=(70, 90, 200), width=2)
        draw.ellipse([200, 150, 440, 330], outline="black", width=4)

    return _png_bytes(640, 480, painter)


def _pdf_bytes(pages: list[str], header: bytes | None, first_page_image: bytes | None) -> bytes:
    document = fitz.open()
    for index, text in enumerate(pages):
        page = document.new_page(width=595, height=842)
        if header is not None:
            page.insert_image(fitz.Rect(40, 20, 440, 80), stream=header)
        page.insert_textbox(fitz.Rect(40, 100, 555, 640), text, fontsize=11)
        if index == 0 and first_page_image is not None:
            page.insert_image(fitz.Rect(60, 500, 380, 740), stream=first_page_image)
    payload = document.tobytes()
    document.close()
    return payload


def _tiny_pdf(text: str) -> bytes:
    return _pdf_bytes([text], None, None)


def _request(sections: list[dict[str, Any]], name: str = "Синтетический проект") -> str:
    return json.dumps(
        {"mode": "live_analysis", "project_display_name": name, "sections": sections},
        ensure_ascii=False,
    )


def _poll(client: TestClient, created: dict[str, Any]) -> dict[str, Any]:
    headers = {"X-Dalel-Job-Token": str(created["access_token"])}
    current = created
    for _ in range(400):
        if current["status"] in {"completed", "failed", "cancelled", "expired"}:
            return current
        time.sleep(0.05)
        current = client.get(f"/api/live/jobs/{created['job_id']}", headers=headers).json()
    pytest.fail("live job did not reach a terminal state")


def _create(client: TestClient, files: list[tuple[str, tuple[str, bytes, str]]], sections) -> Any:
    return client.post("/api/live/jobs", data={"request": _request(sections)}, files=files)


# --- job isolation and credential security ------------------------------------


def test_two_jobs_are_cryptographically_isolated(client: TestClient) -> None:
    first = _create(
        client,
        [("files", ("первый-секретный-документ.pdf", _tiny_pdf("Первый пакет."), PDF_MIME))],
        [{"section_id": "project_documents", "upload_indices": [0]}],
    ).json()
    second = _create(
        client,
        [("files", ("второй-секретный-документ.pdf", _tiny_pdf("Второй пакет."), PDF_MIME))],
        [{"section_id": "project_documents", "upload_indices": [0]}],
    ).json()

    assert first["job_id"] != second["job_id"]
    for created in (first, second):
        suffix = created["job_id"].removeprefix("live_")
        assert len(suffix) >= 32  # 256-bit url-safe token, no counters
        assert len(created["access_token"]) >= 40
    assert first["access_token"] != second["access_token"]

    cross = client.get(
        f"/api/live/jobs/{second['job_id']}",
        headers={"X-Dalel-Job-Token": first["access_token"]},
    )
    assert cross.status_code == 404
    assert "второй-секретный-документ" not in cross.text
    events_cross = client.get(
        f"/api/live/jobs/{second['job_id']}/events",
        headers={"X-Dalel-Job-Token": first["access_token"]},
    )
    assert events_cross.status_code == 404

    own = client.get(
        f"/api/live/jobs/{first['job_id']}",
        headers={"X-Dalel-Job-Token": first["access_token"]},
    )
    assert own.status_code == 200
    assert "второй-секретный-документ" not in own.text

    _poll(client, first)
    _poll(client, second)


def test_wrong_token_indistinguishable_from_missing_job(client: TestClient) -> None:
    created = _create(
        client,
        [("files", ("скрытое-имя-файла.pdf", _tiny_pdf("Пакет."), PDF_MIME))],
        [{"section_id": "project_documents", "upload_indices": [0]}],
    ).json()
    job_path = f"/api/live/jobs/{created['job_id']}"

    no_token = client.get(job_path)
    wrong_token = client.get(job_path, headers={"X-Dalel-Job-Token": "A" * 43})
    absent_job = client.get("/api/live/jobs/live_" + "B" * 43)
    for response in (no_token, wrong_token, absent_job):
        assert response.status_code == 404
        assert response.json()["error"] == "live_job_not_found"
        assert "скрытое-имя-файла" not in response.text
    assert no_token.json() == wrong_token.json() == absent_job.json()

    assert client.delete(job_path).status_code == 404
    assert client.delete(job_path, headers={"X-Dalel-Job-Token": "A" * 43}).status_code == 404
    _poll(client, created)


def test_expired_jobs_are_swept_with_cleanup() -> None:
    clock = {"now": 1000.0}
    cleaned: list[str] = []
    store: SecureJobStore[str] = SecureJobStore(
        prefix="live",
        ttl_seconds=60,
        max_records=4,
        cleanup=cleaned.append,
        clock=lambda: clock["now"],
    )
    value, credentials = store.create(lambda job_id: f"workspace-{job_id}")
    assert store.get(credentials.job_id, credentials.access_token) == value

    clock["now"] += 61
    with pytest.raises(JobNotFoundError):
        store.get(credentials.job_id, credentials.access_token)
    assert cleaned == [value]
    assert store.count() == 0


def test_tokens_and_filenames_stay_out_of_logs(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    marker_name = "секретное-имя-заявителя-947.pdf"
    with caplog.at_level(logging.DEBUG):
        created = _create(
            client,
            [("files", (marker_name, _tiny_pdf("Пакет для проверки логов."), PDF_MIME))],
            [{"section_id": "project_documents", "upload_indices": [0]}],
        ).json()
        _poll(client, created)
        client.delete(
            f"/api/live/jobs/{created['job_id']}",
            headers={"X-Dalel-Job-Token": created["access_token"]},
        )
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert created["access_token"] not in logged
    assert marker_name not in logged
    assert "секретное-имя-заявителя" not in logged


# --- upload hardening ----------------------------------------------------------


def test_traversal_and_absolute_filenames_rejected(client: TestClient) -> None:
    sections = [{"section_id": "project_documents", "upload_indices": [0]}]
    for hostile in ("../../escape.pdf", "..\\..\\escape.pdf", "/etc/passwd.pdf"):
        response = _create(client, [("files", (hostile, _tiny_pdf("x"), PDF_MIME))], sections)
        assert response.status_code == 422
        assert response.json()["error"] == "unsafe_filename"


def test_unassigned_and_unknown_upload_indices_rejected(client: TestClient) -> None:
    payload = _tiny_pdf("Пакет.")
    unknown = _create(
        client,
        [("files", ("a.pdf", payload, PDF_MIME))],
        [{"section_id": "project_documents", "upload_indices": [0, 1]}],
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"] == "unknown_upload_index"

    unassigned = _create(
        client,
        [
            ("files", ("a.pdf", payload, PDF_MIME)),
            ("files", ("b.pdf", _tiny_pdf("Второй."), PDF_MIME)),
        ],
        [{"section_id": "project_documents", "upload_indices": [0]}],
    )
    assert unassigned.status_code == 422
    assert unassigned.json()["error"] == "unassigned_upload"


# --- archive correctness ---------------------------------------------------------


def _encrypted_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("protocol.pdf", b"%PDF-1.4 fake")
    data = bytearray(buffer.getvalue())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        at = 0
        while (at := bytes(data).find(signature, at)) != -1:
            data[at + flag_offset] |= 0x01
            at += 4
    return bytes(data)


def test_encrypted_zip_rejected(client: TestClient) -> None:
    response = _create(
        client,
        [("files", ("encrypted.zip", _encrypted_zip(), "application/zip"))],
        [{"section_id": "hearing_protocol", "upload_indices": [0]}],
    )
    assert response.status_code == 422
    assert response.json()["error"] == "archive_encrypted"


def test_zip_bomb_ratio_rejected(client: TestClient) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.pdf", b"\x00" * (30 * 1024 * 1024))
    response = _create(
        client,
        [("files", ("bomb.zip", buffer.getvalue(), "application/zip"))],
        [{"section_id": "hearing_protocol", "upload_indices": [0]}],
    )
    assert response.status_code == 413
    assert response.json()["error"] == "archive_compression_ratio_limit"


def test_rar_is_registered_unsupported_never_not_archive(client: TestClient) -> None:
    fake_rar = b"Rar!\x1a\x07\x01\x00" + b"\x00" * 128
    response = _create(
        client,
        [("files", ("протокол-слушаний.rar", fake_rar, "application/vnd.rar"))],
        [{"section_id": "hearing_protocol", "upload_indices": [0]}],
    )
    assert response.status_code == 202
    created = response.json()
    assert created["files"][0]["archive_status"] == "extraction_unsupported"

    completed = _poll(client, created)
    assert completed["status"] == "completed"
    final_status = completed["files"][0]["archive_status"]
    assert final_status == "extraction_unsupported"
    file_id = completed["files"][0]["file_id"]
    result = completed["result"]
    assert result["archive_updates"][file_id] == {"archive_status": "extraction_unsupported"}
    assert file_id in result["inventory"]["unsupported_materials"]
    inventory_row = next(
        item for item in result["inventory"]["files"] if item["file_id"] == file_id
    )
    assert inventory_row["archive_status"] == "extraction_unsupported"


# --- required non-Bayterek end-to-end fixture -----------------------------------


def test_pdf_package_with_visual_assets_end_to_end(client: TestClient) -> None:
    header = _header_png()
    map_image = _map_png()
    main_pdf = _pdf_bytes(
        [
            "Пояснительная записка ОВОС\n\n1. Общие сведения\n"
            "Объем валовых выбросов составляет 12,5 тонн в год.\n"
            "Площадь санитарно-защитной зоны составляет 300 м.",
            "2. Оценка воздействия\nВыбросы диоксида азота составляют 4,2 тонн в год.",
        ],
        header,
        _diagram_png(),
    )
    ndv_pdf = _pdf_bytes(
        [
            "Проект нормативов допустимых выбросов (НДВ)\n"
            "Объем валовых выбросов составляет 12,5 тонн в год.",
            "Таблица источников выбросов\nВысота источника составляет 30 м.",
        ],
        header,
        None,
    )
    response = _create(
        client,
        [
            ("files", ("Пояснительная записка ОВОС.pdf", main_pdf, PDF_MIME)),
            ("files", ("НДВ расчет выбросов.pdf", ndv_pdf, PDF_MIME)),
            ("files", ("Карта площадки.png", map_image, "image/png")),
            ("files", ("Карта площадки (копия).png", map_image, "image/png")),
        ],
        [
            {"section_id": "project_documents", "upload_indices": [0, 1]},
            {"section_id": "visual_geographic_materials", "upload_indices": [2, 3]},
        ],
    )
    assert response.status_code == 202
    created = response.json()
    assert created["project_id"].startswith("live_project_")
    assert created["files"][3]["duplicate_of"] == created["files"][2]["file_id"]

    completed = _poll(client, created)
    assert completed["status"] == "completed"
    result = completed["result"]

    serialized = json.dumps(result, ensure_ascii=False)
    assert BAYTEREK not in serialized
    assert "bayterek" not in serialized.lower()
    assert "/Users/" not in serialized
    assert "data/raw" not in serialized

    assert result["preparation"]["document_count"] == 2
    assert result["preparation"]["prepared_document_count"] == 2
    assert result["preparation"]["page_count"] >= 4
    assert result["preparation"]["extracted_visual_asset_count"] >= 5
    assert result["preparation"]["extraction_failure_count"] == 0

    stages = {stage["stage_id"]: stage for stage in result["stages"]}
    assert stages["p0"]["status"] == "completed"
    assert stages["p0_5"]["status"] == "completed"
    assert stages["p1"]["status"] == "completed"
    assert stages["p3"]["status"] in {"completed", "insufficient_input"}

    assert result["pillars"]["P1"]["status"] == "completed"
    assert result["pillars"]["P2"]["status"] == "completed"
    assert result["pillars"]["P4"]["status"] == "completed"

    meta = result["meta"]
    assert meta is not None
    assert meta["project_id"] == result["project_id"]
    assert meta["calibrated_probability"] is None
    assert meta["shap_contributions"] is None
    assert 0 <= meta["review_priority_score"] <= 100
    prefixes = ("p1_", "p2_", "p3_", "p4_")
    assert all(
        str(item["feature_name"]).startswith(prefixes) for item in meta["feature_contributions"]
    )

    visuals = result["visual_inventory"]
    by_state = visuals["by_triage_state"]
    assert by_state.get("candidate_map", 0) >= 1  # useful image survives triage
    assert by_state.get("duplicate", 0) >= 2  # repeated header + duplicated map clustered
    assert by_state.get("repeated_text_header", 0) >= 1  # generic wide-header rule
    assert visuals["duplicate_clusters"] >= 2
    assert visuals["repeated_header_clusters"] >= 1
    assert visuals["review_template_rows"] >= 1
    assert visuals["visual_analysis_status"] == "not_available"
    map_assets = [item for item in visuals["assets"] if item["triage_state"] == "candidate_map"]
    assert all(item["eligible_for_future_p5"] for item in map_assets)
    headers = [item for item in visuals["assets"] if item["triage_state"] == "repeated_text_header"]
    assert all(not item["eligible_for_future_p5"] for item in headers)
    assert all(item["duplicate_cluster_id"] for item in headers)

    honest_missing = result["inventory"]["missing_sections"]
    assert "official_supporting_documents" in honest_missing


# --- visual triage details (§ deterministic, provenance-preserving) -------------


def _write_png(path, width: int, height: int, painter) -> None:
    path.write_bytes(_png_bytes(width, height, painter))


def test_repeated_wide_header_clusters_and_review_template(tmp_path) -> None:
    from dalel.api.visual_triage import build_visual_inventory

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    def header_painter(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle([2, 10, 316, 50], outline="black", width=2)
        draw.text((10, 20), "FL REPEATED APPLICANT LINE", fill="black")

    def logo_painter(draw: ImageDraw.ImageDraw) -> None:
        draw.ellipse([4, 4, 28, 28], outline="green", width=3)

    inventory = []
    for index in range(3):  # identical wide header repeated three times
        name = f"header_{index}.png"
        _write_png(input_dir / name, 320, 60, header_painter)
        inventory.append(
            {
                "file_id": f"HEADER_{index}",
                "section_id": "visual_geographic_materials",
                "display_filename": f"page-{index}.png",
                "media_type": "png",
                "internal_path": f"input/{name}",
            }
        )
    for index in range(2):  # tiny logo repeated across two "documents"
        name = f"logo_{index}.png"
        _write_png(input_dir / name, 32, 32, logo_painter)
        inventory.append(
            {
                "file_id": f"LOGO_{index}",
                "section_id": "visual_geographic_materials",
                "display_filename": f"logo-{index}.png",
                "media_type": "png",
                "internal_path": f"input/{name}",
            }
        )
    _write_png(input_dir / "qr.png", 128, 128, logo_painter)
    inventory.append(
        {
            "file_id": "QR",
            "section_id": "visual_geographic_materials",
            "display_filename": "qr-код объявления.png",
            "media_type": "png",
            "internal_path": "input/qr.png",
        }
    )
    _write_png(input_dir / "stamp.png", 128, 128, header_painter)
    inventory.append(
        {
            "file_id": "STAMP",
            "section_id": "visual_geographic_materials",
            "display_filename": "печать организации.png",
            "media_type": "png",
            "internal_path": "input/stamp.png",
        }
    )

    result = build_visual_inventory(
        tmp_path,
        job_id="live_triage_fixture",
        curated_dir=None,
        inventory=inventory,
    )
    records = {item["source_file_id"]: item for item in result["assets"]}

    header_states = [records[f"HEADER_{index}"]["triage_state"] for index in range(3)]
    assert sorted(header_states) == ["duplicate", "duplicate", "repeated_text_header"]
    header_clusters = {records[f"HEADER_{index}"]["duplicate_cluster_id"] for index in range(3)}
    assert len(header_clusters) == 1 and None not in header_clusters
    assert result["repeated_header_clusters"] == 1

    logo_states = sorted(records[f"LOGO_{index}"]["triage_state"] for index in range(2))
    assert logo_states == ["duplicate", "logo_or_branding"]

    assert records["QR"]["triage_state"] == "qr_code"
    assert records["QR"]["eligible_for_future_p5"] is False
    assert records["STAMP"]["triage_state"] == "stamp_or_signature"
    assert records["STAMP"]["eligible_for_future_p5"] is False

    # No excluded asset was deleted — everything stays in the inventory.
    assert result["assets_total"] == 7

    template = tmp_path / "visual" / "review_template.jsonl"
    assert template.is_file()
    rows = [json.loads(line) for line in template.read_text(encoding="utf-8").splitlines()]
    assert rows and result["review_template_rows"] == len(rows)
    assert {
        "asset_id",
        "predicted_category",
        "reviewed_category",
        "is_useful_for_p5",
        "duplicate_cluster_id",
        "reviewer_note",
    } <= set(rows[0])
    assert all(row["reviewed_category"] is None for row in rows)
    predicted = {row["predicted_category"] for row in rows}
    assert "repeated_text_header" in predicted
