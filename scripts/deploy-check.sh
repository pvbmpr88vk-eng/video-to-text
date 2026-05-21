#!/usr/bin/env bash
# Smoke check after docker compose up (TZ-08). Exit 0 = OK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
if [[ -f docker-compose.dev.yml ]] && [[ "${DEPLOY_PROFILE:-}" == "dev" ]]; then
  COMPOSE+=(-f docker-compose.dev.yml)
fi

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "=== docker compose ps ==="
"${COMPOSE[@]}" ps

echo "=== redis ping ==="
"${COMPOSE[@]}" exec -T redis redis-cli ping | grep -q PONG || fail "redis ping"

echo "=== bot health (skip ollama) ==="
"${COMPOSE[@]}" exec -T bot python -m app health --skip-ollama || fail "bot health"

echo "=== worker-transcript health ==="
"${COMPOSE[@]}" exec -T worker-transcript python -m app health --skip-ollama \
  || fail "worker-transcript health"

echo "=== worker-summary health (ollama) ==="
"${COMPOSE[@]}" exec -T worker-summary python -m app health || fail "worker-summary / ollama"

if "${COMPOSE[@]}" ps --status running 2>/dev/null | grep -q ollama; then
  echo "=== ollama tags ==="
  "${COMPOSE[@]}" exec -T ollama ollama list || fail "ollama list"
fi

echo "OK: deploy check passed"
