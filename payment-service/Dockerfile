FROM node:20-alpine

WORKDIR /app

COPY payment-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY payment-service/ ./

EXPOSE 3010

CMD ["node", "server.js"]
