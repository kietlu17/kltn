FROM node:20-alpine

WORKDIR /app

COPY product-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY product-service/ ./

EXPOSE 3004

CMD ["node", "server.js"]
