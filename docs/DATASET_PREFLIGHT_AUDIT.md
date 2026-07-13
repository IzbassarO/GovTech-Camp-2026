# Dataset Pre-flight Audit

Audit date: 2026-07-13  
Repository scope: `GovTech-Camp-2026/data`  
Target phase: Phase 0 — Dataset Foundation + Document Ingestion

## Executive summary

Dataset foundation is ready for Phase 0.

The audit covered every physical file below `data/`, all four source metadata files, the project manifest, the weak-label annotation, PDF/DOCX/RAR integrity, file signatures, MIME types, sizes, SHA-256 hashes, exact and text-based near-duplicate candidates, Git ignore behavior, and pre-review/post-review leakage boundaries.

Key result:

- 4 projects are represented by exactly 4 JSONL project records.
- 24 document records are present: 19 pre-review model inputs, 4 post-review label sources, and 1 auxiliary archive.
- All manifest paths exist and all manifest hashes match the current files.
- No exact duplicate exists among the physical repository files.
- The Bayterek RAR is valid and its two extracted PDF members match byte-for-byte.
- Label sources are excluded from model features.
- The validator completes with 0 errors and 1 non-blocking warning.
- No PDF, DOCX, RAR, or other binary source document was edited, deleted, renamed, or moved during this audit.

The single warning is the pre-existing `data/raw/.DS_Store`, which is a non-dataset OS artifact and is ignored by Git.

## Current dataset structure

```text
data/
├── annotations/
│   └── project_002_azm/
│       └── weak_findings.json
├── manifests/
│   ├── file_inventory.jsonl
│   └── projects.jsonl
├── processed/
└── raw/
    ├── .DS_Store
    ├── project_001_bereke/
    ├── project_002_azm/
    ├── project_003_bayterek/
    │   └── hearing_protocol_extracted/
    │       └── Протокол публ.обс ФЛ Онгарова/
    │           ├── ФЛ Онгарова протокол публ каз.pdf
    │           └── ФЛ Онгарова протокол публ рус.pdf
    └── project_004_sintez_ural/
```

Physical dataset-file counts after the audit:

| Scope | Count | Notes |
|---|---:|---|
| Raw document binaries | 24 | 22 PDF, 1 DOCX, 1 RAR |
| Raw source metadata | 4 | One UTF-8 JSON per project |
| Raw non-dataset artifacts | 1 | `.DS_Store` |
| Annotation files | 1 | Weak labels for AZM |
| Manifest files | 2 | Projects and file inventory |
| Total physical files under `data/` | 32 | Includes `file_inventory.jsonl` itself |
| Inventory records | 31 | The inventory intentionally excludes its own unstable self-reference |

`file_inventory.jsonl` describes every other physical file under `data/`. It does not describe itself because a file cannot contain its own final SHA-256 and size without invalidating that same record. The validator enforces this explicit convention.

## Project-by-project findings

### project_001_bereke

Confirmed project scope: NDV, PUO, PEK, environmental action plan, and nontechnical summary for ИП КХ «Береке» for 2025–2034.

Official source card: [hearingId=23981](https://hearings.ndbecology.gov.kz/Public/PubHearings/PublicHearingDetail?hearingId=23981).

Findings:

- The official card lists the same five logical project documents and displayed sizes. Local filenames were normalized before this audit; portal filenames are retained in `original_filename`.
- Local title pages confirm a refined sunflower oil and wheat flour facility in the Abai Region, supporting `industry = food_production` rather than the former manifest value `agriculture`.
- All five local documents are pre-review model inputs.
- `action_plan.pdf` is a valid two-page PDF but has no embedded text; Phase 0 must route it through OCR.
- The local package does not contain the portal hearing protocol or photos. It must be described as the local pre-review subset, not as a complete copy of every portal attachment.

Confidence: high for project name, source URL, region, and industry based on the official card and local title pages. Remote files were not re-downloaded for byte-level comparison.

### project_002_azm

Confirmed project scope: NDV, PUO, PEK, action plan, nontechnical summary, and the public-hearing protocol for АО «Актюбинский завод металлоконструкций» for 2026–2035.

Official source card: [hearingId=29039](https://hearings.ndbecology.gov.kz/Public/PubHearings/PublicHearingDetail?hearingId=29039).

Findings:

- The official card lists the same five pre-review project documents and the same Russian protocol filename.
- The DOCX is a valid Office Open XML ZIP package; `unzip -t` reported no compressed-data errors.
- The protocol is a 25-page post-review weak-label source and is excluded from model features.
- Five weak findings were retained because the protocol explicitly acknowledges the underlying document issues: an incorrect contract number, an unrelated company reference in section 8.6, two `ТАЛРЫС` references, and an outdated summary table.
- All five findings remain `confidence = weak`, `expert_verified = false`, and `review_status = not_expert_verified`.
- Physical source pages 3, 4, and 5 were checked and exist.
- The protocol text contains a legacy `ShowDetails/27683` portal reference while the current official detail card is `hearingId=29039`. Exact filenames, timing, project title, and protocol content align with card 29039, so this is recorded as a non-blocking portal identifier discrepancy.

Confidence: high for project name, source URL, region, and industry; weak by design for all extracted annotations.

### project_003_bayterek

Confirmed project scope: explanatory note, ROOS, motivated refusal, and Russian/Kazakh hearing protocols for the construction of the Bayterek concrete-products production base.

Official source card: [hearingId=23206](https://hearings.ndbecology.gov.kz/Disscusion/DisPublic/PublicHearingDetail?hearingId=23206).

Findings:

- `source_metadata.json` was empty before the audit. It is now valid UTF-8 JSON using schema version 1.0.
- The official card lists the exact three PDF filenames and the RAR filename present locally.
- The project title and Kyzylorda region are independently confirmed by the local explanatory-note and ROOS title pages.
- `hearing_protocol_extracted/Протокол публ.обс ФЛ Онгарова` is a directory, not an extensionless file.
- The directory contains two actual PDF files with `.pdf` extensions. There is no extensionless Bayterek protocol file requiring a canonical rename recommendation.
- Both protocol PDFs are valid, unencrypted, two-page PDF 1.4 files with no embedded text; OCR will be required.
- The motivated refusal and both hearing protocols are post-review label sources and cannot enter pre-review embeddings, RAG, or model features.
- The RAR is an auxiliary archive and cannot enter model features.

Confidence: high for project name, URL, region, industry, format detection, and archive/member relationships.

### project_004_sintez_ural

Confirmed project scope: NDV, PEK, PUO, action plan, working-project explanatory note, nontechnical summary, and ROOS for the Sintez Ural mixed-products facility.

Official source card: [hearingId=29665](https://hearings.ndbecology.gov.kz/Public/PubHearings/PublicHearingDetail?hearingId=29665).

Findings:

- The placeholder source URL was replaced by the verified official card.
- The official card lists the same seven filenames and displayed sizes.
- Local title pages confirm Uralsk/West Kazakhstan and chemical-products manufacturing.
- All seven local files are pre-review model inputs; the portal protocol is not present locally.
- Text-based similarity identified expected content overlap between the nontechnical summary, NDV, and PUO. Their SHA-256 hashes differ and they serve distinct document roles, so they are not exact duplicates.
- The portal narrative refers to a 2025–2034 period in places, whereas the local NDV title/annotation refers to 2026–2035. The repository manifest does not infer a period field; Phase 0 should surface this as a content/version consistency candidate rather than silently normalize it.

Confidence: high for project name, source URL, region, and industry. The period discrepancy requires document-level review, not metadata invention.

## Metadata fixes applied

All four `source_metadata.json` files now share the same fields:

```text
schema_version
project_id
project_name
source_url
downloaded_at
region
industry
languages
label_quality
source_platform
notes
metadata_confidence
```

Changes:

| Project | Before | After | Reason | Confidence |
|---|---|---|---|---|
| Bereke | No schema version/name/platform/confidence; legacy `language` field | Unified schema, verified URL/region, `food_production`, `languages` | Official card and local titles | High |
| AZM | No schema version/name/platform/confidence; legacy `language` field | Unified schema, verified URL/region/industry, bilingual metadata | Official card, title page, protocol | High |
| Bayterek | Empty file | Complete schema with verified source URL, Kyzylorda, `construction_materials`, RU/KK | Exact official filename match and local titles | High |
| Sintez Ural | Placeholder URL, null region, legacy `language` field | Verified URL, West Kazakhstan, unified schema | Exact official filename match and local titles | High |

No unknown URL or region was invented. All populated values have direct official-card or local-document support.

## Manifest fixes applied

Before: `projects.jsonl` contained one incomplete Bereke record, a placeholder URL, legacy field names, no document IDs, no hashes, and no records for three projects.

After:

- Exactly four independent JSON objects, one per line.
- Exactly one `source_metadata_path` per project.
- 24 unique document IDs and 24 unique local paths.
- SHA-256 for every document.
- Allowed document types and roles only.
- Explicit `file_format`, `label_timing`, `use_as_model_feature`, and notes.
- Portal filenames preserved as `original_filename` for locally normalized Bereke files.

Role distribution:

| Role | Count | Feature use |
|---|---:|---|
| `model_input` | 19 | `true`, all `pre_review` |
| `label_source` | 4 | `false`, all `post_review` |
| `auxiliary_archive` | 1 | `false`, `post_review` contents |
| `auxiliary` | 0 | Not used for manifest documents |

## Archive inspection

Archive: `data/raw/project_003_bayterek/Протокол публ.обс ФЛ Онгарова.rar`

Results:

- Signature: RAR v4, Win32 origin marker.
- MIME: `application/x-rar`.
- SHA-256: `5a4ea47ecc84f86c68f995c23465b3ce07c130b65fbbfcecc01050d6be6c7dce`.
- Archive listing succeeds and contains one directory plus two PDF members.
- A clean extraction to a temporary audit directory succeeded.
- Kazakh protocol member SHA-256: `a82240328d8d6ef14a1408d31e3b4f226ce55eaaad6eab2f0de89347276bb42b`.
- Russian protocol member SHA-256: `27d286aebec77dde8630fee2b561b92e66c8b7b7dda751c2675a5af255c71613`.
- Both hashes exactly equal the corresponding files already present under `hearing_protocol_extracted/`.
- No corruption or missing nested member was detected.

The archive remains unchanged and is classified as `auxiliary_archive`. The extracted files remain unchanged and are classified as `hearing_protocol` / `label_source`.

## Annotation audit

Before: `data/annotations/project_002_azm/weak_findings.json` was empty and invalid as JSON.

After:

- Valid UTF-8 JSON using schema 1.0.
- Correct `project_id` and `annotation_type = weak_labels`.
- One declared source document, which exists.
- Five findings grounded in explicitly acknowledged protocol statements.
- All source pages exist and were manually checked.
- No gold-label claim, invented page, or expert-verification claim was added.
- The annotation file remains outside `data/raw` and outside the project document manifest.
- It is never a model feature.

The five findings are useful weak supervision candidates only. An environmental expert must review them before any promotion to gold labels.

## Duplicate audit

### Exact duplicates

No two physical repository files have the same SHA-256 after metadata repair.

The two previously empty files had the same empty-file hash before repair, but that was not a document duplicate; both invalid JSON files were replaced with distinct valid content.

### Near-duplicate candidates

- Sintez Ural `нетехническое резюме.pdf` has substantial expected text overlap with its NDV and PUO. This is an intentional summary relationship, not a duplicate. All three hashes and roles differ.
- The Russian and Kazakh Bayterek protocols are parallel language versions of the same hearing form. They are not byte-identical and must remain separate label-source records.
- No normalized-text exact duplicate was found among text-bearing PDFs.

### Archive/extracted relationships

The two extracted Bayterek protocol PDFs are exact copies of their corresponding RAR members. This is a provenance relationship, not a duplicate to delete. The archive and extracted files remain in place.

## Leakage audit

Leakage controls now enforced:

- Hearing protocols: `label_source`, `post_review`, feature use disabled.
- Motivated refusal: `label_source`, `post_review`, feature use disabled.
- Bayterek RAR: `auxiliary_archive`, feature use disabled.
- Weak findings: stored only under `data/annotations`, feature use disabled.
- No label-source path appears as a pre-review model input.
- No post-review path has `use_as_model_feature = true`.
- Project grouping is explicit through `project_id` and must be the minimum split unit.
- Pages or chunks from one project must never be split across train and test.
- Filenames, company/person names, direct outcome phrases, and post-review text must be masked or excluded from future risk-model features as described in the blueprint.

Current leakage risk is controlled at manifest level. Residual implementation risk remains if a future parser ignores manifest roles, recursively embeds all of `data/raw`, or derives labels from filenames. The Phase 0 ingestion agent must treat the manifest as an allowlist, not scan raw files indiscriminately.

## Git safety audit

`.gitignore` now covers:

- `data/raw/` and `data/processed/`;
- preserved manifests and annotations;
- `.env`, `.env.*`, with `.env.example` allowed;
- Python, Jupyter, OS, IDE, cache, and log artifacts.

Checks:

- `git check-ignore -v data/raw/project_001_bereke/ndv.pdf` resolves to `data/raw/`.
- `git check-ignore -v data/processed/` resolves to `data/processed/`.
- Manifest and annotation paths are explicitly unignored.
- `git ls-files data/raw` returned no tracked raw files; no `git rm --cached` action is needed.
- No commit, push, destructive Git command, or index mutation was performed.

The repository began with the dataset, docs, and `.gitignore` untracked. That is not a dataset-foundation blocker, but the user should review and stage only intended non-raw artifacts.

## Remaining unknowns

- Portal licensing, redistribution terms, and long-term retention permissions were not established by file inspection. Confirm these before publishing raw files outside the ignored local workspace.
- Remote portal attachments were matched by official card, exact filenames where available, project identity, timing, and displayed sizes. Remote binaries were not re-downloaded, so remote-to-local byte equality was not asserted.
- Bereke local filenames were normalized before this audit; the time and mechanism of that rename are unknown. Portal original filenames are preserved in the manifest.
- The AZM protocol's embedded legacy portal identifier `27683` versus current detail card `29039` has not been explained by portal documentation.
- Weak findings have not been reviewed by an environmental expert.
- The portal contains additional media, photos, language variants, or protocols that are not present in every local project folder. The local manifest is authoritative only for the physical local dataset.
- The Sintez Ural 2025–2034 versus 2026–2035 period discrepancy requires a future content-level review.

## Blocking issues

None for Phase 0 Dataset Foundation + Document Ingestion.

## Non-blocking warnings

1. `data/raw/.DS_Store` is a non-dataset OS artifact. It remains unchanged because raw data was treated as immutable and is ignored by Git.
2. Bereke `action_plan.pdf` and both Bayterek protocol PDFs have no embedded text and require OCR.
3. Bayterek Russian/Kazakh protocol PDFs duplicate archive-member bytes by design; ingestion must avoid double-processing the RAR and extracted copies.
4. Sintez Ural summary overlap is expected but should be tagged to prevent over-counting repeated evidence.
5. Licensing/terms require manual confirmation before redistribution.

## Final readiness decision

**READY FOR PHASE 0**

Readiness criteria satisfied:

- Original binary source documents preserved unchanged.
- Four valid, unified source metadata files.
- Four valid project JSONL records.
- All document paths and SHA-256 values validated.
- Valid weak-label schema with no gold-label overclaim.
- Model inputs and label sources separated.
- Post-review sources excluded from model features.
- Archive provenance verified.
- Git ignore safety confirmed.
- Validation script exits successfully with zero errors.

Validator result:

```text
WARNING: data/raw/.DS_Store is a non-dataset OS artifact; it remains ignored by Git
Projects validated: 4
Documents validated: 24
Errors: 0
Warnings: 1
Dataset foundation status: READY
```

## Recommended next action

Start Phase 0 ingestion by reading `data/manifests/projects.jsonl` as the authoritative allowlist. Process only records with `role = model_input`, `use_as_model_feature = true`, and `label_timing = pre_review`. Route textless PDFs to OCR, preserve page-level provenance, and use `project_id` as the immutable grouping key for all splits.

Do not recursively ingest all of `data/raw`, and do not include protocols, the motivated refusal, the RAR, or `weak_findings.json` in pre-review embeddings or RAG.
