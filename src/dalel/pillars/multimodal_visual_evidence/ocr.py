"""OCR of visual text for P5 representatives (EasyOCR, ru+en, CPU).

Only cluster representatives and eligible singletons are OCR-ed; duplicates
reuse the representative result. The engine state is always recorded honestly:
``unavailable`` when EasyOCR (or its weights) cannot load, ``failed`` when a
single image errors, ``low_confidence``/``empty`` when the output is unusable.
OCR is never claimed to have succeeded when it did not run.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dalel.pillars.multimodal_visual_evidence.config import (
    OCR_LANGUAGES,
    OCR_MIN_MEAN_CONFIDENCE,
    OCR_MIN_SIDE_PX,
    OCR_TEXT_MAX_CHARS,
)

DISABLE_OCR_ENV_VAR = "DALEL_P5_DISABLE_OCR"


@dataclass
class OcrOutcome:
    status: str  # completed | empty | low_confidence | failed | not_run | unavailable
    engine: str | None = None
    languages: tuple[str, ...] = ()
    text: str | None = None
    mean_confidence: float | None = None
    failure_reason: str | None = None


class OcrEngine:
    """Minimal interface so tests can substitute a deterministic double."""

    @property
    def available(self) -> bool:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    def read(self, path: Path) -> OcrOutcome:
        raise NotImplementedError


class EasyOcrEngine(OcrEngine):
    """Lazy EasyOCR reader shared per process (CPU, ru+en)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reader: Any = None
        self._failure: str | None = None

    @property
    def name(self) -> str:
        return "easyocr"

    @property
    def available(self) -> bool:
        return self._ensure_reader() is not None

    def _ensure_reader(self) -> Any:
        with self._lock:
            if self._reader is not None or self._failure is not None:
                return self._reader
            try:
                import easyocr

                self._reader = easyocr.Reader(list(OCR_LANGUAGES), gpu=False, verbose=False)
            except ImportError:
                self._failure = "easyocr dependency is not installed"
            except Exception as exc:  # weight download failure, torch issues
                self._failure = f"easyocr reader could not start ({type(exc).__name__})"
            return self._reader

    def read(self, path: Path) -> OcrOutcome:
        reader = self._ensure_reader()
        if reader is None:
            return OcrOutcome(status="unavailable", failure_reason=self._failure)
        try:
            raw = reader.readtext(str(path), detail=1, paragraph=False)
        except Exception as exc:
            return OcrOutcome(
                status="failed",
                engine=self.name,
                languages=OCR_LANGUAGES,
                failure_reason=f"recognition error ({type(exc).__name__})",
            )
        fragments: list[str] = []
        confidences: list[float] = []
        for item in raw:
            try:
                _bbox, text, confidence = item
            except (TypeError, ValueError):
                continue
            cleaned = str(text).strip()
            if cleaned:
                fragments.append(cleaned)
                confidences.append(float(confidence))
        if not fragments:
            return OcrOutcome(status="empty", engine=self.name, languages=OCR_LANGUAGES, text=None)
        text = "\n".join(fragments)[:OCR_TEXT_MAX_CHARS]
        mean_confidence = round(sum(confidences) / len(confidences), 4)
        status = "completed" if mean_confidence >= OCR_MIN_MEAN_CONFIDENCE else "low_confidence"
        return OcrOutcome(
            status=status,
            engine=self.name,
            languages=OCR_LANGUAGES,
            text=text,
            mean_confidence=mean_confidence,
        )


@dataclass
class StubOcrEngine(OcrEngine):
    """Test double: maps filename substrings to fixed OCR text."""

    texts: dict[str, str]
    confidence: float = 0.9
    unavailable: bool = False

    @property
    def name(self) -> str:
        return "stub-ocr"

    @property
    def available(self) -> bool:
        return not self.unavailable

    def read(self, path: Path) -> OcrOutcome:
        if self.unavailable:
            return OcrOutcome(status="unavailable", failure_reason="stub disabled")
        for key, value in sorted(self.texts.items()):
            if key in path.name:
                return OcrOutcome(
                    status="completed",
                    engine=self.name,
                    languages=OCR_LANGUAGES,
                    text=value,
                    mean_confidence=self.confidence,
                )
        return OcrOutcome(status="empty", engine=self.name, languages=OCR_LANGUAGES)


def eligible_for_ocr(width_px: int | None, height_px: int | None) -> bool:
    return (
        width_px is not None
        and height_px is not None
        and width_px >= OCR_MIN_SIDE_PX
        and height_px >= OCR_MIN_SIDE_PX
    )


class _DisabledOcrEngine(OcrEngine):
    """Explicit degraded state (tests, lean deployments): never loads weights."""

    @property
    def name(self) -> str:
        return "easyocr"

    @property
    def available(self) -> bool:
        return False

    def read(self, path: Path) -> OcrOutcome:
        return OcrOutcome(
            status="unavailable",
            failure_reason="disabled via environment (DALEL_P5_DISABLE_OCR)",
        )


_ENGINE_LOCK = threading.Lock()
_ENGINE: OcrEngine | None = None


def get_default_engine() -> OcrEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            if os.environ.get(DISABLE_OCR_ENV_VAR, "").strip() in {"1", "true", "yes"}:
                _ENGINE = _DisabledOcrEngine()
            else:
                _ENGINE = EasyOcrEngine()
        return _ENGINE


def reset_default_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None
