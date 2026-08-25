FROM node:20-bookworm-slim

WORKDIR /app

COPY ai-cohost-service/package*.json ./
RUN npm install --omit=dev

COPY ai-cohost-service/src ./src

CMD ["npm", "start"]
