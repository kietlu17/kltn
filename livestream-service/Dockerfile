FROM node:20-alpine

WORKDIR /app

COPY livestream-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY livestream-service/ ./

EXPOSE 3014

CMD ["node", "server.js"]
