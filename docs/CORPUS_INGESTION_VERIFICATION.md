# Independent Corpus Ingestion Verification

Verification date: 2026-07-13  
Repository: `GovTech-Camp-2026`  
Scope: Phase 0 processed corpus only  
Verifier: Codex, independent read-only review

## Executive verdict

**VERIFICATION FAILED — NOT READY FOR DATASET V1**

The headline filesystem counts are real: 19 model inputs, 4 label sources, 23
reports, 1,075 page records, 686 table records, 481 image records/files, and 98
OCR pages exist. Hash integrity, manifest coverage, provenance, parser metadata,
leakage isolation, image files, and all code quality gates passed.

The corpus nevertheless fails verification because 54 of the 686 records in
`tables.jsonl` are empty extraction artifacts with `num_rows=0`, `num_cols=0`,
`cells=[]`, no caption, and no warning. Three belong to Sintez Ural NDV and 51
to Sintez Ural ROOS. Therefore the independently usable non-empty table count is
632, not 686. The audit's statement that a complete table check found no
problems is false.

No pipeline or output was repaired during this verification. The cache ingest
test was not run because the task explicitly requires separate confirmation for
any ingestion command; that confirmation had not been received when this report
was written. This does not change the negative verdict because the empty table
records are already blocking.

## Files and commands inspected

Primary sources read:

- `docs/DALEL_Eco_Technical_Blueprint_RU.md`
- `docs/DATASET_PREFLIGHT_AUDIT.md`
- `docs/CORPUS_INGESTION_AUDIT.md`
- `README.md`
- `NEXT_STEPS.md`
- `data/manifests/projects.jsonl`
- `data/manifests/file_inventory.jsonl`
- `notebooks/01_ingestion_audit.ipynb`
- `notebooks/01_ingestion_audit_executed.ipynb`
- `scripts/validate_dataset_foundation.py`
- every file below `data/processed/model_inputs/` and
  `data/processed/label_sources/`

Read-only verification commands included:

```text
python3 scripts/verify_corpus_ingestion.py
python3 scripts/validate_dataset_foundation.py
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
git status --short
git diff --stat
git diff --cached --name-only
git ls-files data/raw data/processed
git check-ignore -v <one raw file> <one processed file>
```

Raw PDF partial-page explanations were independently checked with PyMuPDF
1.27.2.3 using `get_text()`, `get_images()`, and `get_drawings()`. The DOCX ZIP
contents and `word/document.xml` were also inspected directly. No source file was
written.

## Expected vs actual counts

| Artifact/metric | Expected | Recomputed | Result |
|---|---:|---:|---|
| Model-input document directories | 19 | 19 | Pass |
| Label-source document directories | 4 | 4 | Pass |
| Auxiliary archive parsed outputs | 0 | 0 | Pass |
| Auxiliary archive routing skips | 1 | 1 | Pass |
| `document.json` | 23 | 23 | Pass |
| `pages.jsonl` | 23 | 23 | Pass |
| `sections.jsonl` | 23 | 23 | Pass |
| `tables.jsonl` | 23 | 23 | Pass |
| `images.jsonl` | 23 | 23 | Pass |
| `ingestion_report.json` | 23 | 23 | Pass |
| Page records | 1,075 | 1,075 | Pass |
| Table records | 686 | 686 | Count matches, quality fails |
| Non-empty usable table records | Not reported | **632** | Blocking discrepancy |
| Empty table records without warning | 0 | **54** | **Fail** |
| Image records | 481 | 481 | Pass |
| Physical image files | 481 | 481 | Pass |
| OCR pages | 98 | 98 | Pass |
| Failed document outputs | 0 | 0 | Pass |

Five zero-byte JSONL files were found. Each is an honest zero-record collection
whose corresponding report count is zero, so these are not corrupt artifacts:

- Bereke nontechnical summary: `images.jsonl`;
- AZM DOCX nontechnical summary: `tables.jsonl`;
- Sintez Ural nontechnical summary: `images.jsonl`;
- Bayterek Kazakh hearing protocol: `tables.jsonl`;
- Bayterek motivated refusal: `tables.jsonl`.

No invalid JSON/JSONL, missing mandatory artifact, orphan document directory,
duplicate document directory, unexpected output file, `.tmp__`, `.old__`, or
partial atomic-write residue was found.

## Manifest coverage

All 24 manifest documents were reconciled against processed storage:

- 19 records with `role=model_input`, `use_as_model_feature=true`, and
  `label_timing=pre_review` exist only under `model_inputs`;
- 4 records with `role=label_source`, `use_as_model_feature=false`, and
  `label_timing=post_review` exist only under `label_sources`;
- the one `auxiliary_archive` has no parsed document directory;
- no processed output is absent from the manifest;
- no manifest-selected model input or label source is missing.

Each model-input `project.json` contains the complete project manifest set.
Post-review entries appear only as `status=skipped` routing metadata without
`output_dir`, parser metadata, page content, tables, or images. The archive is
recorded as `auxiliary_archive_never_ingested`.

## Per-project verification

### Model inputs

| Project | Documents | Status | Pages | Table records | Non-empty tables | Images | OCR pages |
|---|---:|---|---:|---:|---:|---:|---:|
| `project_001_bereke` | 5 | 5 success | 238 | 138 | 138 | 157 | 24 |
| `project_002_azm` | 5 | 4 success, 1 partial | 228 | 164 | 164 | 77 | 0 |
| `project_003_bayterek` | 2 | 1 success, 1 partial | 156 | 75 | 75 | 113 | 3 |
| `project_004_sintez_ural` | 7 | 5 success, 2 partial | 422 | 300 | **246** | 113 | 55 |
| **Total** | **19** | **15 success, 4 partial** | **1,044** | **677** | **623** | **460** | **82** |

### Label sources

| Project | Documents | Status | Pages | Table records | Non-empty tables | Images | OCR pages |
|---|---:|---|---:|---:|---:|---:|---:|
| `project_002_azm` | 1 | 1 partial | 25 | 8 | 8 | 17 | 12 |
| `project_003_bayterek` | 3 | 3 success | 6 | 1 | 1 | 4 | 4 |
| **Total** | **4** | **3 success, 1 partial** | **31** | **9** | **9** | **21** | **16** |

## Status and partial analysis

Persisted document statuses are 18 `success`, 5 `partial`, 0 `failed`, 0
`skipped`, and 0 `skipped_cached`. The auxiliary archive is a manifest-routing
skip rather than a document output.

All five partial documents have an explicit document warning, matching page
records with `page_has_no_text_after_ocr_policy`. EasyOCR actually ran in all
five cases. Independent raw-PDF inspection supports the explanations in the
corpus audit:

| Document | Partial pages | Processed chars | Independent raw-page evidence | Result |
|---|---|---|---|---|
| AZM NDV | 26, 136 | 4, 3 | Landscape 842×596; raw text is only page markers; 0 images and 2 vector drawings per page | Explanation confirmed |
| Bayterek ROOS | 20–23 | 2 each | Landscape pages; one image plus 91 vector drawings; raw text is only the page number | Explanation confirmed |
| Sintez Ural NDV | 67, 69, 131 | 23, 30, 21 | One raster image and four drawings per page; raw text is company/footer text of about 20 characters | Explanation confirmed |
| Sintez Ural PUO | 34 | 13 | Raw page has 13 characters, no images, no drawings | Explanation confirmed |
| AZM hearing protocol | 7, 8, 14, 15, 24, 25 | 13, 0, 17, 26, 4, 20 | Raster-only or almost raster-only annex pages, with 1–2 images and no vector drawings | Explanation confirmed |

There is no unexplained partial status. However, the audit's limitation saying
that 16 **model-input** pages lack usable text is inaccurate. Recomputed OCR
policy coverage is:

- model inputs: 92 candidate/no-embedded-text pages, 82 accepted OCR pages, 10
  candidates below the 32-character threshold;
- label sources: 22 candidates, 16 accepted OCR pages, 6 candidates below the
  threshold;
- whole corpus: 114 candidates, 98 accepted OCR pages, 16 short/failed
  candidates.

Thus 16 is the corpus-wide failed-candidate count, not the model-input count.

## Leakage isolation

No violation was found:

- no `hearing_protocol`, `motivated_refusal`, or archive output exists in
  `model_inputs`;
- no model input exists in `label_sources`;
- all post-review outputs are physically isolated;
- no `weak_findings` file, annotation path, or weak-label annotation structure
  was found below `data/processed`;
- `project.json` contains no post-review parsed content;
- no extra output absent from the manifest exists.

## Hash integrity

For all 23 parsed documents:

```text
physical raw SHA-256
  == manifest sha256
  == document.source_sha256
  == report.raw_hash_before
  == report.raw_hash_after
```

`hash_unchanged` is `true` in all 23 reports. Every `source_path` exists. No hash
violation was found.

## Provenance verification

All 4,197 provenance-bearing records were checked, not sampled:

- 1,075 pages;
- 1,955 sections;
- 686 tables;
- 481 images.

Every checked record agrees with the manifest/document for `project_id`,
`document_id`, `document_type`, `role`, `source_path`, `source_sha256`, parser
name/version, extraction method, OCR flag, and available page number. PDF page
numbers are positive and present. Honest null page numbers are retained for the
DOCX flow representation. No provenance violation was found.

## OCR verification

| Metric | Recomputed |
|---|---:|
| Documents where `engine_ran=true` | 11 |
| Model-input OCR pages | 82 |
| Label-source OCR pages | 16 |
| Total OCR pages | 98 |
| Candidate pages without embedded text | 114 |
| Candidate pages below acceptance threshold | 16 |

All executed OCR metadata names EasyOCR 1.7.2, `engine_available=true`, and
ru+en. When `engine_ran=false`, no OCR engine/version or OCR page is claimed.
Each of the 98 `ocr_pages` exists and matches a page record with
`ocr_applied=true` and `extraction_method=docling_ocr`.

The corpus audit reports 10 document warnings, including four Kazakh-language
warnings. The actual count is 11: five missing-text warnings, five
`ocr_language_unsupported: kk` warnings, and one DOCX pseudo-page warning. The
five language-warning documents are AZM NDV, Bayterek ROOS, AZM hearing
protocol, Bayterek Kazakh protocol, and Bayterek Russian protocol. The warning
is derived from coarse document/project language metadata, so it also appears
on the Russian protocol; it is not page-level language detection.

Kazakh label-source OCR is not treated as high-quality recognition. Manual
inspection of the required label-source table samples also found visibly noisy
OCR in the Russian Bayterek protocol table, so the limitation is broader than
the audit's Kazakh-only wording.

## Table verification

All 686 table records were checked for unique ID, project/document provenance,
page number, row/column dimensions, rectangular cells, bbox/null handling,
extraction method, and non-empty content or an explicit warning.

All table IDs are unique and all tables have page provenance and bbox. The
blocking failures are exactly:

| Document | Exact IDs | Pages | Count | Invalid fields |
|---|---|---|---:|---|
| `project_004_sintez_ural__ndv__001` | `tab_0045`, `tab_0055`, `tab_0079` | 71, 77, 87 | 3 | 0×0, empty cells/caption/warnings |
| `project_004_sintez_ural__roos__001` | every ID from `tab_0023` through `tab_0073` | 39–57, 59, 60 | 51 | 0×0, empty cells/caption/warnings |

This is the complete violation set. The data-level cause is visible in the
current code: `docling_parser._build_tables()` appends every Docling table item
even when the grid, dimensions, and caption are empty; the schema allows zero
defaults; the pipeline then serializes the record without adding an empty-grid
warning. No exception is raised, so reports count these as tables.

Required content samples were also inspected:

| Scope/project | Table | Shape | Content result |
|---|---|---:|---|
| Bereke | NDV `tab_0003` | 25×2 | Non-empty, coherent table of contents |
| Bereke | PEK `tab_0013` | 33×6 | Non-empty monitoring/control table |
| Bereke | PUO `tab_0001` | 23×2 | Non-empty, coherent table of contents |
| AZM | NDV `tab_0127` | 39×17 | Non-empty pollutant data; repeated merged headers but usable |
| AZM | PEK `tab_0007` | 22×5 | Non-empty equipment/source table |
| AZM | PUO `tab_0005` | 9×3 | Non-empty environmental-control table |
| Bayterek | Explanatory note `tab_0001` | 3×4 | Non-empty volume/designation table |
| Bayterek | ROOS `tab_0001` | 29×3 | Non-empty table of contents |
| Sintez Ural | NDV `tab_0042` | 7×10 | Non-empty numeric pollutant table |
| Sintez Ural | PEK `tab_0006` | 17×6 | Non-empty source-monitoring table |
| Sintez Ural | Working note `tab_0005` | 39×3 | Non-empty project-volume table |
| Label source | AZM protocol `tab_0007` | 8×18 | Non-empty but OCR-noisy |
| Label source | Bayterek RU protocol `tab_0001` | 5×13 | Non-empty but visibly OCR-corrupted |

Proposed correction, not applied: reject or explicitly warn on tables with no
grid/dimensions/content; mark affected documents partial when a detected table
cannot be extracted; optionally run a table fallback; add a regression test for
an empty Docling table item; then re-ingest only the two affected Sintez Ural
documents with explicit approval and rerun this verifier.

## Image verification

All 481 image records have one corresponding physical PNG file, and every
physical PNG is referenced exactly once. Counts and safety checks:

- duplicate logical image IDs: 0;
- missing files: 0;
- unreferenced files: 0;
- zero-byte files: 0;
- path traversal/unsafe paths: 0;
- non-PNG files: 0;
- smallest file: 267 bytes;
- largest file: 6,116,154 bytes;
- total physical bytes: 157,230,582.

There is one null bbox/page number: the DOCX image. Its record explicitly warns
that page provenance and bbox are unavailable, so this is honest rather than an
error.

## DOCX verification

`project_002_azm__nontechnical_summary__001` is correctly represented as DOCX,
not PDF:

- status: `success`;
- parser: Docling 2.112.0;
- `file_format=docx`, `document_mode=docx_flow`;
- one pseudo-page with full 3,194-character text;
- pseudo-page ordinal `page_number=1`, but provenance `page_number=null`;
- width, height, rotation, section page range, image page, and bbox are null
  with explicit warnings;
- 1 section, 0 tables, 1 image;
- source/report/manifest hashes match.

Direct DOCX inspection finds one media image and zero `<w:tbl>` elements. The
corpus audit's sentence saying that a DOCX table was extracted is therefore
factually wrong, but the zero table count is not itself an ingestion defect
because the source contains no Word table.

## Cache/idempotency test

Not executed. The governing request forbids ingestion without separate
confirmation. A separate request for permission to run normal, non-forced
ingestion of `project_002_azm__nontechnical_summary__001` was issued during the
verification. Until it is granted, the audit's idempotency claim is not
independently verified.

The planned check is limited to that one completed document and will compare
pre/post SHA-256 and nanosecond mtimes for all files in its document directory,
the raw source hash, CLI exit code, and `skipped_cached` result. It will not use
`--force` or run the corpus.

## Notebook verification

`notebooks/01_ingestion_audit_executed.ipynb` is valid JSON and has ten code
cells with sequential execution counts 1–10. It has no error outputs. Code-cell
sources are byte-for-byte equivalent to those in the source notebook.

The notebook:

- reads only `data/processed/model_inputs`;
- never reads `label_sources`;
- contains aggregation and display logic only, not production parsing;
- reports 19 documents, 1,044 pages, 677 table records, 460 images, and zero
  fallback uses, matching independent record counts.

Its table aggregation counts records and therefore does not expose the 54 empty
Sintez Ural table records. The outputs are internally consistent with executed
code, but the notebook has no execution-timing metadata, so filesystem review
cannot cryptographically prove that outputs were never edited manually. This
is a non-blocking provenance limitation of the notebook artifact.

## Audit claim reconciliation

| Claim | Reported | Recomputed | Result |
|---|---:|---:|---|
| Model inputs | 19 | 19 | Pass |
| Model inputs by project | 5 / 5 / 2 / 7 | 5 / 5 / 2 / 7 | Pass |
| Label sources | 4 | 4 | Pass |
| Archive | 1 skipped | No parsed output; routing skip present | Pass |
| Ingestion reports | 23 | 23 | Pass |
| Pages | 1,075 | 1,075 | Pass |
| Table records | 686 | 686 | Count only |
| Valid non-empty tables | Implied 686 | **632** | **Fail** |
| Images | 481 | 481 records and files | Pass |
| OCR pages | 98 | 98 | Pass |
| Parser | Docling 2.112.0 for 23 | Same | Pass |
| Fallback | 0 | 0 | Pass |
| Hash integrity | 23 unchanged | 23 unchanged | Pass |
| Statuses | 18 success, 5 partial, 0 failed | Same | Pass |
| Partial explanations | All explained | All five supported by raw/page evidence | Pass |
| Total document warnings | 10 | 11 | Fail |
| Kazakh-language warnings | 4 | 5 | Fail |
| DOCX table extracted | Yes | 0 tables; source has 0 Word tables | Fail claim, no extraction defect |
| Model-input pages without usable OCR text | 16 | 10 model + 6 label = 16 corpus | Fail |
| Leakage isolation | No violations | No violations | Pass |
| Idempotency | Full cache run claimed | Independent one-document test not authorized | Not verified |
| Notebook totals | 19 / 1,044 / 677 / 460 | Same record counts | Pass with table-quality caveat |
| “NO PROBLEMS FOUND” table verification | Claimed | 54 invalid empty table records | **Fail** |
| Quality gates | Passed | Passed independently | Pass |

## Quality gates

| Command | Independent result |
|---|---|
| `uv run ruff check .` | Pass — all checks passed |
| `uv run ruff format --check .` | Pass — 39 files formatted |
| `uv run mypy src` | Pass — no issues in 24 source files |
| `uv run pytest` | Pass — 68 passed, 3 deselected, 5 SWIG deprecation warnings |
| `python3 scripts/validate_dataset_foundation.py` | Exit 0 — READY, 0 errors, 2 `.DS_Store` warnings |
| `python3 scripts/verify_corpus_ingestion.py` | **Exit 1 — FAIL, 54 blocking table errors** |

Git hygiene checks:

- `data/raw/` and `data/processed/` are ignored by `.gitignore`;
- `git ls-files data/raw data/processed` returns no tracked files;
- no staged file exists (`git diff --cached --name-only` is empty);
- `git diff --stat` is empty because current additions are untracked;
- raw/processed generated artifacts are not staged;
- pre-existing untracked PDFs/DOCX, the corpus audit, and the executed notebook
  were not modified by this verifier.

## Blocking issues

1. **54 empty table records are counted as successful table extractions without
   any warning.** This violates the explicit table audit criterion and makes the
   686-table quality claim unsafe. It affects model-input evidence in Sintez
   Ural NDV and ROOS.
2. **The independent verifier exits 1.** A full-pass verifier is a stated
   readiness requirement; it cannot return 0 while these records remain.

The false warning/DOCX/page-count claims in the corpus audit must also be
corrected, but those documentation errors are secondary to the table blocker.

## Non-blocking limitations

- The one-document cache/idempotency check remains pending separate permission.
- Five zero-byte JSONL files are valid zero-record collections; consumers must
  continue treating empty JSONL as an empty list.
- Bayterek label-source table OCR is visibly noisy, including the Russian
  protocol; these are isolated from model features and must not be promoted to
  high-quality labels without review.
- EasyOCR does not support Kazakh; ru+en output for Kazakh material remains
  explicitly limited.
- DOCX has no physical page geometry; the pseudo-page/provenance-null convention
  is correct but downstream code must understand it.
- The executed notebook lacks cell execution timestamps; its sequential counts,
  matching source, and independently matching outputs are strong but not
  cryptographic execution provenance.
- `data/raw/.DS_Store` drift is a known non-dataset warning.

## Final decision

**VERIFICATION FAILED — NOT READY FOR DATASET V1**

Transition to Dataset v1 is not authorized. Phase 1, LLM/RAG, scoring, CML, and
frontend work were not started.

The safe next action is to review and fix empty-table handling, add a regression
test, and—only after explicit approval—re-ingest the two affected Sintez Ural
documents and rerun `scripts/verify_corpus_ingestion.py`. The verifier did not
apply that fix automatically.
