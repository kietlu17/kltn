FROM node:20-alpine

WORKDIR /app

COPY inventory-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY inventory-service/ ./

EXPOSE 3007

CMD ["node", "server.js"]
