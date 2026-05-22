#!/usr/bin/env bash
# Enable Local Bot API stack (TZ-09). Requires TELEGRAM_API_ID + TELEGRAM_API_HASH in .env
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

: "${TELEGRAM_API_ID:?Set TELEGRAM_API_ID in .env (my.telegram.org)}"
: "${TELEGRAM_API_HASH:?Set TELEGRAM_API_HASH in .env}"

export WITH_LOCAL_BOT_API=1
export TELEGRAM_BOT_API_BASE_URL="${TELEGRAM_BOT_API_BASE_URL:-http://telegram-bot-api:8081}"
export TELEGRAM_BOT_FILE_SIZE_LIMIT="${TELEGRAM_BOT_FILE_SIZE_LIMIT:-524288000}"
export TELEGRAM_BOT_API_CACHE_TTL_HOURS="${TELEGRAM_BOT_API_CACHE_TTL_HOURS:-6}"

# shellcheck source=scripts/lib/compose-args.sh
source "$ROOT/scripts/lib/compose-args.sh"
init_compose_args "$ROOT"

echo "=== compose up (Local Bot API) ==="
docker compose "${COMPOSE_FILES[@]}" "${COMPOSE_PROFILE_ARGS[@]}" up -d --build

./scripts/fix-docker-volumes.sh
sleep 8
WITH_LOCAL_BOT_API=1 TELEGRAM_BOT_API_BASE_URL="$TELEGRAM_BOT_API_BASE_URL" ./scripts/deploy-check.sh

echo "OK: stack with Local Bot API is up"
