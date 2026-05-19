#!/usr/bin/env bash
# Download the single default summary model (qwen2.5:3b-instruct for 8 GB RAM).
# Other models (7b, saiga) are not pulled by this project — install manually if needed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${OLLAMA_MODEL:-qwen2.5:3b-instruct}"

OLLAMA=""
for candidate in /opt/homebrew/bin/ollama /usr/local/bin/ollama "$(command -v ollama 2>/dev/null)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    OLLAMA="$candidate"
    break
  fi
done
if [[ -z "$OLLAMA" ]]; then
  echo "Ollama not found. Install: brew install ollama" >&2
  exit 1
fi

echo "Pulling summary model: $MODEL"
"$OLLAMA" pull "$MODEL"
echo "Ready: $MODEL"
