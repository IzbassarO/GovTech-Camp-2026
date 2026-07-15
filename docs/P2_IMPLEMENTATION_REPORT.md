# Phase 2 — P2 Regulatory Compliance: Implementation Report

Date: 2026-07-15. Base commit: `1c3ce00` (accepted P3). Status:
**demo-ready MVP, all gates pass, nothing committed or pushed.**

## Scope decisions

- **No authoritative regulatory corpus exists in this repository** (the
  technical blueprint references the Ecological Code only as an external
  URL). Per policy, the complete P2 engine was implemented and a
  SYNTHETIC demo corpus of 12 requirements ships as a packaged resource
  (`demo_only=true`, `is_authoritative=false`, `DEMO-REQ-NNN`, explicit
  warning in CLI/report/findings, severity hard-capped at low).
- Deterministic offline pipeline is the default and the only mode used
  by tests; the LLM layer is an optional, validated refinement.
- Not implemented by design (later phases): legal crawler, vector DB,
  transformer training, full legal ontology, temporal version
  resolution, agent orchestration, API/frontend, meta-risk scoring.

## What was built

16 files: 15 new modules/resources under
`src/dalel/pillars/regulatory_compliance/` (see the technical doc for the
layout) plus `tests/fixtures/p2_builders.py` and
`tests/unit/test_p2.py`. Modified: `src/dalel/cli.py` (run-p2,
validate-p2), `scripts/validate_dataset_foundation.py`
(p2_review_template.jsonl added to derived files — same policy as
P1/P3).

Key safety mechanics, each covered by tests:

- corpus loader rejects duplicate IDs, hash mismatches, unsupported
  versions, inverted dates, demo-claiming-authority;
- retrieval is deterministic with recorded boosts; weak matches are not
  forced; package-wide required-document checks use an explicit recorded
  backstop (absence of a document must not hide its own requirement);
- the NLI baseline prefers `insufficient_evidence` over unsupported
  conflicts, never judges quantitative limits, requires strong retrieval
  for any conflict and recognizes negation only inside the matched
  snippet;
- conservative RU/KK inflection tolerance in concept matching (long
  common prefixes; no short-token leaps) — added after manual review of
  the first production run showed «санитарно-защитной зоны» escaping the
  matcher;
- the LLM merge policy is confirm-or-downgrade only; hallucinated
  quotes, unknown evidence IDs, malformed JSON and provider failures all
  fall back with explicit flags; prompt-injection text inside evidence is
  demonstrably treated as data;
- `validate-p2` replays retrievals, assessments, findings, scores and
  the requirements snapshot from raw inputs; an 8-case tamper matrix plus
  a review-template tamper test all fail validation.

## Demo production run (synthetic corpus, accepted Dataset v1)

`uv run dalel run-p2` → 4 projects, 19 documents, 12 requirements,
23 queries, 105 retrieval records (12 of them explicit
required-document backstops), 39 assessments: 28 `supported_by_evidence`,
7 `insufficient_evidence`, 4 `potential_conflict`, 0 `not_applicable`
(the demo corpus has no failing industry condition on these projects;
the label is exercised by tests).
**11 findings: 4 low + 7 info, zero high/medium (demo cap).**

- 4 × `missing_required_document` (low) — all for project_003_bayterek,
  whose package genuinely contains only `roos` + `explanatory_note`;
- 3 × `insufficient_regulatory_evidence` (info) — e.g. the quantitative
  СЗЗ-limit requirement, correctly not judged by the baseline;
- 4 × `non_authoritative_demo_requirement` (info) — one per project.

Manual spot-check confirmed: bereke's СЗЗ section requirement is
supported by a real text snippet; the negation and conflict paths do not
fire spuriously on the real corpus.

## Quality gates (executed in order)

| # | Command | Result |
|---|---|---|
| 1 | `uv run pytest` | **456 passed, 3 deselected** (58 new P2 tests) |
| 2 | `uv run ruff check .` | All checks passed |
| 3 | `uv run ruff format --check .` | all files formatted |
| 4 | `uv run mypy src` | Success, 79 source files |
| 5 | `validate_dataset_foundation.py` | READY |
| 6 | `dalel validate-curated` | VALID |
| 7 | `verify_corpus_ingestion.py` | PASS |
| 8 | `uv lock --check` | OK |
| 9 | `run-p2` twice, `diff -r` | byte-identical |
| 10 | `validate-p2` on both | VALID, 0 errors |
| 11 | Dataset v1 fingerprint | `772694f4…dd57051` unchanged |
| 12 | P1 artifacts / P3 outputs | untouched (hash-verified) |

## Honest limitations

Enumerated in `docs/P2_REGULATORY_COMPLIANCE.md`: synthetic corpus (no
statements about real law), lexical evidence only, tag-level
applicability, no numeric threshold checking, TF-IDF paraphrase limits,
normalization-level Kazakh, LLM refinement unevaluated. The
`assessments_by_label` distribution describes coverage, not legal
classification quality.
