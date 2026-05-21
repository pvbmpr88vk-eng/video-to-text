#!/usr/bin/env bash
# Pull LLM + hint for Whisper cache (TZ-08).
# 4 GB VPS: run Ollama on HOST, then: ./scripts/docker-pull-models.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODEL="${OLLAMA_MODEL:-qwen2.5:3b-instruct}"

if command -v ollama >/dev/null 2>&1; then
  echo "Pulling Ollama model on host: $MODEL"
  ollama pull "$MODEL"
else
  echo "ollama CLI not on host; using compose profile with-ollama..."
  docker compose --profile with-ollama run --rm ollama ollama pull "$MODEL"
fi

echo ""
echo "Whisper model downloads on first STT into volume whisper_cache."
echo "Optional warm-up: docker compose run --rm worker-transcript python -m app health --skip-ollama"
