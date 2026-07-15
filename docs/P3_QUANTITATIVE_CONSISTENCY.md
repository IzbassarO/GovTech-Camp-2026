# P3 — Quantitative Consistency (Phase 1B, final post-audit revision)

Deterministic, evidence-first detection of potentially contradictory or
mathematically inconsistent quantitative claims in environmental permit
documentation (RU / KK / EN). P3 assists a human expert: every finding is a
**potential** inconsistency requiring expert review. P3 never makes legal
conclusions and never claims a document is fraudulent, invalid or
noncompliant.

- No LLMs, no embeddings, no network access, no OCR runs.
- Input: the accepted Curated Dataset v1 only (`sections.jsonl`,
  `tables.jsonl`; `pages.jsonl` for OCR metadata; images are never loaded).
- Repeated runs on identical input produce **byte-identical** artifacts
  (P3 output files contain no timestamps).

Honesty note on claim levels — this document distinguishes:

- **structurally valid artifacts**: outputs pass schema/ID/ordering checks;
- **mathematically reproducible calculations**: every serialized value,
  conversion, difference and decision replays exactly (`validate-p3`
  recomputes them independently);
- **semantically verified findings**: a human confirmed the two values
  describe the same real-world quantity. P3 output alone NEVER implies this
  third level; findings are review candidates.

## Package layout

```text
src/dalel/pillars/quantitative_consistency/   (16 modules)
  __init__.py         P3_VERSION
  config.py           tolerances, severity/confidence rubrics, snapshot
  schemas.py          Pydantic records: mentions, candidates, findings,
                      aggregation checks, suppressed samples, scores
  input_contract.py   input validation against the curated dataset models
                      + supported ingestion schema-version gate
  normalization.py    superscript-safe text/unit normalization
  number_parser.py    numeric scanning + identifier suppression (Decimal)
  units.py            declared unit-alias registry, exact conversions
  semantic_context.py metric/substance/qualifier/period/source/sub-entity
                      lexicons
  extractor.py        mentions, source blocks, sub-entity blocks, facility
                      scopes, suppression samples
  resolution.py       deterministic ambiguity-resolution passes (table-local
                      decimal style, formula chains, aggregation equality,
                      engineering magnitude, twin propagation, sequences)
  matcher.py          tri-state pair assessment, candidate construction,
                      stratified suppression sampling (incl. guard stages)
  comparisons.py      direct/equivalent-unit/bound/percent-triple rules
  aggregations.py     structural aggregation hierarchy, serialized checks,
                      percent columns, row bounds
  scoring.py          severity + confidence rubrics, high-severity gate
  reports.py          Markdown report
  pipeline.py         run_p3 orchestration, review-template merge
  validation.py       validate-p3 independent recomputation
```

## Number formats

Decimal comma and dot, thousands grouping by spaces / NBSP / dots / commas
(unambiguous multi-group shapes), signed values, scientific notation with
comma or dot mantissa (`2,744E-05`), power notation as ONE numeric
expression (`10⁵`, `10⁻⁵`, `2 × 10⁵`, `2 · 10⁻⁵`, `10^3` — never split into
10 and the exponent), percentages, leading-separator decimals (`.5`),
ranges, bounds (RU/EN/KK), approximations, zero and negative values.

**Ambiguous `1,234` (single separator + exactly three fraction digits)**
is resolved by context, never silently:

- document decimal style matches the separator → decimal (`1,234` → 1.234
  in a comma-style document);
- opposite decimal style AND positive grouping evidence (the document
  demonstrably writes `1,234,567`-style groups) → thousands (`1,234` →
  1234, flagged `thousands_from_document_style`);
- anything else → the token keeps its raw form, is flagged
  `ambiguous_decimal_grouping`, is EXCLUDED from all comparisons and
  aggregation sums, and surfaces as an `ambiguous_numeric_format` info cue
  with the reason. Style alone is deliberately insufficient: this corpus
  mixes decimal conventions WITHIN documents, and a style-only rule was
  observed to corrupt `69,625` into 69625 (×1000).

**Dash classification** is syntactic:

- sign: only after explicit openers (`:`, `=`, `<`, `>`, `≤`, `≥`, `(`) —
  `температура: -7,2 °C` stays negative;
- range: symmetric spacing only (`10-12`, `10 – 12`); asymmetric
  (`МР -3 -2,0 кг/год`) is the key-value/bullet idiom and never creates
  ranges or negative values (`УОНИ 13/55 (аналог Э42) -0,3 кг/год` → +0.3);
- letter-attached (`КС-135`), zero-padded pairs (`6001-001`) and bare
  unitless integer pairs (`6701-703`) are identifiers.

`N · 10` with a lost superscript exponent is suppressed as
`missing_scientific_exponent` — never read as ×10 — including the
letter-coefficient shape (`С · 10 мг`, an OCR-damaged formula) and the
digit shape inside formula chains (`5 · 10 6`). Long high-precision
decimals (`23,929263576 т/год`) are quantities: the max-digit identifier
guard applies only to integer-shaped tokens without decimal separators.
Equipment model ratios («УОНИ 13/55», «МР-3») are identifier zones — the
ratio never becomes a scalar and an adjacent dashed value keeps its
key-value reading (`УОНИ 13/55 … -0,3 кг/год` → +0.3 кг/год).

Suppressed non-quantities (years, dates, clause/page references,
phones/BIN, coordinates, substance codes, formula variables `К=0,2`,
identifier columns such as «Код», «Год достижения НДВ» and «№ п.п.») are
counted by reason with provenance samples. The «№ п.п.» row-number header
and dotless OCR fragments («гру пп ы», «NI ПП») never match the
percentage-points unit: `п.п.` requires the dotted or spelled-out form on
the raw text.

## Units

Declared alias registry only (~130 aliases; complete dump in
`config_snapshot.json → unit_registry`). Dimensions are `(kind,
time_basis)` pairs; `г/с` ↔ `т/год` and `мг/нм3` ↔ `мг/м3` are never
converted. Kinds: mass, mass_rate (s/h/day/month/year), volume,
volume_rate, concentration, concentration_normal, **density** (`г/см3`,
`кг/м3`, `т/м3` — distinct from concentration by policy), mass_fraction,
area, percent, percent_points (incl. EN «percentage point(s)»), power,
temperature, velocity, length.

Unit matching is longest-declared-alias with token boundaries; a match
followed by a compound continuation (`/`, `·`, `×`, `^`) is rejected, so
an unsupported compound (`г/см3` before density existed, `кДж/кг`) is left
UNMATCHED rather than prefix-matched into a wrong dimension. Raw units are
preserved; conversions are exact Decimal multiplications serialized in
findings. Table cells inherit the column-header unit (flagged); a cell
whose inline unit contradicts its column unit never feeds aggregation.

## Source, scope and sub-entity attribution (post-audit model)

Every mention carries `aggregation_scope ∈ {source, enterprise, unknown}`
and `sub_entity` (release point «источник выделения N 6001 05» → `rp:…`,
or operation «РАСЧЕТ выбросов ЗВ от сварки» → `op:…`):

- **source**: an explicit per-row source column / caption, a sentence or
  own-section-title source («Источник № 6023»), or a page STRICTLY INSIDE
  a source block. Blocks run from one source heading to the next (or to an
  enterprise-inventory section); boundary pages stay unknown because the
  dataset has no within-page ordering — a heading starting on the same
  page as a table is never assigned to it, and never retroactively to a
  preceding table. Index-only continuation fragments inherit attribution
  only from an adjacent preceding table with the same column count.
  Sub-entity blocks nest inside source blocks with the same strict-interior
  page rule.
- **enterprise**: pages covered by explicit inventory sections («Перечень
  загрязняющих веществ…», «нормативы выбросов», «итого по предприятию»).
- **unknown**: everything else. Unknown stays unknown.

Pair eligibility is a **tri-state assessment per semantic dimension**
(aggregation scope, source, sub-entity, metric, substance, period and
qualifiers): `match` needs positive evidence on both sides and `conflict`
means known and different. A direct-value candidate is compared only when
every required identity dimension is `match`. Any `unknown` dimension
suppresses it as the unscored diagnostic `identity_not_established`, with
all dimension states and specific `unknown_*` reasons serialized. Two
calculation tables under the same ИЗА source but different known
sub-entities are suppressed as `sub_entity_mismatch`; a shared source with
unknown equipment/process identity is never described or scored as a
contradiction. Fully aligned source-level pairs remain comparable.

## Qualifier axes

- wildcard axes (different stated tags suppress; one-sided stated is a
  penalized uncertainty): {max-onetime | gross | annual-mean | daily-mean},
  {planned | actual}, {with | without treatment}, {accumulated | generated};
- **strict axes** (even explicit-vs-unstated suppresses): {emergency |
  background} — an emergency value must not be compared with an unstated
  value as though it were normal operation; {limit} — a permitted-limit
  value is a norm, not a measurement (the bound rule handles limit vs
  actual).

## Comparison rules

Rules A/B (direct and equivalent-unit conflicts), C (aggregation), D
(percent columns + `N из M (P%)`), E (different stated periods never
compare), F (bounds incl. same-row «норматив vs факт»), G (impossible
values, range inversions — ambiguous-format values excluded), H
(cross-representation/cross-document through the same gates).

**Aggregation hierarchy** (rule C) is built from STRUCTURAL and TEXTUAL
evidence only — numerical equality is banned as hierarchy evidence
(A=5, Б=2, В=3, Г=4 with «Итого 14» must not be excused by pairing 5=2+3):

- component spans run upward from a labeled total («итого», «всего»,
  «подытог») to the previous total / divider / category header (a label
  row without values); valueless subset markers («в том числе:») open
  subordinate spans, while a VALUED subset row is self-contained and
  counts as one component;
- «Всего → в том числе» layouts (total ABOVE its components) are checked
  in the below/including direction;
- subtotal chains («Итого A + Итого B = Всего») require IDENTICAL full
  normalized subtotal labels; mixed chains (details + subtotals) require
  every participating subtotal to be independently established by its own
  span first — an unestablished «Итого» is never silently treated as a
  sibling component;
- rounding tolerance is half of the STATED total's display quantum only
  (per-operand tolerances were audited to excuse real integer mismatches);
- page-continuation fragments and structural table copies (fingerprint
  over normalized cells) are never counted as independent evidence.

EVERY evaluated check — consistent or not — is serialized to
`aggregation_checks.jsonl` (check id, direction, every component row with
its inclusion/exclusion decision and conversion, expected/observed totals,
decimal style, decision, finding id when a mismatch is reported), and
duplicated column signatures within one table are merged into one record.

## Tolerances

```text
mismatch  <=>  abs_diff > max(absolute_tolerance, rounding_tolerance)
           AND rel_diff > relative_tolerance
rel_diff = abs_diff / max(|a|, |b|)      (symmetric, zero-safe)
```

Relative 2%, per-dimension absolute floors, rounding tolerance
`0.5 × Σ display quanta`, zero-reference gate (10× floor), approximate ×5,
percentages 0.5 p.p. + half the displayed quantum.

## Severity, confidence, high-severity gate

Severity (material size) and confidence (deterministic rubric with
serialized factors) stay separate. **A direct finding requires every
identity dimension to be an explicit `match`** — two unstated periods or
two empty qualifier sets are `unknown`, never a match — plus resolved
units. High additionally requires extraction confidence ≥ 0.8 on both
sides, no approximation and no ambiguity flags (OCR, ambiguous format,
multi-number cells, echoes). Unknown direct identity is suppressed before
scoring; it is not a low-severity finding. Aggregations reach high only for
clean segments without OCR. Zero findings is the intended output when no
quantity is positively established as contradictory.

## Ambiguity resolution from document context

Before matching, deterministic passes resolve `ambiguous_decimal_grouping`
mentions using local evidence only, recording `resolved_from_context` and
the evidence kind. Table-local resolution accepts a comma decimal when a
compatible unambiguous comma-decimal cell establishes that table's style
and the same table contains no positive comma-thousands pattern such as
`1,234,567`. Other passes use exact formula equality, aggregation equality,
engineering magnitude for length/elevation vocabulary, twin propagation
and descending spatial sequences. Values that remain ambiguous stay
excluded from comparison and surface as `ambiguous_numeric_format` info
cues.

## Input error handling

Every input record is validated against the accepted Curated Dataset v1
Pydantic models (`extra="forbid"`) plus an explicit supported
`schema_version` gate before extraction starts. Expected input problems
never produce tracebacks: malformed JSON lines, non-object records,
missing or wrongly-typed fields, unsupported schema versions and
unreadable files become a concise `P3RunError` naming the file, line and
field path with a suggested action; the CLI prints `ERROR: …` and exits 1
without writing a partial output directory.

## CLI

```bash
uv run dalel run-p3 [--dataset …] [--output data/results/p3/v1]
                    [--project-id P] [--document-id D]
                    [--fail-on info|low|medium|high] [-v]
uv run dalel validate-p3 [--dataset …] [--output …]
```

## Outputs

`mentions.jsonl`, `suppressed_samples.jsonl` (provenance-bearing,
deterministically stratified samples per suppression reason × document:
ids, container, row/col or char span, raw token, context, parser state,
secondary reasons), `candidates.jsonl` (compared pairs + stratified
suppressed-pair samples — including guard-stage rejections such as
same-physical-table and entity under-resolution — with per-side semantic
context, tri-state dimension states and ALL rejection reasons),
`aggregation_checks.jsonl` (every evaluated aggregation check, consistent
ones included), `findings.jsonl`, `document_scores.jsonl`,
`project_scores.jsonl`, `metrics.json` (full per-reason counts — samples
are stratified, counters are exhaustive), `config_snapshot.json`,
`report.md`, and the `data/annotations/p3_review_template.jsonl` merge
that preserves human decisions (rows whose findings disappeared move to
`review_template_stale.jsonl` instead of being deleted).

`validate-p3` independently REPLAYS (not re-reads): mention IDs from their
content basis, unit conversions from the registry, tolerance and severity
decisions for direct findings (including tri-state caps and the
high-severity gate), aggregation expected totals and differences from the
RAW dataset cells (rescanning each component cell), confidence from
serialized factors, document and project scores from findings, findings
ordering, metrics counts against artifacts, report counts, mention spans
against normalized section text / table cells, unique IDs, evidence
page/quote membership in referenced mentions, review-template
correspondence (unknown or missing finding ids are errors), dataset
checksums (Dataset v1 untouched) and suppressed-sample resolution.
Tampering with any single serialized field of a finding, mention,
aggregation check, score or template row is rejected.

## Current production output (accepted Curated Dataset v1)

17 097 mentions (5 078 with units; 242 OCR-flagged), 18 270 suppressed
non-quantities across 19 reasons (169 provenance samples), **0 compared
direct pairs**, 4 117 suppression-reason occurrences and 468 serialized
pair diagnostics, 67 evaluated aggregation checks — **67 consistent** (37
unique records after duplicate-column merge), 25 ambiguous numerals
resolved from context, and **0 findings at every severity**.

All former 17 low direct findings are serialized under their original
candidate IDs as unscored `identity_not_established` diagnostics; their 85
former priority-score points are now zero. The utility table's ambiguous
comma values are resolved by `table_decimal_comma`, so its five capped info
findings also disappear. Zero findings is the precision-first result; no
demo finding is fabricated.

## Known limitations (deliberate false-negative sources)

- Unknown direct identity is retained only as an unscored suppression
  diagnostic; stated conflicts suppress entirely.
- Unresolved ambiguous numerals are excluded from all comparisons.
- A bound at enterprise scope is not checked against source-scope values.
- `г/с` ↔ `т/год` and normal-vs-actual m³ are never converted.
- Space-grouped thousands inside prose («80 000 кв. м») are not parsed as
  one number; the orphaned group is suppressed (`zero_padded_code`), so
  such quantities are missed rather than misread.
- Unitless table numerals without substance/metric identity (TOC page
  numbers, plan item counts) remain as inert mentions: they cannot enter
  any comparison, but they inflate the raw mention count.
- Table-level aggregation suppressions (fragments, copies) are counted
  per reason; only evaluated checks get serialized records.
- Lexicons cover the frequent pollutants; unlisted substances match only
  via inventory-code identity.
- Kazakh support is alias-level; the corpus contains no machine-readable
  Kazakh quantitative text (EasyOCR limitation, see dataset card).
- OCR distortions can still hide real contradictions; OCR-flagged values
  never reach high severity.

P3 supports expert review and does not make final legal decisions.
