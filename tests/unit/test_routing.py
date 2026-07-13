from dalel.ingestion.routing import ParserRoute, route_for, select_documents
from dalel.ingestion.validation import load_manifest


def test_role_filtering_default(tmp_repo) -> None:
    projects = load_manifest(tmp_repo.manifest_path)
    selection = select_documents(projects)
    selected_ids = {s.document.document_id for s in selection.selected}
    assert selected_ids == {
        "project_t1__ndv__001",
        "project_t1__action_plan__001",
        "project_t1__nontechnical_summary__001",
    }


def test_label_sources_excluded_by_default(tmp_repo) -> None:
    projects = load_manifest(tmp_repo.manifest_path)
    selection = select_documents(projects)
    skipped = {s.document.document_id: s.reason for s in selection.skipped}
    assert skipped["project_t1__hearing_protocol__001"] == "excluded_by_leakage_boundary"


def test_label_sources_included_with_flag(tmp_repo) -> None:
    projects = load_manifest(tmp_repo.manifest_path)
    selection = select_documents(projects, include_label_sources=True)
    selected_ids = {s.document.document_id for s in selection.selected}
    assert "project_t1__hearing_protocol__001" in selected_ids


def test_archive_always_skipped(tmp_repo) -> None:
    projects = load_manifest(tmp_repo.manifest_path)
    for include in (False, True):
        selection = select_documents(projects, include_label_sources=include)
        skipped = {s.document.document_id: s.reason for s in selection.skipped}
        assert skipped["project_t1__archive__001"] == "auxiliary_archive_never_ingested"
        assert "project_t1__archive__001" not in {
            s.document.document_id for s in selection.selected
        }


def test_document_id_filter(tmp_repo) -> None:
    projects = load_manifest(tmp_repo.manifest_path)
    selection = select_documents(projects, document_id="project_t1__ndv__001")
    assert len(selection.selected) == 1
    assert selection.selected[0].document.document_id == "project_t1__ndv__001"
    assert not selection.skipped


def test_route_for_formats(tmp_repo) -> None:
    projects = load_manifest(tmp_repo.manifest_path)
    documents = {d.document_id: d for p in projects for d in p.documents}
    assert route_for(documents["project_t1__ndv__001"]) is ParserRoute.PDF
    assert route_for(documents["project_t1__nontechnical_summary__001"]) is ParserRoute.DOCX
    assert route_for(documents["project_t1__archive__001"]) is ParserRoute.SKIP_ARCHIVE


def test_unsupported_format_skipped(tmp_repo) -> None:
    projects = load_manifest(tmp_repo.manifest_path)
    ndv = projects[0].documents[0]
    ndv_unsupported = ndv.model_copy(update={"file_format": "bin"})
    projects[0].documents[0] = ndv_unsupported
    selection = select_documents(projects)
    skipped = {s.document.document_id: s.reason for s in selection.skipped}
    assert skipped[ndv_unsupported.document_id] == "unsupported_file_format"
