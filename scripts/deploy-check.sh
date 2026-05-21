#!/usr/bin/env bash
# Smoke check after docker compose up (TZ-08). Exit 0 = OK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

# shellcheck source=scripts/lib/compose-args.sh
source "$ROOT/scripts/lib/compose-args.sh"
read -r -a COMPOSE_FILES <<<"$(compose_files "$ROOT")"
read -r -a PROFILE_ARGS <<<"$(compose_profile_args)"
COMPOSE=(docker compose "${COMPOSE_FILES[@]}" "${PROFILE_ARGS[@]}")

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

if [[ -n "${TELEGRAM_BOT_API_BASE_URL:-}" ]] || "${COMPOSE[@]}" ps --status running 2>/dev/null | grep -q telegram-bot-api; then
  echo "=== Local Bot API (telegram-bot-api) ==="
  "${COMPOSE[@]}" ps telegram-bot-api 2>/dev/null | grep -q telegram-bot-api || fail "telegram-bot-api not running"
  "${COMPOSE[@]}" exec -T telegram-bot-api sh -c \
    'wget -q --server-response http://127.0.0.1:8081/ 2>&1 | grep -q HTTP/' \
    || fail "telegram-bot-api not reachable on :8081"
  echo "Local Bot API OK"
fi

echo "=== worker-transcript health ==="
"${COMPOSE[@]}" exec -T worker-transcript python -m app health --skip-ollama \
  || fail "worker-transcript health"

echo "=== whisper cache writable ==="
"${COMPOSE[@]}" exec -T worker-transcript python -c "
from pathlib import Path
p = Path('/home/appuser/.cache/huggingface/hub')
p.mkdir(parents=True, exist_ok=True)
f = p / '.write_test'
f.write_text('ok')
f.unlink()
print('whisper cache ok')
" || fail "whisper_cache not writable — run ./scripts/fix-docker-volumes.sh"

echo "=== worker-summary health (ollama) ==="
"${COMPOSE[@]}" exec -T worker-summary python -m app health || fail "worker-summary / ollama"

if "${COMPOSE[@]}" ps --status running 2>/dev/null | grep -q ollama; then
  echo "=== ollama tags ==="
  "${COMPOSE[@]}" exec -T ollama ollama list || fail "ollama list"
fi

echo "OK: deploy check passed"
