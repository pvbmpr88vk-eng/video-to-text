#!/usr/bin/env bash
# Fix bind-mount output/ and Docker volume whisper_cache for appuser (uid 1000).
# Run on VPS after first deploy or if STT fails with "Модель распознавания не загружена".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi
# shellcheck source=scripts/lib/compose-args.sh
source "$ROOT/scripts/lib/compose-args.sh"
init_compose_args "$ROOT"
COMPOSE=(docker compose "${COMPOSE_FILES[@]}" "${COMPOSE_PROFILE_ARGS[@]}")

OUTPUT="${1:-$ROOT/output}"
UID_APP=1000

mkdir -p "$OUTPUT/jobs" "$OUTPUT/telegram/inbox"
# Host chown may fail on macOS for files owned by container uid; fix via container below.
if chown -R "${UID_APP}:${UID_APP}" "$OUTPUT" 2>/dev/null; then
  chmod -R u+rwX "$OUTPUT"
  echo "OK: $OUTPUT -> uid ${UID_APP} (host chown)"
else
  echo "WARN: host chown skipped (use container fix for output/)"
fi

"${COMPOSE[@]}" run --rm --user root worker-transcript sh -c \
  'mkdir -p /home/appuser/.cache/huggingface/hub && chown -R 1000:1000 /home/appuser/.cache'
echo "OK: whisper_cache volume -> uid ${UID_APP}"

if [[ -d "$OUTPUT" ]]; then
  "${COMPOSE[@]}" run --rm --user root -v "${OUTPUT}:/app/output" worker-transcript sh -c \
    'chown -R 1000:1000 /app/output && chmod -R u+rwX /app/output' \
    && echo "OK: output/ -> uid ${UID_APP} (via container)"
fi
