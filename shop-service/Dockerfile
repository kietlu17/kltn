FROM node:20-alpine

WORKDIR /app

COPY shop-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY shop-service/ ./

EXPOSE 3003

CMD ["node", "server.js"]
