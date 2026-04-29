FROM node:20-alpine

WORKDIR /app

COPY review-service/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY review-service/ ./

EXPOSE 3008

CMD ["node", "server.js"]
