#!/usr/bin/env bash
# Start HTTP staging for GPU Sharing artifacts (audio, ONNX) on the VPS host.
set -euo pipefail

STAGING_DIR="${GPU_STAGING_DIR:-/opt/video-to-text/staging/gpu-audio}"
PORT="${GPU_SHARING_STT_PUBLISH_PORT:-18888}"
APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"

mkdir -p "${STAGING_DIR}"
chown -R "${APP_UID}:${APP_GID}" "${STAGING_DIR}"
chmod 775 "${STAGING_DIR}"

if ss -tln 2>/dev/null | grep -q ":${PORT} "; then
  echo "GPU staging HTTP already listening on :${PORT}"
  exit 0
fi

cd "${STAGING_DIR}"
nohup python3 -m http.server "${PORT}" >"/tmp/vtt-http-${PORT}.log" 2>&1 &
sleep 1
if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/"; then
  echo "GPU staging HTTP OK on :${PORT} (${STAGING_DIR})"
else
  echo "WARN: staging HTTP not responding on :${PORT}" >&2
  exit 1
fi

if command -v ufw >/dev/null 2>&1; then
  ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
fi
