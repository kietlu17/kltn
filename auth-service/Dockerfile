FROM node:20-alpine

WORKDIR /app

COPY auth-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY auth-service/ ./

EXPOSE 3001

CMD ["node", "server.js"]
