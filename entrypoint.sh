#!/bin/sh
set -e

# entrypoint.sh — works on Railway AND Render (both supply PORT env var).
#
# Render free tier: 512 MB RAM.  sentence-transformers + FAISS load ~300 MB,
# so keep --workers 1 (or 2 at most).  Render will OOM-kill with more workers.
# Change to --workers 2 only if you upgrade to a paid Render plan (1 GB+).

echo "Running DB migrations..."
alembic upgrade head

echo "Seeding HSN GST history..."
python -m app.utils.seed_gst_history || echo "WARNING: seed_gst_history failed, continuing..."

echo "Starting server..."

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 1 \
  --bind 0.0.0.0:${PORT:-8000} \
  --timeout 120 \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --access-logfile - \
  --error-logfile -
