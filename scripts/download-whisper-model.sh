#!/usr/bin/env bash
# Pre-download faster-whisper model so transcribe does not look "stuck".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODEL="${1:-tiny}"
export PYTHONUNBUFFERED=1
echo "Downloading Whisper model: $MODEL (device=cpu, int8)"
"$ROOT/.venv/bin/python" -u -c "
from faster_whisper import WhisperModel
WhisperModel('${MODEL}', device='cpu', compute_type='int8')
print('Model ready:', '${MODEL}')
"
