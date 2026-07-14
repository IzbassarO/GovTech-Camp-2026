"""Phase 0.5: Curated Dataset v1 builder and validator.

Reads ``data/processed`` strictly read-only, normalizes mixed ingestion
schemas (1.0.0 / 1.1.0), re-applies the table validity contract to every
serialized table and writes a leakage-separated curated dataset.
"""

CURATION_VERSION = "1.0.0"
DATASET_VERSION = "v1"
