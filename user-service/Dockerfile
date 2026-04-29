FROM node:20-alpine

WORKDIR /app

COPY user-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY user-service/ ./

EXPOSE 3002

CMD ["node", "server.js"]
