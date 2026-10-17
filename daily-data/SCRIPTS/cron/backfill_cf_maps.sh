#!/bin/bash

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
TOOL_PATH_PREFIX="${TOOL_PATH_PREFIX:-/opt/homebrew/bin:/usr/local/bin}"
CONDA_ENV="${CONDA_ENV:-compass-daily-data}"

export PATH="${TOOL_PATH_PREFIX}:$PATH"

if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
  CONDA_BIN="${CONDA_EXE}"
elif command -v conda >/dev/null 2>&1; then
  CONDA_BIN="$(command -v conda)"
else
  echo "Conda not found. Install conda, activate it, or set CONDA_EXE."
  exit 1
fi

"$CONDA_BIN" run -n "$CONDA_ENV" python3 "${script_dir}/backfill_cf_maps.py" "$@"
