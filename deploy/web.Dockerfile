FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin API: Caddy proxies the API routes, so no base URL is baked in.
ARG VITE_ASSISTANT_IMAGE=true
ARG VITE_ASSISTANT_VOICE=false
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
