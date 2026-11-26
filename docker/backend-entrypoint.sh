#!/bin/sh
# Entrypoint for the RagNex backend image. First argument selects the role.
set -eu

role="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$role" in
  api)
    # --proxy-headers + --forwarded-allow-ips: take the client IP from the reverse proxy's
    # X-Forwarded-For. Rate limiting is per client IP, so without this every user would
    # share the proxy's IP and one limit. Only trust proxies that can actually reach the API.
    exec uvicorn backend.app.main:create_app --factory \
      --host 0.0.0.0 --port "${PORT:-8000}" \
      --workers "${API_WORKERS:-2}" \
      --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
      "$@"
    ;;
  worker)
    exec celery -A backend.app.core.celery_app.celery_app worker \
      -Q default,parsing,embedding,indexing \
      --concurrency "${WORKER_CONCURRENCY:-2}" \
      --loglevel "${LOG_LEVEL:-info}" \
      "$@"
    ;;
  migrate)
    exec alembic -c /app/backend/alembic.ini upgrade head "$@"
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
