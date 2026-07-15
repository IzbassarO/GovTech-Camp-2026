"""P3 Quantitative Consistency pillar.

Deterministic, evidence-first detection of potentially contradictory or
mathematically inconsistent quantitative claims in environmental permit
documentation (Russian / Kazakh / English). The pillar assists a human
expert: every finding is a *potential* inconsistency requiring expert
review — never a legal conclusion or a fraud claim.

No LLMs, no embeddings, no network access, no OCR: P3 consumes only the
accepted Curated Dataset v1 text/table representations.
"""

from __future__ import annotations

P3_VERSION = "1.0.0"
