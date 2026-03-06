# Multi-stage build for minimal image size
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# Install package
RUN uv pip install --system .

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/deribit-data /usr/local/bin/deribit-data
COPY scripts /app/scripts

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /data /checkpoints && \
    chmod +x /app/scripts/run-sync-with-notify.sh && \
    chown -R appuser:appuser /data /checkpoints /app/scripts

USER appuser

# Default environment
ENV DERIBIT_CATALOG_PATH=/data/deribit_options
ENV DERIBIT_CHECKPOINT_DIR=/checkpoints

ENTRYPOINT ["deribit-data"]
CMD ["--help"]
