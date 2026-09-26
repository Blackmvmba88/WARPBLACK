#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTROL_REPO="${1:-${WARPBLACK_CONTROL_REPO:-}}"
WORKSPACE="${2:-${WARPBLACK_WORKSPACE:-$HOME}}"
VENV="${WARPBLACK_VENV:-$ROOT/.venv}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11+ is required." >&2
  exit 2
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required")
PY

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[WARPBLACK] creating virtual environment"
  python3 -m venv "$VENV"
fi

echo "[WARPBLACK] installing local package"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install -e "$ROOT"

echo "[WARPBLACK] doctor"
DOCTOR_ARGS=(doctor --workspace "$WORKSPACE")
if [[ -n "$CONTROL_REPO" ]]; then
  DOCTOR_ARGS+=(--repo "$CONTROL_REPO")
fi
"$VENV/bin/warpblack" "${DOCTOR_ARGS[@]}"

if [[ -z "$CONTROL_REPO" ]]; then
  cat <<EOF

WARPBLACK is installed.

To start the observer:
  bash scripts/install-local.sh OWNER/PRIVATE_CONTROL_REPO /path/to/workspace

Example:
  bash scripts/install-local.sh Blackmvmba88/control "$WORKSPACE"
EOF
  exit 0
fi

echo "[WARPBLACK] starting private GitHub observer"
exec "$ROOT/scripts/start-control.sh" "$CONTROL_REPO" "$WORKSPACE"
