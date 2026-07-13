from dalel.ingestion.pdf_mode import analyze_pdf


def test_digital_pdf_detected(tmp_repo) -> None:
    analysis = analyze_pdf(tmp_repo.digital_pdf)
    assert analysis.mode == "digital"
    assert analysis.page_count == 2
    assert analysis.ocr_candidate_pages == []
    first = analysis.pages[0]
    assert first.width > 0 and first.height > 0
    assert first.has_usable_text
    assert "Fixture page 1" in first.embedded_text


def test_scanned_pdf_detected(tmp_repo) -> None:
    analysis = analyze_pdf(tmp_repo.scanned_pdf)
    assert analysis.mode == "scanned"
    assert analysis.ocr_candidate_pages == [1, 2]


def test_mixed_pdf_detected(tmp_path) -> None:
    import fitz

    from fixtures.builders import PAGE_TEXT

    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(72, 96, 523, 400), PAGE_TEXT, fontsize=11)
    doc.new_page(width=595, height=842)  # empty page, no text
    doc.save(str(path))
    doc.close()

    analysis = analyze_pdf(path)
    assert analysis.mode == "mixed"
    assert analysis.ocr_candidate_pages == [2]
