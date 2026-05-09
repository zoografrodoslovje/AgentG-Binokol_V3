FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md MANIFEST.in ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

COPY . .

RUN mkdir -p .devin_agent/memory logs cache FINISHED_WORK

EXPOSE 7860

ENV HOST=0.0.0.0
ENV MODEL_WARMUP_ENABLED=false
ENV PYTHONUNBUFFERED=1
ENV OLLAMA_HOST=http://localhost:11434
ENV OFFLINE_QUEUE_ENABLED=false
ENV OFFLINE_QUEUE_REQUESTS=false

CMD ["uvicorn", "agent_joko.dashboard.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860"]
