#!/bin/sh
set -e

# entrypoint.sh — works on Railway AND Render (both supply PORT env var).
#
# Render free tier: 512 MB RAM.  sentence-transformers + FAISS load ~300 MB,
# so keep --workers 1 (or 2 at most).  Render will OOM-kill with more workers.
# Change to --workers 2 only if you upgrade to a paid Render plan (1 GB+).

run_migrate() {
  # Large bulk-load migrations must not be SIGKILL'd mid-flight (timeout 60 was).
  # Cap at 25m to stay below Render deploy timeout but allow CBIC seed data to finish.
  if command -v timeout >/dev/null 2>&1; then
    timeout 1500 python -m alembic upgrade head
  else
    python -m alembic upgrade head
  fi
}

echo "[entrypoint] Running Alembic migrations..."
if ! run_migrate; then
  echo "[entrypoint] MIGRATION FAILED — diagnostic"
  python -m alembic heads 2>&1 || true
  ls -la alembic/versions 2>&1 | tail -n 30 || true
  python - <<'PY' 2>&1 || true
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini")
sd = ScriptDirectory.from_config(cfg)
print("heads:", sd.get_heads())
r = sd.get_revision("f1a2b3c4d5e6")
print("f1a2b3c4d5e6 in scripts:", r is not None)
PY
  exit 1
fi
echo "[entrypoint] Migrations complete. Starting server..."

exec python -m gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 1 \
  --bind 0.0.0.0:${PORT:-8000} \
  --timeout 120 \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --access-logfile - \
  --error-logfile -
