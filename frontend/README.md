# Dalel — Demo Website (BizAI)

Frontend for the DÁLEL Eco demo: visualizes the accepted **P1 Document
Integrity**, **P2 Regulatory Compliance (demo)**, **P3 Quantitative
Consistency**, **P4 Cross-Document Coherence**, and deterministic **Meta Review
Priority** results. Read-only, Russian-language UI, evidence-first.

`/analyze` offers two strictly separated modes. **Демонстрация Bayterek**
(`/analyze/demo`) is an immutable prepared replay: nothing is uploaded and
every stage's metrics come from the accepted artifacts of the configured
demo project. **Анализ нового проекта** (`/analyze/live`) uploads real file
bytes (multipart) into an isolated token-protected job, drives the pipeline
UI from backend progress events, and shows honest per-pillar availability —
never Bayterek data. See `docs/DEMO_WEBSITE.md#two-analysis-modes-prepared-replay--live-analysis`
for the full honesty rationale and recording flow.

- Next.js 15 (App Router) · TypeScript (strict) · Tailwind CSS
- No database, no auth, no LLM calls. Talks to the FastAPI layer over HTTP.

## Local development

The frontend reads the API base URL from `NEXT_PUBLIC_API_BASE_URL`
(default `http://localhost:8000`).

```bash
# 1) Backend API (from the repository root, in another terminal)
uv run uvicorn dalel.api.app:app --reload --port 8000

# 2) Frontend
cd frontend
cp .env.example .env.local        # optional; default already points at :8000
npm install
npm run dev                       # http://localhost:3000
```

## Docker (one command)

From the **repository root** (requires Docker Desktop):

```bash
docker compose up --build
```

Frontend → http://localhost:3000, API → http://localhost:8000.
`frontend/Dockerfile` is a multi-stage standalone production build;
`NEXT_PUBLIC_API_BASE_URL` is inlined at **build** time from the compose
build arg and points at `http://localhost:8000` — the URL the **browser**
uses to reach the API, never the compose-internal `http://api:8000`. Stop
with `docker compose down`; follow logs with
`docker compose logs -f frontend`. See `docs/DEMO_WEBSITE.md` for the full
stack documentation.

## Scripts

| Command             | Purpose                              |
| ------------------- | ------------------------------------ |
| `npm run dev`       | Dev server with hot reload           |
| `npm run build`     | Production build (standalone output) |
| `npm run start`     | Serve the production build           |
| `npm run lint`      | ESLint (`next lint`)                 |
| `npm run typecheck` | `tsc --noEmit`                       |

## Notes

- `NEXT_PUBLIC_API_BASE_URL` is inlined at **build** time for `next start`
  / Docker, and read at **runtime** for `npm run dev`.
- Pages fetch on the client with loading / empty / error states, so the
  demo works fully offline against a local API — no network required.
- The UI never claims legal compliance. P2 always shows the synthetic
  demo-corpus notice; Meta is explicitly a review order rather than a
  probability of violation. Calibration and SHAP stay unavailable until real
  expert labels are sufficient.
- `/analyze/demo` POSTs only `{"mode": "prepared_replay"}` to
  `/api/demo/jobs` — no file names, no file content — and the replay job is
  computed synchronously from accepted artifacts. `/analyze/live` POSTs the
  actual selected files as `multipart/form-data` to `/api/live/jobs`; the
  job token returns once in the creation response, is kept in
  `sessionStorage`, and is sent only via the `X-Dalel-Job-Token` header.
