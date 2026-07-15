# Demo Website — BizAI / Dalel

A read-only demo site visualizing the accepted analysis results
(P1 / P2 / P3) over the curated dataset. It re-runs nothing: it normalizes
the on-disk artifacts into a stable API and renders them.

## Architecture

```
data/curated/v1, data/results/{p1,p2,p3}/v1   (accepted artifacts, read-only)
        │
        ▼
src/dalel/api/            FastAPI (offline, no DB, no LLM)
  repository.py           loads + caches artifacts (dicts only, no paths leak)
  services.py             normalizes artifacts → stable pillar contracts
  routes/                 health, projects, findings, reports, system
        │  HTTP (JSON)  + CORS
        ▼
frontend/                 Next.js 15 App Router (TypeScript, Tailwind)
  never reads files directly — only the API
```

Future pillars (P4/P5/P6, integrated meta-risk) plug in at the **service
layer** via the generic `PillarSummary` contract without changing the API
shape or the frontend. Reserved fields (`calibrated_risk`, `model_score`,
`shap_contributions`, `graph`, `map`, `provider`) exist in the contract as
`null` and are never fabricated.

## API endpoints

| Method | Path                                          | Purpose                         |
| ------ | --------------------------------------------- | ------------------------------- |
| GET    | `/api/health`                                 | Readiness + available pillars   |
| GET    | `/api/projects`                               | Project list with counts        |
| GET    | `/api/projects/{id}`                          | Project detail + documents      |
| GET    | `/api/projects/{id}/summary`                  | Pillar summaries + reserved      |
| GET    | `/api/projects/{id}/pillars`                  | Pillar summaries only            |
| GET    | `/api/projects/{id}/documents`                | Documents with finding counts   |
| GET    | `/api/projects/{id}/findings`                 | Filterable findings + filters   |
| GET    | `/api/projects/{id}/findings/{finding_id}`    | Finding detail + evidence        |
| GET    | `/api/projects/{id}/reports/{pillar}`         | Synthesized per-pillar markdown |
| GET    | `/api/system/metrics`                         | Aggregate metrics                |

Findings filters (query params): `pillar`, `severity`, `finding_type`,
`document_id`, `search`. Unknown project/finding/pillar IDs return clean
JSON `{error, detail}` with a 4xx status — never a traceback or a path.
Interactive docs at `/api/docs`.

## Local startup

```bash
# Terminal 1 — API (repository root)
uv run uvicorn dalel.api.app:app --reload --port 8000
#   or: make api

# Terminal 2 — frontend
cd frontend && npm install && npm run dev
#   or: make web-install && make web
```

Open http://localhost:3000. The API is at http://localhost:8000
(`/api/docs` for OpenAPI). Everything is offline; no API key is needed.

### If port 8000 is occupied

`NEXT_PUBLIC_API_BASE_URL` is configurable — never hardcode a port. If an
unrelated local service already uses port 8000, run the API on another
port and point the frontend at it (the frontend reads the env at dev-time):

```bash
# Terminal 1 — API on an alternative port
uv run uvicorn dalel.api.app:app --reload --port 8011

# Terminal 2 — frontend pointed at that port
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8011 npm run dev
```

If the frontend shows «API Dalel недоступен или указан неверный адрес
сервера», the backend is not running at `NEXT_PUBLIC_API_BASE_URL` or that
port is answered by a different service — start the API and/or correct the
URL. The message intentionally names the configured address; genuine API
errors are still shown verbatim.

## Deployment (prepared, not executed)

Minimal, correct Docker assets live in `deploy/`:

```bash
docker compose -f deploy/docker-compose.demo.yml up --build
# API → :8000, web → :3000
```

- `deploy/api.Dockerfile` — lean Python image; installs only
  fastapi/uvicorn/pydantic (no docling/torch). The accepted, read-only
  artifacts are **not baked into the image** — they are excluded by
  `.dockerignore` and mounted read-only at runtime by the compose file, so
  no accepted analysis output enters a distributable layer.
- `deploy/web.Dockerfile` — Next.js standalone; set
  `--build-arg NEXT_PUBLIC_API_BASE_URL=...` to the browser-facing API URL.
- `.dockerignore` excludes all `.env`/`.env.*` files (keeping
  `.env.example`), `node_modules`, `.next`, VCS/dev caches, source PDFs/DOCX
  and curated/results/annotations data from the build context.

## Data honesty

- **P2** is a synthetic demonstration corpus. Every P2 surface shows
  «Демонстрационный нормативный корпус. Не является официальным источником
  права.» The UI never states legal compliance or non-compliance.
- **P3** currently has zero proven contradictions. The UI shows a careful
  positive empty state («Доказанных числовых противоречий не обнаружено»)
  and explains that low-context comparisons were excluded — it never
  presents zero findings as proof the documents are correct.
- **No integrated risk score** is shown. The dashboard and project pages
  display «Интегральный риск — следующий этап» instead of a fabricated
  number.
- P1 findings are review priorities, not administrative conclusions.
