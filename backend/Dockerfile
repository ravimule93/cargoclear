FROM python:3.12-slim

# Install system dependencies for pdf2image (Poppler)
# Phase 1: Add poppler-utils when PDF processing is enabled
RUN apt-get update && apt-get install -y --no-install-recommends \
    # poppler-utils \   # Phase 1: uncomment
    # libgl1 \          # Phase 1: uncomment (for OpenCV)
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Cloud Run expects the app to listen on PORT env var (default 8080)
ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
