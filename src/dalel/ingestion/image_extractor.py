"""Embedded-image extraction via PyMuPDF (fallback path).

When Docling succeeds its own picture items are used instead; this module
serves the PyMuPDF fallback route. Images are deduplicated by xref per page
placement and tiny decorative fragments are dropped.
"""

from __future__ import annotations

import logging
from typing import Any

from dalel.config import MIN_IMAGE_DIMENSION_PX
from dalel.ingestion.parsed import ParsedImage
from dalel.schemas.evidence import BBox

logger = logging.getLogger(__name__)


def extract_page_images(doc: Any, page: Any, page_number: int) -> list[ParsedImage]:
    """Extract embedded raster images of one PyMuPDF page.

    ``page_number`` is 1-based. Bounding boxes come from ``get_image_rects``;
    when placement cannot be resolved the bbox stays ``null`` with a warning.
    """
    import fitz  # lazy: PyMuPDF

    images: list[ParsedImage] = []
    try:
        entries = page.get_images(full=True)
    except Exception as exc:
        logger.warning("page %d: get_images failed: %s", page_number, exc)
        return images

    for entry in entries:
        xref = entry[0]
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.width < MIN_IMAGE_DIMENSION_PX or pix.height < MIN_IMAGE_DIMENSION_PX:
                continue
            if pix.colorspace is None or pix.n - pix.alpha >= 4:
                # Stencil masks have no colorspace; CMYK+ must convert before PNG.
                pix = fitz.Pixmap(fitz.csRGB, pix)
            png_bytes = pix.tobytes("png")
            width_px, height_px = pix.width, pix.height
        except Exception as exc:
            images.append(
                ParsedImage(
                    page_number=page_number,
                    warnings=[f"image xref {xref}: pixmap extraction failed: {exc}"],
                )
            )
            continue

        bbox: BBox | None = None
        bbox_warnings: list[str] = []
        try:
            rects = page.get_image_rects(xref)
            if rects:
                rect = rects[0]
                bbox = BBox(l=float(rect.x0), t=float(rect.y0), r=float(rect.x1), b=float(rect.y1))
                if len(rects) > 1:
                    bbox_warnings.append(
                        f"image xref {xref} is placed {len(rects)} times; first placement recorded"
                    )
            else:
                bbox_warnings.append(f"image xref {xref}: placement rect unavailable; bbox is null")
        except Exception as exc:
            bbox_warnings.append(f"image xref {xref}: get_image_rects failed: {exc}; bbox is null")

        images.append(
            ParsedImage(
                page_number=page_number,
                bbox=bbox,
                width_px=width_px,
                height_px=height_px,
                png_bytes=png_bytes,
                warnings=bbox_warnings,
            )
        )
    return images
