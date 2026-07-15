# DÁLEL Eco demo frontend (Next.js standalone).
#
# Build context is the REPOSITORY ROOT:
#   docker build -f deploy/web.Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 \
#     -t dalel-web .
#
# NEXT_PUBLIC_* is inlined at BUILD time — set it to the URL the browser
# will use to reach the API.
FROM node:20-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
