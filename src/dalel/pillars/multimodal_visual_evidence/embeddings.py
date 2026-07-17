"""Vision-language embedding backend for P5 (OpenCLIP multilingual CLIP).

One pinned open-source encoder (``xlm-roberta-base-ViT-B-32`` /
``laion5b_s13b_b90k``): MIT-licensed, CPU inference, deterministic settings
(eval mode, no grad, fixed preprocessing, bounded batches). The model is
loaded at most once per process and degrades to an explicit ``unavailable``
state when the dependency or weights are missing — never a silent fallback.

Set ``DALEL_P5_DISABLE_MODEL=1`` to force the unavailable state (tests, lean
deployments). The Hugging Face cache honours ``HF_HOME``.
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dalel.pillars.multimodal_visual_evidence.config import (
    MODEL_DEVICE,
    MODEL_EMBEDDING_DIM,
    MODEL_IMAGE_BATCH_SIZE,
    MODEL_LICENSE,
    MODEL_NAME,
    MODEL_PRETRAINED_TAG,
    MODEL_TEXT_BATCH_SIZE,
)

DISABLE_ENV_VAR = "DALEL_P5_DISABLE_MODEL"


class VisualEmbeddingBackend(Protocol):
    """Deterministic image/text embedding provider."""

    @property
    def available(self) -> bool: ...

    @property
    def metadata(self) -> dict[str, Any]: ...

    def encode_images(self, paths: list[Path]) -> list[list[float] | None]: ...

    def encode_texts(self, texts: list[str]) -> list[list[float]]: ...


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


@dataclass
class UnavailableBackend:
    """Explicit degraded state: records WHY the model cannot run."""

    reason: str

    @property
    def available(self) -> bool:
        return False

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_name": MODEL_NAME,
            "pretrained_tag": MODEL_PRETRAINED_TAG,
            "license": MODEL_LICENSE,
            "device": MODEL_DEVICE,
            "embedding_dim": MODEL_EMBEDDING_DIM,
            "status": "unavailable",
            "status_reason": self.reason,
        }

    def encode_images(self, paths: list[Path]) -> list[list[float] | None]:
        return [None for _ in paths]

    def encode_texts(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class OpenClipBackend:
    """Multilingual OpenCLIP encoder, loaded once, CPU-only, eval mode."""

    def __init__(self) -> None:
        import open_clip
        import torch

        self._torch = torch
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=MODEL_PRETRAINED_TAG
        )
        model = model.to(MODEL_DEVICE)
        model.eval()
        self._model = model
        self._preprocess = preprocess
        self._tokenizer = open_clip.get_tokenizer(MODEL_NAME)
        self._open_clip_version = getattr(open_clip, "__version__", "unknown")
        self._torch_version = getattr(torch, "__version__", "unknown")

    @property
    def available(self) -> bool:
        return True

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_name": MODEL_NAME,
            "pretrained_tag": MODEL_PRETRAINED_TAG,
            "license": MODEL_LICENSE,
            "device": MODEL_DEVICE,
            "embedding_dim": MODEL_EMBEDDING_DIM,
            "status": "available",
            "status_reason": None,
            "open_clip_version": self._open_clip_version,
            "torch_version": self._torch_version,
        }

    def encode_images(self, paths: list[Path]) -> list[list[float] | None]:
        from PIL import Image

        torch = self._torch
        results: list[list[float] | None] = []
        batch_tensors: list[Any] = []
        batch_slots: list[int] = []

        def _flush() -> None:
            if not batch_tensors:
                return
            stacked = torch.stack(batch_tensors)
            with torch.no_grad():
                embeddings = self._model.encode_image(stacked)
            for slot, row in zip(batch_slots, embeddings, strict=True):
                results[slot] = [float(v) for v in row.tolist()]
            batch_tensors.clear()
            batch_slots.clear()

        for path in paths:
            results.append(None)
            slot = len(results) - 1
            try:
                with Image.open(path) as image:
                    tensor = self._preprocess(image.convert("RGB"))
            except Exception:
                continue
            batch_tensors.append(tensor)
            batch_slots.append(slot)
            if len(batch_tensors) >= MODEL_IMAGE_BATCH_SIZE:
                _flush()
        _flush()
        return results

    def encode_texts(self, texts: list[str]) -> list[list[float]]:
        torch = self._torch
        results: list[list[float]] = []
        for start in range(0, len(texts), MODEL_TEXT_BATCH_SIZE):
            batch = texts[start : start + MODEL_TEXT_BATCH_SIZE]
            tokens = self._tokenizer(batch)
            with torch.no_grad():
                embeddings = self._model.encode_text(tokens)
            results.extend([float(v) for v in row.tolist()] for row in embeddings)
        return results


@dataclass
class DeterministicStubBackend:
    """Test double: embeds by keyword lookup, fully deterministic, no torch.

    ``image_vectors`` maps a filename substring to a vector; ``text_vectors``
    maps a text substring to a vector. Unmatched inputs embed to the zero-ish
    ``default`` vector so similarity stays defined.
    """

    image_vectors: dict[str, list[float]] = field(default_factory=dict)
    text_vectors: dict[str, list[float]] = field(default_factory=dict)
    default: list[float] = field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0])
    fail_images: bool = False

    @property
    def available(self) -> bool:
        return True

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_name": "deterministic-stub",
            "pretrained_tag": "test",
            "license": "n/a",
            "device": "cpu",
            "embedding_dim": len(self.default),
            "status": "available",
            "status_reason": None,
        }

    def encode_images(self, paths: list[Path]) -> list[list[float] | None]:
        if self.fail_images:
            return [None for _ in paths]
        output: list[list[float] | None] = []
        for path in paths:
            name = path.name
            vector = next(
                (v for key, v in sorted(self.image_vectors.items()) if key in name),
                self.default,
            )
            output.append(list(vector))
        return output

    def encode_texts(self, texts: list[str]) -> list[list[float]]:
        output: list[list[float]] = []
        for text in texts:
            lowered = text.casefold()
            vector = next(
                (v for key, v in sorted(self.text_vectors.items()) if key in lowered),
                self.default,
            )
            output.append(list(vector))
        return output


_BACKEND_LOCK = threading.Lock()
_BACKEND: VisualEmbeddingBackend | None = None


def get_default_backend() -> VisualEmbeddingBackend:
    """Process-wide backend singleton with graceful degradation."""
    global _BACKEND
    with _BACKEND_LOCK:
        if _BACKEND is not None:
            return _BACKEND
        if os.environ.get(DISABLE_ENV_VAR, "").strip() in {"1", "true", "yes"}:
            _BACKEND = UnavailableBackend(
                reason="disabled via environment (DALEL_P5_DISABLE_MODEL)"
            )
            return _BACKEND
        try:
            _BACKEND = OpenClipBackend()
        except ImportError:
            _BACKEND = UnavailableBackend(reason="open_clip/torch dependency is not installed")
        except Exception as exc:  # missing weights, offline hub, corrupt cache
            _BACKEND = UnavailableBackend(
                reason=f"model weights could not be loaded ({type(exc).__name__})"
            )
        return _BACKEND


def reset_default_backend() -> None:
    """Testing hook: drop the cached backend."""
    global _BACKEND
    with _BACKEND_LOCK:
        _BACKEND = None
