FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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

# Run the server
CMD ["python", "server.py"]
