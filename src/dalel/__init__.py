"""DALEL Eco - Phase 0 local document ingestion.

Evidence-first ingestion of environmental permit documentation.
Heavy parser dependencies (Docling, OCR engines) are imported lazily;
importing this package must never trigger model downloads.
"""

__version__ = "0.1.0"
