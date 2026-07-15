# Phase 1B — P3 Quantitative Consistency: Final Minimal Correction Report

Date: 2026-07-15. Base commit: `83c7573`.
Status: **final two semantic blockers corrected; all gates pass; ready to
commit.**

This report supersedes the previous one. The second audit found blocking
defects in the FIRST correction: input records with wrong field types
produced tracebacks, damaged scientific notation (`С · 10 мг`) became a
false scalar, «УОНИ 13/55 — 0,3 кг/год» produced a false 13 and an
inverted 55–0.3 range, long decimals (`23,929263576`) were suppressed as
identifiers, per-source-table pairs were suppressed by a blanket reason
instead of positive sub-entity compatibility, high severity was reachable
with unstated periods/qualifiers, aggregation hierarchy could be inferred
from numerical equality alone, «Всего → в том числе» layouts were
unsupported, consistent aggregation checks were not serialized, and the
validator did not independently replay every serialized decision.

## 1. Second-audit blockers → root cause → correction → regression test

| Blocker | Root cause | Correction | Regression test(s) |
|---|---|---|---|
| Wrong-type input fields → traceback; foreign schema versions accepted | ad-hoc key checks instead of the accepted contract | `input_contract.py`: every record validated against the curated Pydantic models (`extra="forbid"`) + `SUPPORTED_INGESTION_SCHEMAS` gate; `P3RunError` with file:line + field path | CLI input matrix (11 cases) in `test_p3_audit2_regressions.py` |
| `С · 10 мг` → scalar 10 | lost-exponent rule matched only digit coefficients | `_LOST_POWER_RE` also matches 1–3-letter coefficients; reason `missing_scientific_exponent` | `test_variable_coefficient_damaged_power_suppressed` |
| «УОНИ 13/55 — 0,3 кг/год» → 13 + range 55–0.3 | model ratios unrecognized; dash-range crossed a ratio boundary | `_MODEL_RATIO_RE` equipment-identifier zone; the dashed value stays a key-value scalar | `test_electrode_model_ratio_em_dash` (+3 dash/model cases) |
| `23,929263576 т/год` suppressed as identifier | MAX_QUANTITY_DIGITS applied to decimal-bearing tokens | identifier digit cap gated on `integer_shaped` (no decimal separator) | `test_long_comma_decimal_preserved` (+2) |
| Blanket `source_block_subentities` suppression | no sub-entity identity dimension | `sub_entity` on mentions (release points `rp:…`, operations `op:…`), sub-blocks with strict-interior pages, tri-state compatibility | `test_same_source_different_equipment_suppressed`, `test_same_source_unknown_equipment_no_strong_finding` |
| High severity with None periods / empty qualifiers | absence treated as agreement | tri-state per dimension: only explicit `match` counts; any `unknown` caps at low; `high_severity_eligible` requires all-match | `test_missing_period_prevents_high_and_medium`, `test_missing_qualifiers_prevent_high`, `test_unknown_facility_prevents_high`, `test_fully_aligned_contradiction_reaches_high` |
| A=5,Б=2,В=3,Г=4 vs «Итого 14» excused | numerical-equality subtotal pairing; per-operand tolerances | structural/textual hierarchy evidence only; rounding tolerance = 0.5 × stated total's quantum | `test_coincidental_equality_is_not_hierarchy`, `test_real_mismatch_with_coincidental_equality_still_detected` |
| «Всего → в том числе» unsupported | only upward spans | `_collect_below`: below/including directions; valueless «в том числе:» is a marker, not a category header | `test_total_then_including_consistent`, `test_total_then_including_mismatch`, `test_labeled_subtotal_with_including_children_not_double_counted` |
| Consistent checks unserialized | only mismatches recorded | `aggregation_checks.jsonl` for EVERY evaluated check with components, totals, decision | `test_consistent_aggregation_checks_serialized` |
| Suppression counters without examples | sampling only at one call site | stratified samples at ALL pair/group guard sites; ALL reasons + tri-state states on each sample | `test_guard_stage_suppressions_serialize_pair_samples`, `test_suppressed_comparison_samples_cover_reasons` |
| One-field tampering undetected | validator trusted serialized values | full replay: IDs, conversions, tolerance/severity/confidence, aggregation sums from raw cells, scores, orderings, template | parametrized tamper matrix (13 finding fields + mention/check/score/template cases) |
| Resolvable info cues unresolved | no context passes | `resolution.py`: formula chains, aggregation equality, engineering magnitude, twin propagation, spatial sequences | `test_formula_resolves_ambiguity` (+4) |
| Unknown direct identity emitted as 17 scored low contradictions | direct matcher allowed tri-state `unknown` | direct comparison now requires positive matches for source/facility, applicable sub-entity, aggregation scope, metric, substance, period and qualifiers; otherwise unscored `identity_not_established` with every `unknown_*` reason | generic reused-source, missing-identity, fully-aligned conflict/equivalence regressions |
| Five utility-table ambiguity findings survived | resolver used document-wide style but not local table evidence | compatible unambiguous comma-decimal cells establish table style unless the table has positive comma-thousands evidence; narrative twins inherit the resolution | mixed-table, column-local, comma-thousands, isolated `1,234`, table/narrative twin regressions |

Two further defect families were found during the FINAL manual mention
review of this round and fixed the same way (failing test first):

- «№ п.п.» row-number headers inherited the percentage-points unit
  (22 production mentions at confidence 0.95) → item-number headers are
  identifier columns (`test_item_number_header_is_identifier_not_percent_points`);
- dotless OCR fragments («гру пп ы суммации», «NI ПП») matched the
  «п.п.» alias because registry keys strip dots — substance codes became
  unit-bearing quantities → percent-points now requires the dotted or
  spelled-out raw form (`test_bare_pp_token_is_not_percent_points`).

And two chain-safety defects found by cell-level review of aggregate
mismatches (all six of which were false positives): mixed chains could
double-count an unestablished «Итого», and subtotal chains linked rows
whose labels merely shared a first word — corrected to
`established_totals` gating and full-normalized-label identity
(`test_mixed_chain_requires_established_subtotals`,
`test_subtotal_chain_requires_identical_labels`).

## 2. Architecture after the second correction (16 modules)

New: `input_contract.py` (contract validation), `resolution.py`
(context-based ambiguity resolution). Changed: `number_parser.py`
(letter-coefficient lost exponents, model ratios, integer-shaped
identifier gate), `units.py` (percent-points raw-form guard),
`semantic_context.py` (+sub-entity lexicons), `extractor.py` (sub-blocks,
`resolve_facility`, «№ п.п.» identifier headers), `matcher.py`
(`assess_pair` tri-state, guard-stage sampling), `scoring.py`
(`high_severity_eligible` all-match), `comparisons.py` (unknown-dimension
caps, rationale lists unknown dimensions), `aggregations.py` (structural
hierarchy, below/including, established-subtotal chains, serialized
checks), `pipeline.py` (contract validation, new artifacts),
`validation.py` (independent replay + tamper rejection), `schemas.py`
(`sub_entity`, `dimension_states`, `P3AggregationCheck`, extended
samples).

## 3. Quality gates (all actually executed, in order)

| # | Command | Result |
|---|---|---|
| 1 | `uv run pytest` | **398 passed, 3 deselected** |
| 2 | `uv run ruff check .` | All checks passed |
| 3 | `uv run ruff format --check .` | 90 files already formatted |
| 4 | `uv run mypy src` | Success, 64 source files |
| 5 | `validate_dataset_foundation.py` | READY, 0 errors |
| 6 | `uv run dalel validate-curated` | VALID, 0 errors |
| 7 | `verify_corpus_ingestion.py` | FINAL VERIFICATION STATUS: PASS |
| 8 | `uv lock --check` | OK (144 packages; pre-existing local edits preserved) |
| 9–10 | `run-p3` twice into clean dirs, `diff -r` | byte-identical; canonical output identical to clean runs |
| 11 | `validate-p3` | VALID, 0 errors (full replay incl. raw-cell rescans) |
| 12 | Dataset v1 fingerprint | `772694f42bbf22dd5d649c7eb0d79e8cc73b9e8c2e9b0eae8790633c9dd57051`, 474 checksums |
| 13 | P1 artifacts | combined hash `eed1c6f5c58c…dfee2cbfb9e0` unchanged |
| 14 | temp files in repo | none |

## 4. Production results (first correction → second correction)

| Metric | 1st correction | 2nd correction |
|---|---|---|
| mentions | 16 947 | 17 097 (long decimals recovered; bogus «п.п.» units removed) |
| with recognized unit | 5 076 | 5 078 |
| suppressed numbers | 18 405 | 18 270 (19 reasons, 169 provenance samples) |
| compared pairs | 12 | 63 (tri-state replaces blanket suppression) |
| aggregation checks | 62 (62 ok), mismatches only serialized | 67 evaluated, **67 consistent**, ALL serialized (37 unique records) |
| suppressed comparisons | 1 579, counters only for guards | 4 117 reason occurrences; 468 serialized diagnostics |
| ambiguities resolved from context | 0 | 25 |
| findings | 11 (all info) | **0 at every severity** |

## 5. Manual semantic review (performed on the FINAL output)

- **All former 17 low findings**: exact candidate IDs remain serialized as
  unscored `identity_not_established` diagnostics with full provenance and
  all unknown dimensions; old priority-score impact 85, new impact 0.
- **All former 5 info cues**: the utility table contains positive local
  comma-decimal evidence (`0,187`, `6,0`) and no comma-thousands pattern;
  all compatible ambiguous cells resolve via `table_decimal_comma`.
- **All 67 aggregation checks consistent**; the six aggregate mismatches
  reported mid-round were verified false positives (chain defects above)
  and their tables replay exactly.
- **30 stratified mentions** across 16 documents — this review caught the
  two «п.п.» defect families, which were then fixed with failing tests
  first and the whole verification sequence re-run.
- **37 suppressed-number samples** across all 19 reason families and
  **24 suppressed-comparison samples** across all 10 pair-level families
  inspected; the formerly audited Bereke (56 serialized candidates),
  AZM (now the 9 low review cues) and Sintez (limit-qualifier and
  scope suppressions) families are all locatable in diagnostics.

## 6. Remaining limitations

Enumerated in `docs/P3_QUANTITATIVE_CONSISTENCY.md`: unscored suppression
diagnostics under unknown direct identity; excluded
ambiguous numerals; no rate-basis conversions; space-grouped prose
thousands missed (suppressed, never misread); inert unitless mentions;
lexicon coverage; alias-level Kazakh; OCR distortions never reach high.

## 7. For the reverifier

From this working tree: run gates 1–14 above; hand-check
`data/results/p3/v1/findings.jsonl` (0 records) and the 468 serialized
candidate diagnostics against
`data/curated/v1/sections.jsonl`/`tables.jsonl`; audit
`aggregation_checks.jsonl` (every evaluated check with per-component
decisions), `candidates.jsonl` (compared + stratified suppressed samples
with tri-state dimension states and ALL rejection reasons) and
`suppressed_samples.jsonl`; tamper with any single serialized field and
observe `validate-p3` reject it. Nothing has been committed or pushed.
