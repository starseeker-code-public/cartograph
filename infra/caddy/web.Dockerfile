# Build the SPA, serve it (plus the reverse proxy) from Caddy.
# Build context: repository root (see docker-compose.prod.yml).
FROM node:22-slim AS web-builder

WORKDIR /web
# npm ci only — falling back to npm install would silently unpin the lockfile.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ .
RUN npm run build

FROM caddy:2-alpine

COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web-builder /web/dist /srv/www
