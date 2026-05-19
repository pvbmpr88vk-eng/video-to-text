#!/bin/bash
# Install ffmpeg + ffprobe into .local/bin (no Homebrew / no sudo).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.local/bin"
mkdir -p "$BIN"

echo "==> Downloading ffmpeg..."
curl -fL -o /tmp/ffmpeg.zip "https://evermeet.cx/ffmpeg/getrelease/zip"
unzip -o -j /tmp/ffmpeg.zip -d "$BIN"

echo "==> Downloading ffprobe..."
curl -fL -o /tmp/ffprobe.zip "https://evermeet.cx/ffmpeg/get/ffprobe/zip"
unzip -o -j /tmp/ffprobe.zip -d "$BIN"

chmod +x "$BIN/ffmpeg" "$BIN/ffprobe"
xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true

echo ""
echo "Installed:"
"$BIN/ffmpeg" -version | head -1
"$BIN/ffprobe" -version | head -1
echo ""
echo "Add to PATH for this shell:"
echo "  export PATH=\"$BIN:\$PATH\""
