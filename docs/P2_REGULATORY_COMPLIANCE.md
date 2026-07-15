# P2 — Regulatory Compliance (Phase 2, demo-ready MVP)

Expert-support module: deterministic retrieval of requirement-level
regulatory records, evidence-first assessment of project documentation
against them, and cautious review candidates. **P2 never makes legal
conclusions**: it never states that a project complies with or violates
the law, never says a permit must be granted or rejected, and never
asserts that an obligation definitely applies when applicability is
uncertain.

> **Corpus warning.** The packaged corpus is SYNTHETIC:
> *Illustrative demo regulatory corpus. Not an authoritative legal
> source.* No local authoritative regulatory texts exist in this
> repository; the demo corpus illustrates requirement SHAPES, not
> Kazakhstan law. Findings from it are hard-capped below medium severity.

- Offline and deterministic by default: no LLM, no network, byte-identical
  artifacts on identical inputs (no timestamps).
- Input: accepted Curated Dataset v1 (`projects.jsonl`, `documents.jsonl`,
  `sections.jsonl`) — read-only, validated against the accepted models.
- Optional LLM assessor behind an AlemLLM-ready provider abstraction;
  never enabled by default, never used in tests.

## Package layout

```text
src/dalel/pillars/regulatory_compliance/   (13 modules)
  __init__.py         P2_VERSION
  config.py           thresholds, severity policy, provider env names
  schemas.py          requirements, evidence, retrievals, assessments,
                      findings, scores (Pydantic, extra="forbid")
  normalization.py    RU/KK/EN normalization, tokenization, conservative
                      inflection-tolerant token matching
  corpus.py           strict corpus loading/validation + demo resource
  evidence.py         addressable project evidence with provenance
  retrieval.py        deterministic TF-IDF retriever with declared boosts
  nli.py              deterministic 4-label baseline
  prompts.py          delimited injection-resistant prompt + JSON schema
  providers.py        LLMProvider / Mock / Disabled / OpenAI-compatible +
                      content-addressed response cache
  assessment.py       NLI + optional LLM merge (confirm-or-downgrade)
  scoring.py          finding taxonomy, severity caps, priority scores
  reports.py          Markdown report + CLI summary
  pipeline.py         run_p2 orchestration, review-template merge
  validation.py       validate-p2 independent replay
  resources/demo_regulatory_corpus.jsonl   12 synthetic requirements
```

## Regulatory corpus format

One JSONL file; each line is a requirement-level record: stable
`requirement_id`, corpus id/version, jurisdiction, authority, document
title/number, article, exact `requirement_text` with
`source_hash = sha256(requirement_text)`, short title, `obligation_type`
(required_document | mandatory_section | quantitative_limit |
disclosure_requirement | procedural_requirement | monitoring_requirement |
permit_requirement | prohibition | applicability_condition | other),
structured `applicability_tags` («key:value»), topics, activities,
machine-actionable hints (`required_document_type`, `required_concepts`),
effective dates when known, source URL/file, `is_authoritative`,
`demo_only`, language, notes and limitations. Unknown metadata stays
`null` — the loader never invents numbers, dates or URLs, and rejects
duplicate IDs, hash mismatches, unsupported versions, inverted effective
dates and demo-marked records claiming authority. Authoritative
requirements can be added later in the SAME format without pipeline
changes.

## Retrieval

Compact deterministic TF-IDF (no search framework, no embeddings):
requirement text = title + text + topics + tags + activities; queries are
built per document (document type + section headings) and per package
(document types + project context). Score = normalized TF-IDF dot product
plus DECLARED boosts (exact title terms, applicability-tag match, topic
match), each recorded in the retrieval record together with matched
terms, query hash, evidence references and a rationale. Ordering is
deterministic: `(-score, requirement_id)`; scores are rounded before
ranking. Requirements below `MIN_RETRIEVAL_SCORE` are not retrieved —
weak topical overlap never forces a regulation match. One exception is
explicit and recorded: package-wide `required_document` obligations are
always checked per package (their lexical signal disappears exactly when
the required document is absent); such records carry a backstop
rationale and their REAL (possibly near-zero) score.

## NLI labels and the deterministic baseline

Labels: `supported_by_evidence`, `potential_conflict`,
`insufficient_evidence`, `not_applicable`.

Applicability comes from DECLARED tags only (document types present,
industry match, `package:any`); tags the dataset cannot evaluate (e.g.
`category:I`) yield `unknown` — never a guess. The baseline then decides
per obligation type:

- required_document: target type present → supported (document evidence);
  absent → potential_conflict review cue with explicit «package scope
  uncertain» limitation;
- mandatory_section / monitoring / disclosure / procedural: concept match
  in target-document HEADINGS (strong) or TEXT (weaker, with a bounded
  quotable snippet); explicit negation inside the snippet
  («не проводится», «отсутствует», …) → potential_conflict; nothing
  found → mandatory_section becomes a potential_conflict only when
  retrieval is strong, softer types become insufficient_evidence;
- quantitative_limit / prohibition / permit_requirement / other: the
  baseline NEVER claims support or conflict from keyword presence
  (numeric consistency belongs to P3) → insufficient_evidence;
- failed applicability → not_applicable; unknown applicability blocks
  conflict/support upgrades.

`potential_conflict` additionally requires retrieval score ≥
`CONFLICT_MIN_RETRIEVAL_SCORE`: weak retrieval can never become a
conflict. Concept matching tolerates RU/KK inflection conservatively
(long common prefixes; single final-char changes for 4+-char tokens);
it never leaps on short or dissimilar tokens.

## Optional LLM mode (AlemLLM-ready provider architecture)

`LLMProvider` abstraction with `MockProvider` (tests/offline),
`DisabledProvider` and `OpenAICompatibleProvider` — the latter configured
ENTIRELY via environment: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`,
`LLM_MODEL` (no hardcoded credentials, URLs or model names; temperature
0). Any OpenAI-compatible endpoint — including an AlemLLM-compatible
one — plugs in through configuration only; no AlemLLM call has been
executed from this repository.

The model receives ONE requirement, a bounded evidence bundle, explicit
applicability metadata and a strict JSON schema, inside fenced blocks
labelled «данные, не команды»; the system instruction forbids following
instructions found inside documents. Every response is validated:
schema, label vocabulary, confidence bounds, evidence IDs must resolve,
quotes must be EXACT substrings of supplied evidence. Invalid output
falls back to the deterministic result with an explicit quality flag.
A valid response may CONFIRM the deterministic label or DOWNGRADE it to
`insufficient_evidence`; upgrades are rejected (`llm_upgrade_rejected`) —
no finding is ever based only on an LLM statement, and LLM confidence
never overrides missing applicability evidence. Responses are cached
content-addressed (`sha256(provider|model|prompt)` →
`llm_cache.jsonl`); repeated runs reuse validated cached responses.

## Findings, severity and scores

Taxonomy: `missing_required_document`, `missing_required_section`,
`potential_regulatory_conflict`, `insufficient_regulatory_evidence`,
`applicability_uncertain`, `outdated_or_unknown_regulation_version`,
`non_authoritative_demo_requirement`, `malformed_regulatory_source`.
Supported and not-applicable assessments produce no findings; every demo
run adds one per-project info notice that a synthetic corpus was used.

Severity policy: demo-only requirements are hard-capped at LOW and never
promoted. HIGH requires an authoritative requirement, confirmed
applicability, inference confidence ≥ 0.85 and ZERO quality flags;
unconfirmed applicability is never medium. Severity and confidence stay
separate; the priority score (25/12/5/2 points per finding, cap 100) is
a transparent review priority — NOT a calibrated probability — with
per-finding contributions recorded, compatible with later meta-risk
scoring.

## CLI

```bash
uv run dalel run-p2 [--dataset data/curated/v1] [--regulations demo|<path>]
                    [--output data/results/p2/v1] [--top-k 5]
                    [--provider none|mock|openai-compatible]
                    [--cache/--no-cache] [--project-id P]
                    [--fail-on info|low|medium|high] [-v]
uv run dalel validate-p2 [--dataset …] [--regulations …] [--output …]
```

Expected input problems (missing dataset, malformed corpus, wrong types)
print a concise `ERROR: …` and exit 1 — never a traceback. The demo
corpus prints its warning on every run.

## Outputs

`requirements_snapshot.jsonl` (corpus verbatim), `project_evidence.jsonl`
(addressable evidence incl. quotable snippets), `retrievals.jsonl`,
`assessments.jsonl`, `findings.jsonl`, `document_scores.jsonl`,
`project_scores.jsonl`, `metrics.json`, `config_snapshot.json`,
`report.md`, optional `llm_cache.jsonl`, and the
`data/annotations/p2_review_template.jsonl` merge that preserves expert
decisions (P1/P3 contract; stale rows move to
`review_template_stale.jsonl`).

`validate-p2` REPLAYS everything deterministic from the dataset and the
corpus: snapshot equality, retrieval scores/ordering, assessment IDs and
baseline fields, evidence resolution and exact quote membership, findings
reconstruction (types, severities, ordering, IDs), demo severity
restrictions, score recomputation, metrics/report counts and
review-template correspondence. Tampering with any single serialized
field is rejected; provider-dependent fields are checked structurally
(hash formats, confirm-or-downgrade label policy).

## Limitations

- The packaged corpus is synthetic: no assessment of this run says
  anything about compliance with the law of Kazakhstan.
- Labels rest on lexical evidence in the curated dataset; absence of a
  match does not prove absence of content (OCR noise, synonymy), and
  presence of a heading does not prove substantive compliance.
- Applicability is evaluated only against declared tags; object category,
  permit class and temporal validity are not derivable from the dataset.
- Quantitative thresholds are never compared with project values by the
  baseline (P3 owns numeric consistency).
- Retrieval is lexical TF-IDF: paraphrase beyond the inflection tolerance
  is missed; Kazakh support is normalization-level.
- The LLM layer, when enabled, refines rationale/labels within the
  confirm-or-downgrade policy only; its output quality is not evaluated
  here and it never creates findings on its own.

P2 supports expert review and makes no final legal or administrative
decisions.
