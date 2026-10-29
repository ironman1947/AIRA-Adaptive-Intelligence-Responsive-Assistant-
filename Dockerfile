# ==============================================================================
# PROJECT AIRA (Adaptive Intelligence & Responsive Assistant) Containerfile
# ==============================================================================
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and project files
COPY pyproject.toml README.md .env.example ./
COPY src/ ./src/
COPY frontend.py ./

# Install python dependencies
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir uvicorn fastapi streamlit beautifulsoup4 pypdf python-docx duckduckgo-search scikit-learn numpy httpx

# Expose ports: 8080 (FastAPI backend) and 8501 (Streamlit frontend)
EXPOSE 8080 8501

# Default command: start FastAPI backend
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
