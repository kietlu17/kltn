FROM node:20-alpine

WORKDIR /app

COPY wallet-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY wallet-service/ ./

EXPOSE 3011

CMD ["node", "server.js"]
