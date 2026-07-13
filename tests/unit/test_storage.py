from pathlib import Path

import pytest
from pydantic import BaseModel

from dalel.ingestion import storage
from dalel.ingestion.storage import (
    compute_cache_key,
    is_cached,
    write_document_output,
)


class _Stub(BaseModel):
    value: str = "x"


def _write(out_dir: Path, marker: str = "x") -> None:
    write_document_output(
        out_dir,
        document_record=_Stub(value=marker),
        pages=[_Stub()],
        sections=[],
        tables=[],
        images=[],
        image_blobs={"images/img_0001.png": b"png-bytes"},
        report=_Stub(value=marker),
    )


def test_write_creates_all_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "proj" / "doc"
    _write(out_dir)
    for name in [
        "document.json",
        "pages.jsonl",
        "sections.jsonl",
        "tables.jsonl",
        "images.jsonl",
        "ingestion_report.json",
    ]:
        assert (out_dir / name).is_file(), name
    assert (out_dir / "images" / "img_0001.png").read_bytes() == b"png-bytes"
    leftovers = [p for p in out_dir.parent.iterdir() if p.name.startswith(".tmp__")]
    assert not leftovers


def test_atomic_write_failure_leaves_no_output(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "proj" / "doc"

    original = storage._write_json

    def failing_write_json(path: Path, model: BaseModel) -> None:
        if path.name == "ingestion_report.json":
            raise OSError("synthetic disk failure")
        original(path, model)

    monkeypatch.setattr(storage, "_write_json", failing_write_json)
    with pytest.raises(OSError):
        _write(out_dir)
    assert not out_dir.exists()
    leftovers = list(out_dir.parent.iterdir()) if out_dir.parent.exists() else []
    assert not leftovers


def test_atomic_overwrite_failure_restores_previous(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "proj" / "doc"
    _write(out_dir, marker="original")

    original = storage._write_json

    def failing_write_json(path: Path, model: BaseModel) -> None:
        if path.name == "ingestion_report.json":
            raise OSError("synthetic disk failure")
        original(path, model)

    monkeypatch.setattr(storage, "_write_json", failing_write_json)
    with pytest.raises(OSError):
        _write(out_dir, marker="replacement")
    assert out_dir.is_file() is False and out_dir.is_dir()
    assert '"original"' in (out_dir / "document.json").read_text(encoding="utf-8")


def test_cache_key_changes_with_inputs() -> None:
    base = compute_cache_key("a" * 64, [("docling", "2.0")], "auto")
    assert base != compute_cache_key("b" * 64, [("docling", "2.0")], "auto")
    assert base != compute_cache_key("a" * 64, [("docling", "2.1")], "auto")
    assert base != compute_cache_key("a" * 64, [("docling", "2.0")], "never")
    assert base != compute_cache_key("a" * 64, [("docling", "2.0")], "auto", "999")
    assert base == compute_cache_key("a" * 64, [("docling", "2.0")], "auto")


def test_is_cached_requires_matching_key_and_status(tmp_path: Path) -> None:
    out_dir = tmp_path / "doc"
    _write(out_dir)  # creates all core files with a stub report
    report = out_dir / "ingestion_report.json"

    report.write_text('{"cache_key": "k1", "extraction_status": "success"}', encoding="utf-8")
    assert is_cached(out_dir, "k1")
    assert not is_cached(out_dir, "other")

    report.write_text('{"cache_key": "k1", "extraction_status": "failed"}', encoding="utf-8")
    assert not is_cached(out_dir, "k1")


def test_is_cached_requires_core_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "doc"
    _write(out_dir)
    (out_dir / "ingestion_report.json").write_text(
        '{"cache_key": "k1", "extraction_status": "success"}', encoding="utf-8"
    )
    assert is_cached(out_dir, "k1")
    (out_dir / "pages.jsonl").unlink()
    assert not is_cached(out_dir, "k1")


def test_stale_workdirs_swept_on_write(tmp_path: Path) -> None:
    out_dir = tmp_path / "proj" / "doc"
    out_dir.parent.mkdir(parents=True)
    stale_tmp = out_dir.parent / ".tmp__doc__12345678"
    stale_tmp.mkdir()
    stale_old = out_dir.parent / ".old__doc__87654321"
    stale_old.mkdir()

    _write(out_dir)
    assert not stale_tmp.exists()
    assert not stale_old.exists()
    assert (out_dir / "document.json").is_file()
