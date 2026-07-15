"""DÁLEL Eco demo website API.

A thin, read-only FastAPI layer over the ALREADY ACCEPTED pillar
artifacts (P1 Document Integrity, P2 Regulatory Compliance demo,
P3 Quantitative Consistency). It never re-runs analysis, never mutates
curated data, and never exposes local filesystem paths or secrets — it
normalizes on-disk artifacts into stable frontend contracts.

The pillar contract is intentionally generic so future pillars
(P4 / P5 / P6, integrated meta-risk scoring) can be added at the service
layer without changing the API shape or the frontend.
"""

API_VERSION = "1.0.0"
