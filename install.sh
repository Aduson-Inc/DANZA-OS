#!/usr/bin/env bash
# DANZABOSS cross-platform bootstrap for POSIX shells.
# Temporary guided-flow test source; change this when the branch is promoted.
set -euo pipefail

REPO_URL="https://github.com/Aduson-Inc/DANZA-OS"
DANZA_BRANCH="codex/production-danzaboss-install-flow"
RAW_BASE="https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/${DANZA_BRANCH}"
DANZA_VERSION="${DANZA_VERSION:-codex/production-danzaboss-install-flow}"
DANZA_BIN_DIR="${DANZA_BIN_DIR:-$HOME/.local/bin}"
CONFIGURE="${CONFIGURE:-1}"

say() { printf '%s\n' "[DANZABOSS] $*"; }
die() { printf '%s\n' "[DANZABOSS] ERROR: $*" >&2; exit 2; }

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' python3
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' python
  else
    return 1
  fi
}

main() {
  local python
  python="$(find_python || true)"
  [[ -n "$python" ]] || die "Python 3.10+ is required. Install it, then rerun this command."
  "$python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' \
    || die "Python 3.10+ is required."
  command -v git >/dev/null 2>&1 \
    || die "Git is required. Install Git, then rerun this command."

  say "Source: ${REPO_URL}@${DANZA_BRANCH}"
  say "Mandatory dependencies: Python 3.10+, Git."
  say "Optional: tmux (POSIX session convenience only; never auto-installed)."
  say "The installer will create a project-local runtime, install DANZABOSS,"
  say "scaffold the project, activate project-only CORTEX, verify the UI, and open it."
  if [[ "${DANZA_APPROVE:-}" != "1" ]]; then
    read -r -p "Approve installation in this folder? [y/N] " answer
    [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]] || die "Installation cancelled before changes were made."
  fi

  tmp="$(mktemp)"
  # Keep tmp at script scope: EXIT runs after main returns, so a function-local
  # trap variable is no longer bound under set -u.
  trap 'rm -f "$tmp"' EXIT
  curl -fsSL "${RAW_BASE}/install.py" -o "$tmp"
  "$python" "$tmp" --target "$PWD" --branch "$DANZA_BRANCH" "$@"
}

main "$@"
