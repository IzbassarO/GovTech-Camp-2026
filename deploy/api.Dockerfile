# Lean DÁLEL Eco demo API image.
#
# Deliberately does NOT install the heavy ingestion dependencies
# (docling, easyocr/torch, pymupdf): the read-only API imports none of
# them. Build context is the REPOSITORY ROOT:
#   docker build -f deploy/api.Dockerfile -t dalel-api .
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.29" \
    "pydantic>=2.7"

# Application code only (pillar parser modules are copied but never imported
# by the API). The accepted, read-only artifacts (data/curated, data/results)
# are NOT baked into the image — they are excluded by .dockerignore and
# MOUNTED read-only at runtime (see docker-compose.demo.yml) so no accepted
# analysis output ever enters a distributable image layer.
COPY src/dalel /app/src/dalel

ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    DALEL_DATA_DIR=/app/data \
    DALEL_API_CORS_ORIGINS=http://localhost:3000

EXPOSE 8000

CMD ["uvicorn", "dalel.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
