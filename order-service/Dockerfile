FROM node:20-alpine

WORKDIR /app

COPY order-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY order-service/ ./

EXPOSE 3006

CMD ["node", "server.js"]
