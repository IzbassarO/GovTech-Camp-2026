# Dalel — Demo Website (BizAI)

Frontend for the DÁLEL Eco demo: visualizes the accepted **P1 Document
Integrity**, **P2 Regulatory Compliance (demo)** and **P3 Quantitative
Consistency** results. Read-only, Russian-language UI, evidence-first.

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
  demo-corpus notice; P3 shows an honest positive empty state.
