#!/usr/bin/env bash
# Один чистый запуск: Redis + сброс очереди + 3 процесса (macOS: без zombie workers).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

source .venv/bin/activate

brew services start redis 2>/dev/null || true
redis-cli ping

echo "=== stopping old bot/workers ==="
# shellcheck source=lib/stop-local-processes.sh
source "$ROOT/scripts/lib/stop-local-processes.sh" "$ROOT"

python -m app jobs reset-stuck
python -c "from app.queue.workers_cleanup import prune_dead_workers; print('Dead RQ workers removed:', prune_dead_workers())"
python -m app queue status

echo ""
echo "Запустите в ТРЁХ отдельных терминалах (или через Cursor — по одному):"
echo "  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES"
echo "  cd \"$ROOT\" && source .venv/bin/activate"
echo "  python -m app worker transcript"
echo "  python -m app worker summary"
echo "  python -m app bot"
