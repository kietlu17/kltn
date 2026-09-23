FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps torch==2.14.0+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install torch==2.14.0+cpu
COPY chatbot-service/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install --retries 5 -r requirements.txt
COPY chatbot-service/src ./src
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "3021", "--workers", "1"]
