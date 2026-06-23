#!/usr/bin/env bash
# One-step launcher for macOS and Linux: creates a local virtual environment,
# installs dependencies on first run, then launches the app. Any arguments are
# passed straight through (so "./run.sh --input x.pdf" runs the CLI).
set -e
cd "$(dirname "$0")"

# Pick a Python 3 interpreter.
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.10+ and retry." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
exec python pdf2docx_app.py "$@"
