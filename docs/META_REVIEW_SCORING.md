# Meta Analysis — Integrated Review Priority Scoring

Meta combines accepted P1–P4 artifacts into a deterministic project-level
**Integrated Review Priority Score** from 0 to 100. It answers which project
package an expert should inspect first. It is not a probability of legal
violation, environmental harm, non-compliance, or a permit recommendation.

## Production contract

The implementation lives in `src/dalel/meta_review/` and keeps artifact loading,
features, coverage, scoring, explainability, calibration readiness, reporting,
the pipeline, and independent validation in separate modules.

Three outputs must be read separately:

1. `review_priority_score` ranks review attention.
2. `evidence_coverage` describes how much relevant analysis could be performed.
3. `assessment_confidence` describes how reliable the integrated score is under
   missing context, suppressed comparisons, and source limitations.

Low coverage reduces confidence; it does not create a lower-priority or “safe”
bonus. An unavailable pillar is explicitly marked unavailable and never treated
as a passed analysis.

## Additive scoring

Every feature records its raw value, normalization, configured weight, raw and
applied contribution, source artifact IDs, source finding IDs, explanation, and
limitations. P1 finding groups are mutually exclusive for positive scoring;
accepted aggregate scores remain visible with zero weight to avoid counting the
same evidence twice. P2 missing-document cues, and P3/P4 severity views, are
likewise exposed without duplicating the underlying assessment or conflict.

For each pillar:

```text
raw subtotal + discount amount + cap adjustment = pillar subtotal
```

For each project:

```text
base score + sum(applied feature contributions)
  + uncertainty adjustment + global cap adjustment = final score
```

All calculations use versioned configuration and two-decimal deterministic
rounding. P2’s current synthetic corpus receives a 0.35 discount and an
8-point upper bound. The bound and whether it actually changed the subtotal are
both exposed. P2 can never dominate the integrated result.

## Calibration policy

The current expert templates contain no completed expert decisions. Therefore
production always exposes:

```json
{
  "calibration_status": "not_available_without_expert_labels",
  "calibrated_probability": null,
  "shap_contributions": null
}
```

No supervised model is trained and no SHAP dependency is installed. A strict
`experimental_test_only=true` fixture and adapter protocol preserve a boundary
for future grouped validation and calibration experiments without presenting
synthetic tests as production evidence.

## Commands

```bash
uv run dalel run-meta
uv run dalel validate-meta
```

The default output is `data/results/meta/v1/`. Validation reloads P1–P4,
recomputes features, normalization, caps, discounts, coverage, confidence,
scores, levels, ordering, metrics, and report text, then rejects any material
drift. Generated results remain untracked.
