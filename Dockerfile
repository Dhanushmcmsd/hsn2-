# Use a lightweight base image
FROM python:3.11-slim

# Prevent Python from writing .pyc files & enable logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install only required system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies FIRST (for caching)
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

RUN python -c "from sentence_transformers import SentenceTransformer; \
  SentenceTransformer('all-MiniLM-L6-v2')"

# Copy the rest of the app
COPY . .

# Fail the build if the Alembic graph is broken or any expected revision is missing
# (catches stale Docker cache / incomplete checkouts before deploy).
RUN python - <<'PY'
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini")
sd = ScriptDirectory.from_config(cfg)
heads = sd.get_heads()
assert len(heads) == 1, f"expected 1 alembic head, got {heads!r}"
assert sd.get_revision("f1a2b3c4d5e6") is not None, "missing revision f1a2b3c4d5e6"
print("alembic ok: head =", heads[0])
PY

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Railway provides PORT env var
CMD ["./entrypoint.sh"]
