#!/usr/bin/env bash
# Create .venv with Python 3.11+ (prefers Homebrew python@3.12).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

choose_python() {
  for candidate in \
    "${PYTHON:-}" \
    "$(command -v python3.12 2>/dev/null || true)" \
    "/opt/homebrew/bin/python3.12" \
    "$(command -v python3.11 2>/dev/null || true)" \
    "/opt/homebrew/bin/python3.11" \
    "$(command -v python3 2>/dev/null || true)"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
      echo "$candidate"
      return 0
    fi
  done
  echo "Need Python 3.11+. Install: brew install python@3.12" >&2
  return 1
}

PY="$(choose_python)"
echo "Using: $("$PY" --version) at $PY"

rm -rf .venv
"$PY" -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/pip install -r requirements.txt
echo "Done. Activate: source .venv/bin/activate"
