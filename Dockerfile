FROM python:3.12-slim

WORKDIR /app

# Set environment variables for better container behavior and ARM compatibility
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Fix for ChromaDB/hnswlib build issues on ARM during cross-compilation
ENV HNSWLIB_NO_NATIVE=1
ENV PIP_DEFAULT_TIMEOUT=100

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    cmake \
    pkg-config \
    libsqlite3-dev \
    libssl-dev \
    libffi-dev \
    rustc \
    cargo \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy application code
COPY server.py .
COPY mempalace/ ./mempalace/
COPY dashboard/ ./dashboard/

# Configuration
ENV PORT_API=8000
ENV PORT_DASHBOARD=8080
ENV MEMPALACE_PALACE_PATH="/app/data/.mempalace"
# Ensure the submodule package can be found
ENV PYTHONPATH="/app/mempalace"

# Expose ports
EXPOSE 8000
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/ || exit 1

# Run the server
CMD ["python", "server.py"]
