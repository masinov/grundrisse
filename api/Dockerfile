FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy core package first (dependency)
COPY packages/core /packages/core
RUN pip install /packages/core

# Copy and install API package
COPY api/pyproject.toml api/README.md ./
COPY api/src ./src
RUN pip install -e .

# Expose port
EXPOSE 8000

# Run the API server
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
