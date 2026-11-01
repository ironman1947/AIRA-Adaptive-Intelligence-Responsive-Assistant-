# ==============================================================================
# PROJECT AIRA (Adaptive Intelligence & Responsive Assistant) Containerfile
# ==============================================================================
FROM python:3.11-slim

# System dependencies including curl for container health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create non-root aira user
RUN useradd -m -u 1000 -s /bin/bash aira
WORKDIR /app

# Copy project specification and code
COPY pyproject.toml README.md .env.example ./
COPY src/ ./src/
COPY frontend.py ./

# Install aira with UI extras
RUN pip install --no-cache-dir -e ".[ui]"

# Ensure aira user owns /app
RUN chown -R aira:aira /app

# Switch to non-root user
USER aira

# Expose ports: 8000 (FastAPI backend) and 8501 (Streamlit UI)
EXPOSE 8000 8501

# Container health check hitting FastAPI /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start FastAPI backend on port 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
