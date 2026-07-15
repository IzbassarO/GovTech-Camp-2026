.PHONY: setup lint format-check typecheck test test-integration qa validate-manifest inspect validate-foundation smoke-digital smoke-ocr ingest-bereke api web web-install demo

setup:
	uv sync --dev

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src

test:
	uv run pytest

test-integration:
	uv run pytest -m integration

qa: lint format-check typecheck test validate-foundation

validate-manifest:
	uv run dalel validate-manifest --manifest data/manifests/projects.jsonl

inspect:
	uv run dalel inspect --manifest data/manifests/projects.jsonl

validate-foundation:
	python3 scripts/validate_dataset_foundation.py

# Smoke test D: one digital PDF from project_001_bereke
smoke-digital:
	uv run dalel ingest --manifest data/manifests/projects.jsonl \
		--document-id project_001_bereke__nontechnical_summary__001 --ocr auto

# Smoke test E: one OCR candidate (scanned action plan)
smoke-ocr:
	uv run dalel ingest --manifest data/manifests/projects.jsonl \
		--document-id project_001_bereke__action_plan__001 --ocr auto

ingest-bereke:
	uv run dalel ingest --manifest data/manifests/projects.jsonl \
		--project-id project_001_bereke --ocr auto

# --- Demo website (read-only API + Next.js frontend) -------------------------

# Terminal 1: start the read-only API (loads accepted P1/P2/P3 artifacts).
api:
	uv run uvicorn dalel.api.app:app --reload --port 8000

# One-time frontend dependency install.
web-install:
	cd frontend && npm install

# Terminal 2: start the frontend dev server (reads NEXT_PUBLIC_API_BASE_URL).
web:
	cd frontend && npm run dev

# Convenience: install frontend deps, then print the two-terminal demo steps.
demo: web-install
	@echo ""
	@echo "Demo ready. Use two terminals:"
	@echo "  1) make api      # http://localhost:8000  (API + /api/docs)"
	@echo "  2) make web      # http://localhost:3000  (frontend)"
