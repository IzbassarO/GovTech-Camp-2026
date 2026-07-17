# DÁLEL Eco — prepared replay + lightweight live-analysis API image.
#
# Build context is the repository root (see compose.yaml):
#   docker compose up --build
#
# The image installs ONLY the locked `api` dependency group from uv.lock:
# FastAPI/uvicorn plus the lightweight live parsers (PyMuPDF, python-docx,
# Pillow and multipart support). It deliberately excludes Docling,
# EasyOCR/Torch and model downloads. Accepted artifacts (data/curated,
# data/results, data/annotations) are NOT baked into the image: compose
# mounts them read-only at runtime, so no accepted analysis output enters
# a distributable image layer.
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

# Dependencies first, in their own cached layer. --only-group api installs
# just the locked web-serving dependencies; the project itself (and with it
# the docling/OCR stack) is deliberately not installed — the package is
# imported from source via PYTHONPATH below.
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group api --no-cache

# Application code only; artifacts are runtime mounts (compose.yaml).
COPY --chown=app:app src ./src

# Mount points for the read-only artifact volumes.
RUN mkdir -p data/curated data/results data/annotations

# Isolated live-job root. Compose replaces it with an ephemeral tmpfs; this
# image-level directory also makes direct `docker run` secure and writable by
# the non-root process.
RUN mkdir -p /tmp/dalel-live-jobs && chmod 700 /tmp/dalel-live-jobs

# UV_NO_SYNC keeps `uv run` from trying to re-sync (and thus install the
# full ingestion project) at container start: it must only use the venv
# prepared above.
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_SYNC=1 \
    DALEL_DATA_DIR=/app/data \
    DALEL_LIVE_JOB_DIR=/tmp/dalel-live-jobs

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "dalel.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
