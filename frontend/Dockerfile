# DÁLEL Eco — demo frontend (Next.js 15, standalone production build).
#
# Build context is frontend/ (see ../compose.yaml):
#   docker compose up --build
#
# NEXT_PUBLIC_* values are inlined into the client bundle at BUILD time —
# pass the URL the BROWSER uses to reach the API. For the local compose
# demo that is http://localhost:8000, never http://api:8000: the browser
# runs outside the compose network and cannot resolve service names.
FROM node:20-slim AS build
WORKDIR /app

# Deterministic install against the committed lockfile (dev dependencies
# included: `next build` runs TypeScript and ESLint).
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- runtime ------------------------------------------------------------
FROM node:20-slim AS run
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

# Standalone output: server.js plus the minimal node_modules subset.
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static

# node:20-slim ships a non-root `node` user.
USER node

EXPOSE 3000

CMD ["node", "server.js"]
