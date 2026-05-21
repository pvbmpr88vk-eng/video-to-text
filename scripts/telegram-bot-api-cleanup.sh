#!/usr/bin/env bash
# Delete cached files in Local Bot API volume older than N hours (TZ-09).
# Usage on VPS:
#   ./scripts/telegram-bot-api-cleanup.sh 6
#   docker compose ... run --rm telegram-bot-api-cleanup ...  # or exec into volume via:
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TTL_HOURS="${1:-${TELEGRAM_BOT_API_CACHE_TTL_HOURS:-6}}"
VOLUME_NAME="${TG_API_VOLUME:-video-to-text_telegram_bot_api_data}"

if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  docker run --rm -v "${VOLUME_NAME}:/data:rw" alpine:3.20 sh -c "
    set -eu
    echo \"Cleaning /data: files older than ${TTL_HOURS}h\"
    find /data -type f -mmin +$((TTL_HOURS * 60)) -print -delete 2>/dev/null || true
    find /data -type d -empty -not -path /data -delete 2>/dev/null || true
    du -sh /data 2>/dev/null || true
  "
else
  echo "Volume not found: $VOLUME_NAME" >&2
  echo "Run via compose profile or set TG_API_VOLUME." >&2
  exit 1
fi

echo "OK: cleanup done (TTL=${TTL_HOURS}h)"
