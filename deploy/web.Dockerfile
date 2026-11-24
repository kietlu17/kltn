# Public HTTPS entry point for the API. The frontend lives on Vercel.
FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
