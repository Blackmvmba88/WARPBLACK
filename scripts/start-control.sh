#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTROL_REPO="${1:-${WARPBLACK_CONTROL_REPO:-}}"
WORKSPACE="${2:-${WARPBLACK_WORKSPACE:-$PWD}}"
ACTOR="${WARPBLACK_ACTOR:-}"
POLL="${WARPBLACK_POLL:-5}"
VENV="${WARPBLACK_VENV:-$ROOT/.venv}"

if [[ -z "$CONTROL_REPO" ]]; then
  echo "usage: $0 OWNER/PRIVATE_CONTROL_REPO [WORKSPACE]" >&2
  echo "or set WARPBLACK_CONTROL_REPO" >&2
  exit 2
fi

if [[ ! -d "$WORKSPACE" ]]; then
  echo "workspace does not exist: $WORKSPACE" >&2
  exit 2
fi

if [[ -z "${WARPBLACK_GITHUB_TOKEN:-}" ]]; then
  if command -v gh >/dev/null 2>&1; then
    WARPBLACK_GITHUB_TOKEN="$(gh auth token)"
    export WARPBLACK_GITHUB_TOKEN
  else
    echo "WARPBLACK_GITHUB_TOKEN is required when GitHub CLI is unavailable" >&2
    exit 2
  fi
fi

if [[ -z "$ACTOR" ]]; then
  if command -v gh >/dev/null 2>&1; then
    ACTOR="$(gh api user --jq .login)"
  else
    echo "WARPBLACK_ACTOR is required when GitHub CLI is unavailable" >&2
    exit 2
  fi
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install -e "$ROOT"

echo "WARPBLACK control repo: $CONTROL_REPO"
echo "WARPBLACK actor: $ACTOR"
echo "WARPBLACK workspace: $WORKSPACE"

"$VENV/bin/warpblack" github-bootstrap \
  --repo "$CONTROL_REPO" \
  --actor "$ACTOR" \
  --workspace "$WORKSPACE"

exec "$VENV/bin/warpblack" github-watch \
  --repo "$CONTROL_REPO" \
  --actor "$ACTOR" \
  --workspace "$WORKSPACE" \
  --poll "$POLL"
