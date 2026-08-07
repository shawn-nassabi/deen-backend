# Dockerfile
FROM python:3.11-slim

# System deps (optional, useful for some libs)
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Create user (non-root)
RUN useradd -m appuser
WORKDIR /app

# Install Python deps
# Copy your files — if you have a requirements.txt use that; else use pyproject
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the actual app
COPY . /app

# Generate BM25 encoder for fiqh retrieval (no Pinecone upload)
RUN python scripts/ingest_fiqh.py --encoder-only

# Switch to non-root
USER appuser

# Expose internal app port
EXPOSE 8000

# Start Gunicorn with Uvicorn workers (async ASGI — required by the DEE-36
# end-to-end async pipeline; plain sync gunicorn workers would break it).
# DEE-59: `-w 2` is load-bearing for the DB connection budget — each worker
# opens sync (2+1) + async (2+1) = 6 pooled connections; 2 workers = 12 of the
# 15-client Supabase session-mode cap. Recompute db/session.py +
# db/async_session.py pool sizes BEFORE changing the worker count.
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "main:app"]