#!/usr/bin/env bash
# Deprecated: use fix-docker-volumes.sh (output + whisper_cache).
exec "$(dirname "$0")/fix-docker-volumes.sh" "$@"
