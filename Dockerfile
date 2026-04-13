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

# Copy the rest of the app
COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Railway provides PORT env var
CMD ["./entrypoint.sh"]
