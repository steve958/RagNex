#!/usr/bin/env bash
set -euo pipefail

NO_UP=false
if [[ "${1:-}" == "--no-up" ]]; then
  NO_UP=true
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$ROOT_DIR/.env" && -f "$ROOT_DIR/.env.example" ]]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  echo "Created .env from .env.example"
fi

if [[ "$NO_UP" == "false" ]]; then
  docker compose -f "$ROOT_DIR/docker-compose.dev.yml" up -d
fi

echo "Dev services are starting."
echo "- Postgres: localhost:5432"
echo "- Redis: localhost:6379"
echo "- OpenSearch: http://localhost:9200"
echo "- OpenSearch Dashboards: http://localhost:5601"
echo "- MinIO: http://localhost:9000 (console: http://localhost:9001)"
