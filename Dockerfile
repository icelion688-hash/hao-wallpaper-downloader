FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        gcc \
        libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend ./backend
COPY config.example.yaml ./config.example.yaml
COPY frontend/index.html ./frontend/index.html
COPY frontend/package.json ./frontend/package.json
COPY frontend/vite.config.js ./frontend/vite.config.js
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p \
        /app/data \
        /app/downloads/anime \
        /app/downloads/landscape \
        /app/downloads/dynamic \
        /app/downloads/uncategorized

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
