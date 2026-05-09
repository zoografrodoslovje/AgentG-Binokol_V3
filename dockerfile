FROM python:3.10-slim

WORKDIR /app

# System deps for lxml, pandas
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime data directories
RUN mkdir -p .devin_agent/memory logs cache FINISHED_WORK

EXPOSE 7860

ENV HOST=0.0.0.0
ENV MODEL_WARMUP_ENABLED=false
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "agent_joko.dashboard.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860"]
