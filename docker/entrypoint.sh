#!/bin/sh
set -eu

cd /app

mkdir -p \
  /app/data \
  /app/downloads/anime \
  /app/downloads/landscape \
  /app/downloads/dynamic \
  /app/downloads/uncategorized

if [ ! -f /app/data/config.yaml ]; then
  cp /app/config.example.yaml /app/data/config.yaml
  echo '[entrypoint] 未检测到 data/config.yaml，已根据 config.example.yaml 创建默认配置。'
fi

ln -sf /app/data/config.yaml /app/config.yaml

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
