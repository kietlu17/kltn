#!/usr/bin/env bash
# Runs on the VPS: ./deploy/deploy.sh <image-tag>
# Rolls back to the previous tag when the smoke test fails.
set -euo pipefail
cd "$(dirname "$0")/.."

NEW_TAG="${1:?image tag required}"
OLD_TAG="$(cat .deployed-tag 2>/dev/null || true)"

dc() {
  docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml "$@"
}

# Connections from the VPS to some Docker Hub IPs stall, so bound and retry pulls.
pull() {
  local i
  for i in 1 2 3 4 5; do
    timeout 420 docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml pull -q && return 0
    echo "Pull attempt $i failed, retrying" >&2
  done
  return 1
}

roll_out() {
  export IMAGE_TAG="$1"
  pull && dc up -d --no-build --remove-orphans
}

healthy() {
  local i
  for i in $(seq 1 40); do
    if dc exec -T web wget -qO- http://api-gateway:3000/assistant/health >/dev/null 2>&1 \
      && dc exec -T web wget -qO- "http://api-gateway:3000/products?limit=1" >/dev/null 2>&1; then
      return 0
    fi
    sleep 6
  done
  return 1
}

if roll_out "$NEW_TAG" && healthy; then
  echo "$NEW_TAG" > .deployed-tag
  docker image prune -af --filter "until=72h" >/dev/null
  echo "Deployed $NEW_TAG"
  exit 0
fi

echo "Deploy of $NEW_TAG failed" >&2
dc ps -a >&2
dc logs --tail 30 api-gateway agentic-rag product-service >&2
if [ -n "$OLD_TAG" ] && [ "$OLD_TAG" != "$NEW_TAG" ]; then
  echo "Rolling back to $OLD_TAG" >&2
  roll_out "$OLD_TAG"
fi
exit 1
