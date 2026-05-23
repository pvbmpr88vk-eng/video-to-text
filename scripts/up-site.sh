#!/usr/bin/env bash
# Start landing site + Caddy (HTTPS when SITE_DOMAIN is a real hostname).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

: "${SITE_DOMAIN:?Set SITE_DOMAIN in .env (see deploy/env/site.env.example)}"

echo "=== Site stack: SITE_DOMAIN=${SITE_DOMAIN} ==="
docker compose -f docker-compose.site.yml up -d --build

echo ""
echo "DNS: A-record ${SITE_DOMAIN} → this server's public IP"
echo "Check: curl -sI https://${SITE_DOMAIN}/  (after DNS propagates)"
echo "Logs:  docker compose -f docker-compose.site.yml logs -f site-caddy"
