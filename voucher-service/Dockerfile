FROM node:20-alpine

WORKDIR /app

COPY voucher-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY voucher-service/ ./

EXPOSE 3013

CMD ["node", "server.js"]
