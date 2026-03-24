#!/usr/bin/env bash
# Production startup — Gunicorn with uvicorn workers (one per CPU core)
# Handles 1M+ requests via:
#   - Multiple workers (all CPU cores)
#   - Async I/O per worker (uvicorn event loop)
#   - Graceful restarts, worker recycling, backlog control
#
# Usage:
#   ./scripts/start_prod.sh
#   WORKERS=16 PORT=8000 ./scripts/start_prod.sh

set -euo pipefail

WORKERS="${WORKERS:-$(python3 -c 'import os; print(min(os.cpu_count() * 2 + 1, 17))')}"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
LOG_LEVEL="${LOG_LEVEL:-info}"
WORKER_TIMEOUT="${WORKER_TIMEOUT:-120}"       # seconds before a slow worker is killed
KEEPALIVE="${KEEPALIVE:-75}"                  # keep-alive for SSE connections (seconds)
MAX_REQUESTS="${MAX_REQUESTS:-10000}"         # recycle each worker after N requests
MAX_REQUESTS_JITTER="${MAX_REQUESTS_JITTER:-1000}"  # prevent thundering-herd on recycle

echo "Starting SAP AI Agent — $WORKERS workers on $HOST:$PORT"

exec gunicorn api.server:app \
  --workers "$WORKERS" \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "$HOST:$PORT" \
  --timeout "$WORKER_TIMEOUT" \
  --keep-alive "$KEEPALIVE" \
  --max-requests "$MAX_REQUESTS" \
  --max-requests-jitter "$MAX_REQUESTS_JITTER" \
  --backlog 2048 \
  --log-level "$LOG_LEVEL" \
  --access-logfile - \
  --error-logfile - \
  --forwarded-allow-ips "*"
