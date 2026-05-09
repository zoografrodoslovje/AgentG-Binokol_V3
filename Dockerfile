FROM python:3.10-slim

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy only the files needed for installation first to leverage Docker cache
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package and its dependencies
RUN pip install --no-cache-dir .

# Copy the rest of the application code
COPY . .

# Runtime data directories
RUN mkdir -p .devin_agent/memory logs cache FINISHED_WORK

EXPOSE 7860

ENV HOST=0.0.0.0
ENV MODEL_WARMUP_ENABLED=false
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["uvicorn", "agent_joko.dashboard.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860"]
