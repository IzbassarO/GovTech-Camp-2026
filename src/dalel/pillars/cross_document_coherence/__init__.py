"""P4 Cross-Document Coherence and Entity Graph pillar.

Deterministic, evidence-first detection of whether the documents inside one
project package describe the SAME project, operator, facility, location,
activity and reporting context consistently.

The pillar assists a human expert: it extracts grounded entity claims from the
accepted Curated Dataset v1, links compatible claims across documents, builds a
lightweight entity graph, and reports ONLY evidence-backed inconsistencies.
Comparisons whose identity or scope is uncertain are suppressed, never guessed.
Every finding is a *potential* inconsistency requiring expert review — never a
legal, administrative or fraud conclusion.

Conservative by construction: precision over recall. A cross-document conflict
is raised only from an explicit incompatible IDENTIFIER (e.g. two different
BINs asserted for the same operator role) — differing spellings, quote styles
and transliterations are treated as aliases, never as contradictions.

No LLMs, no embeddings, no NER training, no vector database, no external graph
database, no geospatial analysis, no network access, no OCR. P4 consumes only
the accepted Curated Dataset v1 text/table representations.
"""

from __future__ import annotations

P4_VERSION = "1.0.0"
