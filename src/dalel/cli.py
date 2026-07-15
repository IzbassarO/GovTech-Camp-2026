"""``dalel`` CLI: validate-manifest, inspect, ingest.

``validate-manifest`` and ``inspect`` are import-light and never touch
Docling. ``ingest`` imports the pipeline lazily and warns about the one-time
Docling/EasyOCR model download before the first conversion.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from dalel.config import OcrMode, derive_repo_root

app = typer.Typer(
    name="dalel",
    help="DALEL Eco Phase 0: local document ingestion.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

DEFAULT_MANIFEST = Path("data/manifests/projects.jsonl")

ManifestOption = Annotated[
    Path,
    typer.Option("--manifest", help="Path to the canonical projects.jsonl manifest."),
]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep third-party parser logging readable at default level.
    if not verbose:
        for noisy in ("docling", "docling_core", "urllib3", "filelock", "fontTools"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command("validate-manifest")
def validate_manifest_command(
    manifest: ManifestOption = DEFAULT_MANIFEST,
    check_hashes: Annotated[
        bool,
        typer.Option(
            "--check-hashes/--no-check-hashes",
            help="Verify SHA-256 of every manifest document against the file on disk.",
        ),
    ] = True,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Validate the manifest without loading any parser models."""
    _setup_logging(verbose)
    from dalel.ingestion.validation import validate_manifest

    repo_root = derive_repo_root(manifest)
    result = validate_manifest(manifest, repo_root, check_hashes=check_hashes)

    for error in result.errors:
        typer.secho(f"ERROR: {error}", fg=typer.colors.RED)
    for warning in result.warnings:
        typer.secho(f"WARNING: {warning}", fg=typer.colors.YELLOW)

    typer.echo(f"Projects: {len(result.projects)}")
    typer.echo(f"Documents: {result.document_count}")
    typer.echo(f"Errors: {len(result.errors)}")
    typer.echo(f"Warnings: {len(result.warnings)}")
    typer.echo(f"Manifest status: {'VALID' if result.ok else 'INVALID'}")
    raise typer.Exit(code=0 if result.ok else 1)


@app.command("inspect")
def inspect_command(
    manifest: ManifestOption = DEFAULT_MANIFEST,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Show projects, documents, roles, formats, OCR and skip candidates."""
    _setup_logging(verbose)
    from rich.console import Console
    from rich.table import Table

    from dalel.ingestion.routing import ParserRoute, route_for, select_documents
    from dalel.ingestion.validation import ManifestError, load_manifest

    repo_root = derive_repo_root(manifest)
    try:
        projects = load_manifest(manifest)
    except ManifestError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc
    console = Console()

    total_docs = 0
    for project in projects:
        table = Table(
            title=(
                f"{project.project_id} — region={project.region},"
                f" industry={project.industry}, languages={','.join(project.languages)}"
            ),
            show_lines=False,
        )
        table.add_column("document_id", overflow="fold")
        table.add_column("type")
        table.add_column("role")
        table.add_column("format")
        table.add_column("feature")
        table.add_column("timing")
        table.add_column("route/note")

        for document in project.documents:
            total_docs += 1
            route = route_for(document)
            if route is ParserRoute.SKIP_ARCHIVE:
                note = "SKIP: auxiliary archive (never unpacked)"
            elif route is ParserRoute.SKIP_UNSUPPORTED:
                note = f"SKIP: unsupported format {document.file_format!r}"
            elif document.is_default_ingestible:
                note = f"ingest via {route.value}"
                local_path = repo_root / document.local_path
                if not local_path.is_file():
                    note += " [MISSING FILE]"
            else:
                note = "label source: requires --include-label-sources"
            table.add_row(
                document.document_id,
                document.document_type,
                document.role,
                document.file_format,
                str(document.use_as_model_feature),
                str(document.label_timing),
                note,
            )
        console.print(table)

    selection = select_documents(projects)
    label_sources = sum(1 for p in projects for d in p.documents if d.role == "label_source")
    archives = sum(1 for p in projects for d in p.documents if d.role == "auxiliary_archive")
    console.print(f"Projects: {len(projects)}")
    console.print(f"Documents: {total_docs}")
    console.print(f"Model inputs (ingested by default): {len(selection.selected)}")
    console.print(f"Label sources (excluded by default): {label_sources}")
    console.print(f"Auxiliary archives (always skipped): {archives}")

    ocr_candidates = _probe_ocr_candidates(repo_root, projects)
    if ocr_candidates is not None:
        console.print(f"OCR candidates (no embedded text): {', '.join(ocr_candidates) or 'none'}")
    else:
        console.print("OCR candidates: run with PyMuPDF installed to probe embedded text")


def _probe_ocr_candidates(repo_root: Path, projects: list) -> list[str] | None:  # type: ignore[type-arg]
    """Best-effort embedded-text probe; import-light callers may lack PyMuPDF."""
    try:
        from dalel.ingestion.pdf_mode import analyze_pdf
    except ImportError:
        return None
    candidates: list[str] = []
    for project in projects:
        for document in project.documents:
            # Probe only default-ingestible model inputs: even in-memory text
            # extraction from label sources stays behind the explicit flag.
            if not document.is_default_ingestible:
                continue
            if document.file_format.lower() != "pdf":
                continue
            local_path = repo_root / document.local_path
            if not local_path.is_file():
                continue
            try:
                analysis = analyze_pdf(local_path)
            except Exception:
                continue
            if analysis.mode in {"scanned", "mixed"}:
                candidates.append(f"{document.document_id} ({analysis.mode})")
    return candidates


@app.command("ingest")
def ingest_command(
    manifest: ManifestOption = DEFAULT_MANIFEST,
    project_id: Annotated[
        str | None, typer.Option("--project-id", help="Ingest only this project.")
    ] = None,
    document_id: Annotated[
        str | None, typer.Option("--document-id", help="Ingest only this document.")
    ] = None,
    ocr: Annotated[
        OcrMode, typer.Option("--ocr", help="OCR policy: auto, always or never.")
    ] = OcrMode.AUTO,
    include_label_sources: Annotated[
        bool,
        typer.Option(
            "--include-label-sources",
            help=(
                "Also parse label-source documents (hearing protocols, motivated refusal)"
                " into the separate data/processed/label_sources tree. Never used as"
                " model features."
            ),
        ),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Reprocess even when the cache key matches.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Ingest manifest documents (model inputs by default) into data/processed."""
    _setup_logging(verbose)

    typer.secho(
        "NOTE: the first Docling conversion downloads layout/TableFormer models"
        " (~500 MB) to ~/.cache and EasyOCR weights (~100 MB) to ~/.EasyOCR."
        " Subsequent runs use the local cache.",
        fg=typer.colors.YELLOW,
    )

    from dalel.ingestion.pipeline import IngestOptions, ingest_documents
    from dalel.ingestion.reports import format_batch_summary
    from dalel.ingestion.validation import ManifestError

    repo_root = derive_repo_root(manifest)
    options = IngestOptions(
        manifest_path=manifest,
        repo_root=repo_root,
        project_id=project_id,
        document_id=document_id,
        ocr_mode=ocr,
        include_label_sources=include_label_sources,
        force=force,
    )
    try:
        batch = ingest_documents(options)
    except (ValueError, ManifestError) as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc

    typer.echo(format_batch_summary(batch))
    raise typer.Exit(code=0 if batch.ok else 1)


@app.command("curate")
def curate_command(
    input_root: Annotated[
        Path, typer.Option("--input", help="Processed corpus root (read-only).")
    ] = Path("data/processed"),
    output_dir: Annotated[
        Path, typer.Option("--output", help="Curated dataset output directory.")
    ] = Path("data/curated/v1"),
    manifest: ManifestOption = DEFAULT_MANIFEST,
    force: Annotated[
        bool, typer.Option("--force", help="Atomically replace an existing dataset.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Build Curated Dataset v1 from the processed corpus (Phase 0.5)."""
    _setup_logging(verbose)
    from dalel.curation.builder import (
        CuratedBuildError,
        CurateOptions,
        build_curated_dataset,
    )

    repo_root = derive_repo_root(manifest)
    options = CurateOptions(
        input_root=input_root,
        output_dir=output_dir,
        repo_root=repo_root,
        manifest_path=manifest,
        annotations_root=repo_root / "data" / "annotations",
        force=force,
    )
    try:
        result = build_curated_dataset(options)
    except CuratedBuildError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    for error in result.errors:
        typer.secho(f"ERROR: {error}", fg=typer.colors.RED)
    typer.echo(f"Build status: {result.status}")
    typer.echo(f"Counts: {result.counts}")
    if result.report_path is not None:
        typer.echo(f"Build report: {result.report_path}")
    raise typer.Exit(code=0 if result.status == "success" else 1)


@app.command("validate-curated")
def validate_curated_command(
    dataset: Annotated[Path, typer.Option("--dataset", help="Curated dataset directory.")] = Path(
        "data/curated/v1"
    ),
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Validate a built curated dataset (structure, counts, leakage, checksums)."""
    _setup_logging(verbose)
    from dalel.curation.validation import validate_curated_dataset

    repo_root = dataset.resolve().parents[2] if len(dataset.resolve().parents) >= 3 else Path.cwd()
    result = validate_curated_dataset(dataset, repo_root)
    for error in result.errors:
        typer.secho(f"ERROR: {error}", fg=typer.colors.RED)
    for warning in result.warnings:
        typer.secho(f"WARNING: {warning}", fg=typer.colors.YELLOW)
    typer.echo(f"Counts: {result.counts}")
    typer.echo(f"Errors: {len(result.errors)}")
    typer.echo(f"Curated dataset status: {'VALID' if result.ok else 'INVALID'}")
    raise typer.Exit(code=0 if result.ok else 1)


@app.command("run-p1")
def run_p1_command(
    dataset: Annotated[
        Path, typer.Option("--dataset", help="Curated dataset directory (read-only).")
    ] = Path("data/curated/v1"),
    output: Annotated[Path, typer.Option("--output", help="P1 results output directory.")] = Path(
        "data/results/p1/v1"
    ),
    project_id: Annotated[
        str | None, typer.Option("--project-id", help="Analyze only this project.")
    ] = None,
    document_id: Annotated[
        str | None, typer.Option("--document-id", help="Analyze only this document.")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the P1 Document Integrity deterministic baseline (no LLM)."""
    _setup_logging(verbose)
    from dalel.pillars.document_integrity.pipeline import P1Options, P1RunError, run_p1

    repo_root = dataset.resolve().parents[2] if len(dataset.resolve().parents) >= 3 else Path.cwd()
    options = P1Options(
        dataset_dir=dataset,
        output_dir=output,
        annotations_root=repo_root / "data" / "annotations",
        project_id=project_id,
        document_id=document_id,
    )
    try:
        result = run_p1(options)
    except P1RunError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"P1 complete: documents={result.metrics['documents_analyzed']}"
        f" findings={result.metrics['findings_total']}"
        f" by_severity={result.metrics['findings_by_severity']}"
    )
    if result.review_template_created:
        typer.echo(f"Review template created: {result.review_template_path}")
    else:
        typer.echo(
            f"Review template already exists (not overwritten): {result.review_template_path}"
        )
    typer.echo(f"Outputs: {output}")


_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3}


@app.command("run-p3")
def run_p3_command(
    dataset: Annotated[
        Path, typer.Option("--dataset", help="Curated dataset directory (read-only).")
    ] = Path("data/curated/v1"),
    output: Annotated[Path, typer.Option("--output", help="P3 results output directory.")] = Path(
        "data/results/p3/v1"
    ),
    project_id: Annotated[
        str | None, typer.Option("--project-id", help="Analyze only this project.")
    ] = None,
    document_id: Annotated[
        str | None, typer.Option("--document-id", help="Analyze only this document.")
    ] = None,
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            help="Exit nonzero when findings at or above this severity exist"
            " (info, low, medium or high).",
        ),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the P3 Quantitative Consistency deterministic baseline (no LLM)."""
    _setup_logging(verbose)
    import time

    from dalel.pillars.quantitative_consistency.pipeline import (
        P3Options,
        P3RunError,
        run_p3,
    )
    from dalel.pillars.quantitative_consistency.reports import summarize_for_cli

    if fail_on is not None and fail_on not in _SEVERITY_RANK:
        typer.secho(
            f"ERROR: --fail-on must be one of {', '.join(_SEVERITY_RANK)}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    repo_root = dataset.resolve().parents[2] if len(dataset.resolve().parents) >= 3 else Path.cwd()
    options = P3Options(
        dataset_dir=dataset,
        output_dir=output,
        annotations_root=repo_root / "data" / "annotations",
        project_id=project_id,
        document_id=document_id,
    )
    started = time.monotonic()
    try:
        result = run_p3(options)
    except P3RunError as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.echo(summarize_for_cli(result.metrics))
    typer.echo(f"Elapsed: {time.monotonic() - started:.1f}s")
    if result.review_template_created:
        typer.echo(f"Review template created: {result.review_template_path}")
    else:
        typer.echo(f"Review template updated (human decisions kept): {result.review_template_path}")
    typer.echo(f"Outputs: {output}")

    if fail_on is not None:
        threshold = _SEVERITY_RANK[fail_on]
        hits = sum(1 for f in result.findings if _SEVERITY_RANK.get(f.severity, -1) >= threshold)
        if hits:
            typer.secho(
                f"FAIL-ON: {hits} finding(s) at severity >= {fail_on}", fg=typer.colors.YELLOW
            )
            raise typer.Exit(code=1)


@app.command("validate-p3")
def validate_p3_command(
    dataset: Annotated[
        Path, typer.Option("--dataset", help="Curated dataset directory (read-only).")
    ] = Path("data/curated/v1"),
    output: Annotated[Path, typer.Option("--output", help="P3 results directory.")] = Path(
        "data/results/p3/v1"
    ),
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Validate P3 outputs: schemas, IDs, evidence, recomputed formulas."""
    _setup_logging(verbose)
    from dalel.pillars.quantitative_consistency.validation import validate_p3_outputs

    result = validate_p3_outputs(dataset, output)
    for error in result.errors:
        typer.secho(f"ERROR: {error}", fg=typer.colors.RED)
    for warning in result.warnings:
        typer.secho(f"WARNING: {warning}", fg=typer.colors.YELLOW)
    typer.echo(f"Counts: {result.counts}")
    typer.echo(f"Errors: {len(result.errors)}")
    typer.echo(f"P3 outputs status: {'VALID' if result.ok else 'INVALID'}")
    raise typer.Exit(code=0 if result.ok else 1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
