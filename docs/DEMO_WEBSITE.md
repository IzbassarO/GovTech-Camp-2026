# Demo Website — BizAI / Dalel

A read-only demo site visualizing the accepted analysis results
(P1 / P2 / P3 / P4) over the curated dataset. It re-runs nothing: it
normalizes the on-disk artifacts into a stable API and renders them.

`/analyze` adds two **strictly separated** product modes on top of that
read-only base — see [Two analysis modes](#two-analysis-modes-prepared-replay--live-analysis)
below:

- **Демонстрация Bayterek** — an immutable prepared replay of the accepted
  Bayterek results (nothing is uploaded, nothing is recomputed);
- **Анализ нового проекта** — genuine live analysis: real file bytes are
  uploaded into an isolated, token-protected temporary job and the actual
  P0/P0.5 preparation plus the accepted P1–P4/Meta pipelines run on them.

**P4 · Cross-Document Coherence and Entity Graph** is implemented: it checks
whether the documents in one project package describe the same project,
operator, facility, location, activity and reporting context consistently, and
builds a provenance-preserving entity graph. P4 is deterministic and is NOT a
spatial, visual or geospatial analysis — those belong to the later P5/P6 phases
(integrated meta-risk is a future META step). The accepted production corpus
yields zero *proven* cross-document contradictions; this is the honest,
conservative result and never a claim that the documents are correct.

## Architecture

```
data/curated/v1, data/results/{p1,p2,p3,p4}/v1   (accepted artifacts, read-only)
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

Future pillars (P5/P6 spatial & geospatial analysis, integrated meta-risk) plug
in at the **service layer** via the generic `PillarSummary` contract without
changing the API shape or the frontend. Reserved fields (`calibrated_risk`,
`model_score`, `shap_contributions`, `map`, `provider`) exist in the contract as
`null` and are never fabricated; P4 populates `graph` with its coherence view.

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
| GET    | `/api/demo/package-schema`                    | Canonical dossier section definitions |
| GET    | `/api/demo/manifest`                          | Prepared dossier with reconciled per-file states |
| POST   | `/api/demo/jobs`                              | Create an immutable prepared-replay job (`{"mode": "prepared_replay"}` only) |
| GET    | `/api/demo/jobs/{job_id}`                     | Fetch a replay job (requires `X-Dalel-Job-Token`) |
| GET    | `/api/live/package-schema`                    | Live dossier sections + upload limits |
| POST   | `/api/live/jobs`                              | Multipart upload of real file bytes → isolated live job (202) |
| GET    | `/api/live/jobs/{job_id}`                     | Live job state + result (requires `X-Dalel-Job-Token`) |
| GET    | `/api/live/jobs/{job_id}/events`              | Backend progress events (requires `X-Dalel-Job-Token`) |
| DELETE | `/api/live/jobs/{job_id}`                     | Cancel the job and delete its temporary files |

Job access tokens travel only in the `X-Dalel-Job-Token` header — never in
URLs. A missing or wrong token is indistinguishable from a missing job
(same 404 body), so unauthenticated requests can not even confirm a job
exists, let alone read its filenames.

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
# Terminal 1 — API on an alternative port (8011 occupied too? use 8012, etc.)
uv run uvicorn dalel.api.app:app --reload --port 8011

# Terminal 2 — frontend pointed at that port
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8011 npm run dev
```

If the frontend shows «API Dalel недоступен или указан неверный адрес
сервера», the backend is not running at `NEXT_PUBLIC_API_BASE_URL` or that
port is answered by a different service — start the API and/or correct the
URL. The message intentionally names the configured address; genuine API
errors are still shown verbatim. This applies to `/analyze` too: it talks
to the same API over the same configured base URL, nothing extra to set up.

## Two analysis modes (prepared replay + live analysis)

`/analyze` shows two clearly separated product cards. The modes never share
data, controls, jobs, or results.

### Mode A — «Демонстрация Bayterek» (immutable prepared replay)

`/analyze/demo` is a read-only walkthrough of the accepted Bayterek
analysis. It is explicitly labelled a replay and states persistently:

> «Демонстрационный запуск воспроизводит ранее рассчитанные результаты
> подготовленного проекта Bayterek.»

- The screen shows the FULL registered official package from the versioned
  prepared manifest (`src/dalel/api/demo_manifests/project_003_bayterek.json`,
  served reconciled by `GET /api/demo/manifest`): 7 officially registered
  materials (3 project PDFs, newspaper page, 2 notice-board photos, protocol
  RAR) plus 2 protocol PDFs extracted from the archive. Every file carries an
  honest, **computed** state (`analyzed` / `supporting_only` / `extracted` /
  `official_only` / …) reconciled against the curated dataset and the accepted
  P1–P4/Meta artifacts; the UI distinguishes the official source package, the
  local raw copy and the analyzed subset (2 curated documents). Display names
  are safe: source filenames containing a private individual's surname are
  never exposed, and no personal contact data or BIN enters the manifest.
- The prepared package is **immutable**: no upload controls, no deletion, no
  section reassignment anywhere in this mode. The backend enforces the same
  boundary — `POST /api/demo/jobs` accepts exactly
  `{"mode": "prepared_replay"}` (`extra="forbid"`); legacy `sections` /
  `selected_files` payloads, uploaded bytes and custom project ids are
  rejected with 422 and are covered by regression tests.
- «Запустить демонстрацию Bayterek» creates the replay job synchronously
  from the accepted artifacts via the same normalized service-layer builders
  the rest of the API uses (`build_pillar_summary`, `build_meta_assessment`) —
  the backend hardcodes stage order and status copy, never a score, count or
  ranking. Replay jobs live in a bounded, token-protected in-memory store
  (random 256-bit job id + independent access token; only the token digest is
  retained).
- The replay pipeline animation (P0 → P0.5 → P1–P4 → Meta) is client-side
  cinematic timing — allowed here precisely because the page states it is a
  replay of already-computed results, and every displayed number is
  artifact-backed.

### Mode B — «Анализ нового проекта» (genuine live analysis)

`/analyze/live` uploads **actual file bytes** (multipart) and runs the real
pipeline inside an isolated temporary workspace. Nothing about Bayterek is
ever used or shown in this mode.

- **Intake** (`POST /api/live/jobs`): per-file and total size limits,
  zero-byte rejection, extension + declared-MIME + magic-byte validation,
  filename sanitization with path-traversal rejection, duplicate detection
  by content hash, internally generated storage names. Uploads are written
  only into the per-job workspace (`0700`, under `DALEL_LIVE_JOB_DIR`) —
  never into `data/raw|curated|results|annotations`.
- **Security**: cryptographically random job id + independent access token
  (`X-Dalel-Job-Token` header, never a URL parameter); only the token's
  SHA-256 digest is stored; wrong token ≡ missing job (identical 404);
  bounded active jobs; TTL expiry with workspace cleanup; cancellation via
  DELETE removes the temporary files; tokens and user filenames never reach
  logs.
- **P0 (validating)** re-verifies the received package inside the worker:
  hashes, sizes, signatures, section assignment, duplicate references and
  safe ZIP extraction (traversal/symlink/encrypted/nested rejection, entry
  count, expanded-size and compression-ratio limits). RAR archives are
  registered honestly as `extraction_unsupported` — never analyzed, never
  reported as extracted.
- **P0.5 (preparing)** runs the real dependency-light ingestion
  (`parser_policy="lightweight"`: PyMuPDF / python-docx, honest OCR
  degradation without claiming OCR ran), extracts pages/sections/tables and
  embedded images, then builds a job-local Curated-Dataset-v1-compatible
  dataset. A deterministic **visual asset inventory** is also produced:
  exact SHA-256 and conservative dHash near-duplicate clustering, generic
  repeated-text-header detection (wide/short rasters recurring across
  pages/documents — e.g. a scanned applicant-name line — become one cluster
  with one representative), small-logo/stamp/QR flags, and an optional
  review-template seed (`review_template.jsonl`) for future expert
  correction. Visual triage stays `visual_analysis_status="not_available"`,
  feeds nothing into P1–P4 or Meta, and deletes nothing.
- **P1–P4** run the accepted pipelines unchanged against the job-local
  dataset, each followed by its independent output validator. Every pillar
  returns one of `completed` / `insufficient_input` / `unavailable` /
  `failed`; missing input is *never* replaced with Bayterek artifacts.
- **Meta** runs only over this job's validated pillar outputs. Missing
  pillars reduce coverage/confidence and are never treated as low risk. No
  calibrated probability and no SHAP (no expert-labelled model exists).
- **Progress is backend-driven**: the worker emits state events
  (`validating → preparing → running_p1 … running_meta → completed/failed/
  cancelled/expired`) with progress, current operation, metrics, warnings
  and limitations; `/analyze/live/[jobId]` polls the job + events endpoints
  and never marks a stage complete before the backend does (the UI only
  smooths transitions).

### Recording flow (replay mode)

1. Open `/analyze` and show the two separated mode cards.
2. Open «Демонстрация Bayterek» — the full registered package appears
   grouped by section, read-only, with the replay disclaimer visible.
3. Explain the three scopes on the completeness summary: official source
   materials vs locally available vs the analyzed subset (2 documents);
   official-only materials stay visible as «нет локальной копии».
4. Click **«Запустить демонстрацию Bayterek»** and watch P0 → P0.5 →
   P1–P4 → Meta animate in order; each pillar shows its input, operation
   and artifact-backed output.
5. Point out the P2 synthetic-corpus warning and the honest P3/P4
   zero-conflict wording as they appear.
6. On the Meta stage / result screen, point out the score, evidence
   coverage and assessment confidence are three separate numbers, and read
   the "not a probability of violation" notice and the analyzed-subset
   scope note.
7. Open the coverage matrix (документ → пиллары) and the public-feedback
   card (22 вопроса зарегистрированы, в анализ пока не входят).
8. Click **«Открыть полный результат»** to land on the real Bayterek
   project page and continue into findings/evidence as usual.
9. Optionally return to `/analyze`, open «Анализ нового проекта», upload a
   real PDF/DOCX package and show the backend-driven live pipeline with its
   honest per-pillar states and live Meta.

## Deployment — Docker Compose (one command)

The whole demo stack starts from the **repository root** (requires a
running [Docker Desktop](https://www.docker.com/products/docker-desktop/)):

```bash
docker compose up --build
```

| Service    | URL                                            |
| ---------- | ---------------------------------------------- |
| Frontend   | http://localhost:3000 (mode selection: `/analyze`) |
| API        | http://localhost:8000                          |
| API health | http://localhost:8000/api/health               |
| API docs   | http://localhost:8000/api/docs                 |

Day-to-day commands:

```bash
docker compose down        # stop and remove the containers
docker compose logs -f     # follow logs of both services
docker compose ps          # service status + health
docker compose up --build  # rebuild after code changes
```

How it fits together (`compose.yaml` at the repository root):

- **`Dockerfile` (API)** — `python:3.12-slim` + pinned `uv`; installs only
  the locked `api` dependency group from `uv.lock` (fastapi/uvicorn — no
  docling/torch/pymupdf), runs
  `uv run uvicorn dalel.api.app:app --host 0.0.0.0 --port 8000` as a
  non-root user with a `/api/health` health check.
- **`frontend/Dockerfile`** — multi-stage Next.js standalone production
  build (`npm ci` against the committed lockfile).
  `NEXT_PUBLIC_API_BASE_URL` is inlined into the client bundle at **build**
  time via the compose build arg and points at `http://localhost:8000` —
  the URL the **browser** uses, never the compose-internal
  `http://api:8000` (a browser outside Docker cannot resolve compose
  service names).
- The frontend waits for the API health check
  (`depends_on: condition: service_healthy`), so the first page load never
  races a still-starting API.
- **Accepted local artifacts are mounted read-only, never baked into an
  image**: `data/curated/`, `data/results/` and `data/annotations/` must
  exist locally. `data/annotations` is genuinely required — the Meta
  replay validation reads the expert review templates, and without it META
  reports unavailable. Creating demo jobs never mutates the mounts (jobs
  are in-memory only).
- `.dockerignore` / `frontend/.dockerignore` keep `.env*` (except
  `.env.example`), `node_modules`, `.next`, VCS/dev caches, notebooks and
  every private PDF/DOCX (`docs/`, `data/raw/`) out of the build context —
  no private document can enter an image layer.
- Ports are fixed at 3000/8000 (the frontend bundle is built for
  `http://localhost:8000`). If a port is taken, find and stop the occupant
  instead of switching ports:

  ```bash
  lsof -nP -iTCP:3000 -sTCP:LISTEN
  lsof -nP -iTCP:8000 -sTCP:LISTEN
  ```

- **Mode boundary in Docker**: the replay mode never reads uploaded
  content, and the live mode confines every upload to the container-private
  tmpfs at `DALEL_LIVE_JOB_DIR` (`0700`, `noexec`, sized, destroyed with the
  container). The accepted artifact mounts are read-only, so neither mode
  can mutate accepted analysis outputs (see the two-modes section above).

The older assets in `deploy/` (`docker-compose.demo.yml`,
`api.Dockerfile`, `web.Dockerfile`) predate the root `compose.yaml` and are
superseded by it; the root file is the supported entry point.

## Data honesty

- **P2** is a synthetic demonstration corpus. Every P2 surface shows
  «Демонстрационный нормативный корпус. Не является официальным источником
  права.» The UI never states legal compliance or non-compliance.
- **P3** currently has zero proven contradictions. The UI shows a careful
  positive empty state («Доказанных числовых противоречий не обнаружено»)
  and explains that low-context comparisons were excluded — it never
  presents zero findings as proof the documents are correct.
- **Meta · Integrated Review Priority Score** combines the accepted P1–P4
  evidence into a transparent, deterministic 0–100 score. The UI always
  shows it next to its evidence coverage and assessment confidence — never
  as a bare number — and states «Это приоритет экспертной проверки, а не
  вероятность нарушения.» Calibrated probability and SHAP values are never
  fabricated; the UI shows «Калибровка недоступна без достаточной
  экспертной разметки» instead.
- P1 findings are review priorities, not administrative conclusions.
- **`/analyze`** separates the two modes explicitly. The Bayterek
  demonstration is labelled a replay of previously computed results and its
  disclaimer stays visible while a demo job runs; it never claims uploaded
  files were analyzed. The live mode analyzes only what was actually
  uploaded, reports unavailable or insufficient-input pillars honestly, and
  never displays Bayterek evidence, findings or scores.
