"""Phase 0 ingestion pipeline.

Import-light by design: parser modules import Docling/PyMuPDF/python-docx
lazily inside functions so that manifest validation and unit tests never
load parser models.
"""
