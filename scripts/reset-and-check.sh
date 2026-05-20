#!/usr/bin/env bash
# Сброс зависших задач и проверка очереди (после Ctrl+C на worker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate

echo "=== git pull ==="
git pull

echo ""
echo "=== jobs reset-stuck ==="
python -m app jobs reset-stuck

echo ""
echo "=== queue status ==="
python -m app queue status

echo ""
echo "Дальше в ТРЁХ отдельных терминалах:"
echo "  1) python -m app worker transcript"
echo "  2) python -m app worker summary"
echo "  3) python -m app bot"
