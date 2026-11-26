# Enterprise Knowledge Assistant - Dockerfile
# -------------------------------------------
# Multi-stage build for optimized image size
#
# Build stage: Install dependencies
# Runtime stage: Copy only what's needed
#
# Usage:
#   docker build -t eka .
#   docker run -p 8000:8000 eka
#
# Override command for Celery worker:
#   docker run eka celery -A app.core.celery:celery_app worker --loglevel=info

# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create uploads directory
RUN mkdir -p /app/uploads

# Expose port
EXPOSE 8000

# Default command (API server)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
