#!/usr/bin/env bash
# Локальный стек с ТЕСТОВЫМ ботом (telegram-bot.access.test.txt).
# Прод-бот — только на VPS (62.217.176.132), не запускайте telegram-bot.access.txt локально.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

TEST_ACCESS="$ROOT/telegram-bot.access.test.txt"
if [[ ! -f "$TEST_ACCESS" ]]; then
  echo "Создайте $TEST_ACCESS из telegram-bot.access.test.example.txt" >&2
  exit 1
fi

export TELEGRAM_ACCESS_FILE="$TEST_ACCESS"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/1}"
export APP_ENV="${APP_ENV:-test}"
export TELEGRAM_BOT_FILE_SIZE_LIMIT="${TELEGRAM_BOT_FILE_SIZE_LIMIT:-524288000}"

if [[ -f "$ROOT/.env.local" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env.local"
  set +a
fi

source .venv/bin/activate

brew services start redis 2>/dev/null || true
redis-cli ping

echo "=== stopping old local bot/workers ==="
# shellcheck source=lib/stop-local-processes.sh
source "$ROOT/scripts/lib/stop-local-processes.sh" "$ROOT"

python -m app jobs reset-stuck
python -c "from app.queue.workers_cleanup import prune_dead_workers; print('Dead RQ workers removed:', prune_dead_workers())"
python -m app queue status

echo ""
echo "Тестовый бот: TELEGRAM_ACCESS_FILE=$TELEGRAM_ACCESS_FILE"
echo "Redis: $REDIS_URL (DB 1 — отдельно от дефолтной /0)"
echo "Лимит файла из Telegram: $((TELEGRAM_BOT_FILE_SIZE_LIMIT / 1024 / 1024)) MB"
echo ""
echo "Запустите в ТРЁХ терминалах:"
echo "  cd \"$ROOT\" && source .venv/bin/activate"
echo "  export TELEGRAM_ACCESS_FILE=\"$TEST_ACCESS\" REDIS_URL=\"$REDIS_URL\" OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES"
echo "  python -m app worker transcript"
echo "  python -m app worker summary"
echo "  python -m app bot -v"
