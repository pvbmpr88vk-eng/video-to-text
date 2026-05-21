#!/usr/bin/env bash
# Shared docker compose file list (TZ-08 + optional TZ-09).
# Source from other scripts: source "$(dirname "$0")/lib/compose-args.sh"
set -euo pipefail

compose_files() {
  local root="${1:-.}"
  local files=(-f "${root}/docker-compose.yml" -f "${root}/docker-compose.prod.yml")
  if [[ -f "${root}/docker-compose.dev.yml" ]] && [[ "${DEPLOY_PROFILE:-}" == "dev" ]]; then
    files+=(-f "${root}/docker-compose.dev.yml")
  fi
  if [[ -f "${root}/docker-compose.local-bot-api.yml" ]]; then
    if [[ "${WITH_LOCAL_BOT_API:-}" == "1" ]] || [[ -n "${TELEGRAM_BOT_API_BASE_URL:-}" ]]; then
      files+=(-f "${root}/docker-compose.local-bot-api.yml")
    fi
  fi
  echo "${files[@]}"
}

compose_profile_args() {
  if [[ "${WITH_LOCAL_BOT_API:-}" == "1" ]] || [[ -n "${TELEGRAM_BOT_API_BASE_URL:-}" ]]; then
    echo --profile with-local-bot-api
  fi
}
