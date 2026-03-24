#!/usr/bin/env bash
# Development startup — single uvicorn worker with hot reload
set -euo pipefail

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

echo "Starting SAP AI Agent (dev) on $HOST:$PORT"
exec uvicorn api.server:app \
  --host "$HOST" \
  --port "$PORT" \
  --reload \
  --reload-dir api \
  --reload-dir agent \
  --reload-dir modules \
  --reload-dir tools \
  --log-level info
