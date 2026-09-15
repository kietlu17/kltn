FROM python:3.12-slim

WORKDIR /app

COPY ai-cohost-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ai-cohost-service/src ./src

CMD ["python", "src/main.py", "start"]
