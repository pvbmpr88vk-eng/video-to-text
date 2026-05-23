#!/usr/bin/env bash
# Deploy landing only (docker-compose.site.yml) to VPS.
# Usage:
#   export DEPLOY_HOST=62.217.176.132 DEPLOY_USER=root
#   export SITE_DOMAIN=pible.ru SITE_EMAIL=admin@pible.ru
#   ./scripts/deploy-site-remote.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

: "${DEPLOY_HOST:?Set DEPLOY_HOST}"
: "${DEPLOY_USER:?Set DEPLOY_USER}"
: "${SITE_DOMAIN:?Set SITE_DOMAIN (e.g. pible.ru)}"

KEY="${DEPLOY_KEY:-$ROOT/ssh-keys/id_ed25519}"
APP_DIR="${DEPLOY_APP_DIR:-/opt/video-to-text}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
RSYNC=(rsync -avz -e "ssh -i ${KEY} -o StrictHostKeyChecking=accept-new")

echo "=== Site deploy → ${DEPLOY_USER}@${DEPLOY_HOST} (${SITE_DOMAIN}) ==="
"${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "mkdir -p ${APP_DIR}"

RSYNC_SSH=(rsync -avz -e "ssh -i \"${KEY}\" -o StrictHostKeyChecking=accept-new")

"${RSYNC_SSH[@]}" \
  "${ROOT}/website/" "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/website/"
"${RSYNC_SSH[@]}" \
  "${ROOT}/deploy/caddy/" "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/deploy/caddy/"
"${RSYNC_SSH[@]}" \
  "${ROOT}/docker-compose.site.yml" \
  "${ROOT}/scripts/up-site.sh" \
  "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/"

SITE_EMAIL="${SITE_EMAIL:-admin@pible.ru}"
"${SSH[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" \
  "SITE_DOMAIN=$(printf '%q' "${SITE_DOMAIN}") SITE_EMAIL=$(printf '%q' "${SITE_EMAIL}") APP_DIR=$(printf '%q' "${APP_DIR}") bash -s" <<'REMOTE'
set -euo pipefail
cd "$APP_DIR"
touch .env
if grep -q '^SITE_DOMAIN=' .env 2>/dev/null; then
  sed -i "s|^SITE_DOMAIN=.*|SITE_DOMAIN=\"${SITE_DOMAIN}\"|" .env
else
  echo "SITE_DOMAIN=\"${SITE_DOMAIN}\"" >> .env
fi
if grep -q '^SITE_EMAIL=' .env 2>/dev/null; then
  sed -i "s|^SITE_EMAIL=.*|SITE_EMAIL=${SITE_EMAIL}|" .env
else
  echo "SITE_EMAIL=${SITE_EMAIL}" >> .env
fi
ufw allow 80/tcp 2>/dev/null || true
ufw allow 443/tcp 2>/dev/null || true
set -a && source .env && set +a
docker compose -f docker-compose.site.yml up -d --build
docker compose -f docker-compose.site.yml ps
REMOTE

echo ""
echo "DNS: A @ and A www for ${SITE_DOMAIN} must point to ${DEPLOY_HOST} (current dig may differ)."
echo "Check: curl -sI https://${SITE_DOMAIN}/"
