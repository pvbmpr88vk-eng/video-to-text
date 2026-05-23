#!/usr/bin/env bash
# Smoke test GPU Sharing API (tenant handoff). Requires GPU_SHARING_* in .env
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

: "${GPU_SHARING_API_KEY:?Set GPU_SHARING_API_KEY in .env}"

exec python -m app gpu-sharing-check "$@"
