#!/usr/bin/env bash
# Start Redis for video-to-text (TZ-05). Run from project root.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ping_redis() {
  redis-cli -u "${REDIS_URL:-redis://127.0.0.1:6379/0}" ping 2>/dev/null | grep -q PONG
}

if ping_redis; then
  echo "Redis already running ($(redis-cli ping 2>/dev/null || echo OK))"
  exit 0
fi

# 1) Homebrew service
if command -v brew >/dev/null 2>&1; then
  if brew list redis >/dev/null 2>&1; then
    echo "Starting Redis via Homebrew..."
    brew services start redis
    sleep 2
    if ping_redis; then
      echo "Redis OK (brew services)"
      exit 0
    fi
  else
    echo "Redis not installed. Run: brew install redis && brew services start redis"
  fi
fi

# 2) redis-server in PATH (foreground fallback — use another terminal)
if command -v redis-server >/dev/null 2>&1; then
  echo "Starting redis-server in background..."
  redis-server --daemonize yes --port 6379
  sleep 1
  if ping_redis; then
    echo "Redis OK (redis-server --daemonize)"
    exit 0
  fi
fi

# 3) Docker Compose (redis service only)
if command -v docker >/dev/null 2>&1; then
  echo "Starting Redis via docker compose..."
  docker compose up -d redis
  sleep 3
  if ping_redis; then
    echo "Redis OK (docker compose)"
    exit 0
  fi
fi

echo ""
echo "Redis is not running. Install one of:"
echo "  brew install redis && brew services start redis"
echo "  docker compose up -d redis   (needs Docker Desktop)"
echo ""
echo "Then check: redis-cli ping   →  PONG"
echo "Start bot:  python -m app bot -v"
exit 1
