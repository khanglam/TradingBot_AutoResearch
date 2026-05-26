#!/usr/bin/env bash
# init.sh — bootstrap on macOS / Linux.
# Idempotent: re-running is safe.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "[init] === TradingBot AutoResearch init (POSIX) ==="

PY=""
for cand in python3.12 python3.11; do
  if command -v "$cand" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  cat >&2 <<EOF
[init] ERROR: Python 3.11 or 3.12 not found on PATH.
  This project requires 3.11 or 3.12 (backtesting.py wheels).
  Install via:
    macOS:   brew install python@3.12
    Ubuntu:  sudo apt install python3.12 python3.12-venv
EOF
  exit 1
fi
echo "[init] using $($PY --version)"

if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
  echo "[init] created .venv"
fi

VENV_PY=".venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -r requirements.txt --quiet
echo "[init] python deps installed"

"$VENV_PY" scripts/bootstrap.py
