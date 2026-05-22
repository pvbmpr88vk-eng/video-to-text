#!/usr/bin/env bash
# Remote deploy to VPS (TZ-08). Requires: DEPLOY_HOST, DEPLOY_USER, ssh-keys/id_ed25519
# Usage:
#   export DEPLOY_HOST=1.2.3.4 DEPLOY_USER=root
#   ./scripts/deploy-remote.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${DEPLOY_HOST:?Set DEPLOY_HOST (server IP or hostname)}"
: "${DEPLOY_USER:?Set DEPLOY_USER (e.g. root or ubuntu)}"

KEY="${DEPLOY_KEY:-$ROOT/ssh-keys/id_ed25519}"
APP_DIR="${DEPLOY_APP_DIR:-/opt/video-to-text}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
SCP=(scp -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
RSYNC=(rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new")

echo "=== SSH test ${DEPLOY_USER}@${DEPLOY_HOST} ==="
"${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "uname -a && docker --version && docker compose version"

echo "=== Prepare ${APP_DIR} on server ==="
"${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "mkdir -p ${APP_DIR} && command -v git >/dev/null || (apt-get update && apt-get install -y git)"

"${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "mkdir -p ${APP_DIR}"

echo "=== Rsync project (private repo — no git clone on server) ==="
RSYNC=(rsync -avz --delete
  --exclude '.venv' --exclude 'output' --exclude '.git' --exclude '__pycache__'
  --exclude '.env' --exclude '.env.local'
  --exclude 'telegram-bot.access.test.txt'
  --exclude 'ssh-keys/id_ed25519' --exclude '.clt-install')
"${RSYNC[@]}" -e "ssh -i \"${KEY}\" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=30" \
  "${ROOT}/" "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/"

echo "=== Ollama on host (listen 0.0.0.0 for Docker) ==="
"${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" bash -s <<'REMOTE'
set -euo pipefail
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
mkdir -p /etc/systemd/system/ollama.service.d
printf '%s\n' '[Service]' 'Environment=OLLAMA_HOST=0.0.0.0:11434' \
  > /etc/systemd/system/ollama.service.d/override.conf
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama
sleep 3
ollama pull qwen2.5:3b-instruct
REMOTE

echo "=== Upload secrets (if present locally) ==="
if [[ -f "$ROOT/.env" ]]; then
  "${SCP[@]}" "$ROOT/.env" "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/.env"
else
  "${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" \
    "cd ${APP_DIR} && cp -n deploy/env/minimal-4gb.env .env || true"
  echo "WARN: no local .env — edit ${APP_DIR}/.env on server (TELEGRAM_*)"
fi
if [[ -f "$ROOT/telegram-bot.access.txt" ]]; then
  "${SCP[@]}" "$ROOT/telegram-bot.access.txt" \
    "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/telegram-bot.access.txt"
else
  echo "WARN: no telegram-bot.access.txt — set TELEGRAM_BOT_TOKEN in .env on server"
fi

echo "=== Docker compose up ==="
ENABLE_LOCAL_BOT_API="${ENABLE_LOCAL_BOT_API:-0}"
"${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" bash -s <<REMOTE
set -euo pipefail
cd ${APP_DIR}
WITH_LOCAL_BOT_API=${ENABLE_LOCAL_BOT_API}
source scripts/lib/compose-args.sh
init_compose_args "\${PWD}"
docker compose "\${COMPOSE_FILES[@]}" "\${COMPOSE_PROFILE_ARGS[@]}" up -d --build
./scripts/fix-docker-volumes.sh
echo "=== Warm up Whisper model (small) ==="
docker compose "\${COMPOSE_FILES[@]}" "\${COMPOSE_PROFILE_ARGS[@]}" exec -T worker-transcript python -c \
  "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8'); print('whisper ok')"
docker compose "\${COMPOSE_FILES[@]}" "\${COMPOSE_PROFILE_ARGS[@]}" exec -T redis redis-cli DEL bot:telegram:polling 2>/dev/null || true
docker compose "\${COMPOSE_FILES[@]}" "\${COMPOSE_PROFILE_ARGS[@]}" restart bot
sleep 5
WITH_LOCAL_BOT_API=${ENABLE_LOCAL_BOT_API} ./scripts/deploy-check.sh
REMOTE

echo "NOTE: stop any other bot instance (local Mac) to avoid Telegram 409 Conflict."

echo "OK: deployed to ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}"
