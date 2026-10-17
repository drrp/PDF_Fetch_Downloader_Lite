# Portable container build (Fly.io, Koyeb, Railway, Cloud Run, a VPS, etc.).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

# App writes downloads here; mount a volume at /app/downloads for persistence
RUN mkdir -p /app/downloads

ENV PORT=8000
EXPOSE 8000

# --proxy-headers trusts the platform's HTTPS headers so OAuth redirects are https
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=*"]
