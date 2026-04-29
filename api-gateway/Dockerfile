FROM node:20-alpine

WORKDIR /app

COPY api-gateway/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY api-gateway/ ./

EXPOSE 3000

CMD ["node", "server.js"]
