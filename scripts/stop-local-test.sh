#!/usr/bin/env bash
# Остановить локальный тестовый стек (бот + воркеры этого репозитория).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/1}"
# shellcheck source=lib/stop-local-processes.sh
source "$ROOT/scripts/lib/stop-local-processes.sh" "$ROOT"
