.PHONY: setup lint format-check typecheck test test-integration qa validate-manifest inspect validate-foundation smoke-digital smoke-ocr ingest-bereke

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
