FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY ["agentic rag/requirements.txt", "/tmp/requirements.txt"]
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY ["agentic rag/app", "/app/app"]
RUN mkdir -p /data

EXPOSE 3030
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3030"]

