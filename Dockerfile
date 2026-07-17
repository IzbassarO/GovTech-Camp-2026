# DÁLEL Eco — prepared replay + live-analysis API image with P5 vision support.
#
# Build context is the repository root (see compose.yaml):
#   docker compose up --build
#
# The image installs the locked `api` + `p5` dependency groups from uv.lock:
# FastAPI/uvicorn, the lightweight live parsers (PyMuPDF, python-docx,
# Pillow, multipart) plus the P5 multimodal stack — OpenCLIP with CPU-only
# torch wheels (pinned to the pytorch-cpu index for linux in uv.lock; CUDA
# wheels are never pulled) and EasyOCR. Docling stays excluded: live jobs
# parse via the PyMuPDF/python-docx fallback.
#
# Model weights are NOT baked into the image. On the first live P5 run the
# OpenCLIP multilingual weights (~1.1 GB) download into the HF cache volume
# and EasyOCR weights (~100 MB) into its cache volume (see compose.yaml);
# afterwards start-up is fully offline. Without weights and without network,
# P5 degrades to an explicit model-unavailable state and never blocks
# P1–P4 or Meta. Set DALEL_P5_DISABLE_MODEL=1 / DALEL_P5_DISABLE_OCR=1 for a
# deliberately lean deployment.
#
# Accepted artifacts (data/curated, data/results, data/annotations) are NOT
# baked into the image: compose mounts them read-only at runtime, so no
# accepted analysis output enters a distributable image layer.
FROM python:3.12-slim

# Pinned uv for reproducible, lockfile-driven installs (matches the uv 0.11
# line that produced uv.lock, revision 3).
RUN pip install --no-cache-dir uv==0.11.28

# Non-root runtime user.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app \
    && chown app:app /app

WORKDIR /app
USER app

# Dependencies first, in their own cached layer. --only-group installs just
# the locked serving + vision dependencies; the project itself (and with it
# the docling ingestion stack) is deliberately not installed — the package is
# imported from source via PYTHONPATH below.
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group api --only-group p5 --no-cache

# Application code only; artifacts are runtime mounts (compose.yaml).
COPY --chown=app:app src ./src

# Mount points for the read-only artifact volumes.
RUN mkdir -p data/curated data/results data/annotations

# Model cache mount points, owned by the runtime user so the named volumes
# inherit writable ownership on first use.
RUN mkdir -p /home/app/.cache/huggingface /home/app/.EasyOCR

# Isolated live-job root. Compose replaces it with an ephemeral tmpfs; this
# image-level directory also makes direct `docker run` secure and writable by
# the non-root process.
RUN mkdir -p /tmp/dalel-live-jobs && chmod 700 /tmp/dalel-live-jobs

# UV_NO_SYNC keeps `uv run` from trying to re-sync (and thus install the
# full ingestion project) at container start: it must only use the venv
# prepared above. HF_HOME pins the OpenCLIP weight cache to the volume.
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_SYNC=1 \
    DALEL_DATA_DIR=/app/data \
    DALEL_LIVE_JOB_DIR=/tmp/dalel-live-jobs \
    HF_HOME=/home/app/.cache/huggingface

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "dalel.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
