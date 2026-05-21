#!/usr/bin/env bash
# Fix bind-mount output/ and Docker volume whisper_cache for appuser (uid 1000).
# Run on VPS after first deploy or if STT fails with "Модель распознавания не загружена".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
if [[ -f docker-compose.dev.yml ]] && [[ "${DEPLOY_PROFILE:-}" == "dev" ]]; then
  COMPOSE+=(-f docker-compose.dev.yml)
fi

OUTPUT="${1:-$ROOT/output}"
UID_APP=1000

mkdir -p "$OUTPUT/jobs" "$OUTPUT/telegram/inbox"
chown -R "${UID_APP}:${UID_APP}" "$OUTPUT"
chmod -R u+rwX "$OUTPUT"
echo "OK: $OUTPUT -> uid ${UID_APP}"

"${COMPOSE[@]}" run --rm --user root worker-transcript sh -c \
  'mkdir -p /home/appuser/.cache/huggingface/hub && chown -R 1000:1000 /home/appuser/.cache'
echo "OK: whisper_cache volume -> uid ${UID_APP}"
