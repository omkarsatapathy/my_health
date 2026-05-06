#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv &>/dev/null; then
  echo "uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  uv venv
fi

echo "Installing dependencies..."
uv pip install -r requirements.txt

echo "Starting HealthPulse AI on port 8080..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
