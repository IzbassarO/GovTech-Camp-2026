"""Mixed ingestion-schema normalization (1.0.0 / 1.1.0).

Per the independent re-verification: legacy 1.0.0 reports lack the three table
counters. Loading them into the current Pydantic report model would silently
zero the counters, which is wrong for documents that do have tables. The
counters are therefore inferred explicitly from the actual ``tables.jsonl``
record count and every inference is recorded as a normalization warning.
Processed reports are never rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LEGACY_COUNTER_WARNING = "legacy_report_counters_inferred"

_COUNTER_FIELDS = (
    "detected_table_items",
    "serialized_table_count",
    "skipped_empty_table_items",
)


@dataclass
class NormalizedCounters:
    detected_table_items: int
    serialized_table_count: int
    skipped_empty_table_items: int
    applied_normalizations: list[str] = field(default_factory=list)
    normalization_warnings: list[str] = field(default_factory=list)


def normalize_table_counters(
    report: dict[str, Any], actual_table_records: int, ingestion_schema_version: str
) -> NormalizedCounters:
    """Return trustworthy table counters for any ingestion schema version.

    Schema >= 1.1.0 reports carry the counters natively; they are used as-is
    (with a consistency check against the physical record count). Legacy
    reports get explicit inference, never model defaults.
    """
    has_native = all(field_name in report for field_name in _COUNTER_FIELDS)
    if has_native:
        counters = NormalizedCounters(
            detected_table_items=int(report["detected_table_items"]),
            serialized_table_count=int(report["serialized_table_count"]),
            skipped_empty_table_items=int(report["skipped_empty_table_items"]),
        )
        if counters.serialized_table_count != actual_table_records:
            counters.normalization_warnings.append(
                "native serialized_table_count "
                f"({counters.serialized_table_count}) disagrees with physical"
                f" tables.jsonl record count ({actual_table_records})"
            )
        return counters

    counters = NormalizedCounters(
        detected_table_items=actual_table_records,
        serialized_table_count=actual_table_records,
        skipped_empty_table_items=0,
        applied_normalizations=[
            f"inferred table counters from tables.jsonl for ingestion schema"
            f" {ingestion_schema_version}: serialized={actual_table_records},"
            f" detected=serialized, skipped=0"
        ],
        normalization_warnings=[LEGACY_COUNTER_WARNING],
    )
    return counters
