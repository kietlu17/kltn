FROM node:20-alpine

WORKDIR /app

COPY cart-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY cart-service/ ./

EXPOSE 3005

CMD ["node", "server.js"]
