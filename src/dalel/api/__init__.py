"""DÁLEL Eco demo website API.

A thin, read-only FastAPI layer over the accepted P1–P4 pillar artifacts
and the validated project-level Meta review-priority assessment. It never
mutates curated or pillar data and never exposes local filesystem paths or
secrets; Meta validation is replayed once while the artifact store loads.

Meta remains separate from finding filters because it synthesizes accepted
evidence rather than creating a fifth class of findings. P5 and P6 remain
explicitly unavailable roadmap phases.
"""

API_VERSION = "1.0.0"
