FROM node:20-alpine

WORKDIR /app

COPY payment-gateway/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY payment-gateway/ ./

EXPOSE 3012

CMD ["node", "server.js"]
