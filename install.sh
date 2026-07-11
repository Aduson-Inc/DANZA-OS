#!/usr/bin/env bash
# DANZA-OS installer - hardened curl|bash wrapper around pipx.
#
#   curl -fsSL https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/main/install.sh | bash
#
# Env knobs:
#   DANZA_VERSION   git ref to install (default: latest release tag, else main)
#   DANZA_BIN_DIR   where pipx links the danza binary (default: pipx's default)
#   CONFIGURE       "false" skips PATH configuration - CI mode (default: true)
#
# The whole body lives inside main(), invoked only on the last line, so a
# truncated download can never execute a partial script.
set -euo pipefail

REPO_URL="https://github.com/Aduson-Inc/DANZA-OS"
API_LATEST="https://api.github.com/repos/Aduson-Inc/DANZA-OS/releases/latest"

log() { printf 'danza-install: %s\n' "$*"; }
die() { printf 'danza-install: ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1; }

resolve_version() {
  if [ -n "${DANZA_VERSION:-}" ]; then
    printf '%s' "$DANZA_VERSION"
    return
  fi
  local tag
  tag="$(curl -fsSL "$API_LATEST" 2>/dev/null \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        | head -n1 || true)"
  printf '%s' "${tag:-main}"
}

ensure_pipx() {
  if need pipx; then return; fi
  log "pipx not found - installing with python3 -m pip --user"
  need python3 || die "python3 is required (>= 3.10)"
  python3 -m pip install --user pipx \
    || die "could not install pipx; install it manually, then re-run"
  export PATH="$HOME/.local/bin:$PATH"
  need pipx || die "pipx installed but not on PATH; open a new shell and re-run"
}

main() {
  need curl || die "curl is required"
  local version
  version="$(resolve_version)"
  log "installing danza-os@${version}"
  ensure_pipx
  if [ -n "${DANZA_BIN_DIR:-}" ]; then
    export PIPX_BIN_DIR="$DANZA_BIN_DIR"
  fi
  if pipx list 2>/dev/null | grep -q "danza-os"; then
    log "existing install detected - reinstalling at ${version}"
    pipx install --force "git+${REPO_URL}@${version}"
  else
    pipx install "git+${REPO_URL}@${version}"
  fi
  if [ "${CONFIGURE:-true}" != "false" ]; then
    pipx ensurepath >/dev/null 2>&1 || true
  fi
  log "done. verify with: danza doctor"
}

main "$@"
