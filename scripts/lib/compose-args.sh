#!/usr/bin/env bash
# Shared docker compose file list (TZ-08 + optional TZ-09).
# Source from other scripts: source "$(dirname "$0")/lib/compose-args.sh"
# Paths may contain spaces — use init_compose_args + "${COMPOSE_FILES[@]}", not word-splitting.
set -euo pipefail

COMPOSE_FILES=()
COMPOSE_PROFILE_ARGS=()

init_compose_args() {
  local root="${1:-.}"
  COMPOSE_FILES=(-f "${root}/docker-compose.yml" -f "${root}/docker-compose.prod.yml")
  if [[ -f "${root}/docker-compose.dev.yml" ]] && [[ "${DEPLOY_PROFILE:-}" == "dev" ]]; then
    COMPOSE_FILES+=(-f "${root}/docker-compose.dev.yml")
  fi
  if [[ -f "${root}/docker-compose.local-bot-api.yml" ]]; then
    if [[ "${WITH_LOCAL_BOT_API:-}" == "1" ]] || [[ -n "${TELEGRAM_BOT_API_BASE_URL:-}" ]]; then
      COMPOSE_FILES+=(-f "${root}/docker-compose.local-bot-api.yml")
    fi
  fi
  COMPOSE_PROFILE_ARGS=()
  if [[ "${WITH_LOCAL_BOT_API:-}" == "1" ]] || [[ -n "${TELEGRAM_BOT_API_BASE_URL:-}" ]]; then
    COMPOSE_PROFILE_ARGS=(--profile with-local-bot-api)
  fi
}

# Deprecated: do not use with <<< — breaks on spaces in paths.
compose_files() {
  init_compose_args "${1:-.}"
  echo "${COMPOSE_FILES[@]}"
}

compose_profile_args() {
  init_compose_args "${1:-.}"
  echo "${COMPOSE_PROFILE_ARGS[@]}"
}
