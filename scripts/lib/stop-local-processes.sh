#!/usr/bin/env bash
# Stop local bot + RQ workers for this repo only (avoids killing other Python projects).
# Usage: ./scripts/lib/stop-local-processes.sh [project_root]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${1:-}" != "" ]]; then
  ROOT="$(cd "$1" && pwd)"
fi

REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/1}"

# macOS: bot/workers often run via Homebrew Python (cwd in project), not only .venv.
_APP_RE="[Pp]ython -m app"

_stop_matching() {
  local role="$1" # bot | worker transcript | worker summary | worker
  local killed=0
  local pattern="${_APP_RE} ${role}"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local pid="${line%% *}"
    kill -9 "$pid" 2>/dev/null || true
    killed=$((killed + 1))
  done < <(pgrep -fl "$pattern" 2>/dev/null || true)
  echo "$killed"
}

_stop_cursor_wrappers() {
  local killed=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local pid="${line%% *}"
    local cmd="${line#* }"
    if [[ "$cmd" == *"$ROOT"* && "$cmd" == *"python -m app"* ]]; then
      kill -9 "$pid" 2>/dev/null || true
      killed=$((killed + 1))
    fi
  done < <(pgrep -fl "/bin/zsh -c" 2>/dev/null || true)
  echo "$killed"
}

_count_app_processes() {
  pgrep -f "${_APP_RE} (bot|worker)" 2>/dev/null | wc -l | tr -d ' ' || true
}

_finish() {
  local code="$1"
  if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    exit "$code"
  fi
  return "$code"
}

echo "=== stop local stack: $ROOT ==="

bots=$(_stop_matching "bot")
transcript=$(_stop_matching "worker transcript")
summary=$(_stop_matching "worker summary")
workers=$(_stop_matching "worker")
wrappers=$(_stop_cursor_wrappers)

sleep 1

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  TELEGRAM_ACCESS_FILE="${TELEGRAM_ACCESS_FILE:-}" REDIS_URL="$REDIS_URL" \
    "$ROOT/.venv/bin/python" -c "
from app.queue.rq_connection import get_redis
r = get_redis()
r.delete('bot:telegram:polling')
print('Redis lock bot:telegram:polling cleared')
" 2>/dev/null || echo "(skip Redis lock: Redis unavailable)"
fi

remaining=$(_count_app_processes)
echo "Stopped: bot=$bots transcript=$transcript summary=$summary workers=$workers zsh_wrappers=$wrappers"
echo "Remaining bot/worker processes: $remaining"
if [[ "$remaining" != "0" ]]; then
  pgrep -fl "${_APP_RE} (bot|worker)" 2>/dev/null || true
  _finish 1
fi
echo "OK: no duplicate bot/worker processes"
