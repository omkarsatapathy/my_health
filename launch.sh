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

# Kill any existing process on port 8080
PORT=8080
if lsof -i ":$PORT" >/dev/null 2>&1; then
  echo "Port $PORT is already in use. Killing existing process..."
  lsof -i ":$PORT" | grep -v "COMMAND" | awk '{print $2}' | xargs kill -9 2>/dev/null || true
  sleep 1
fi

echo "Starting HealthPulse AI on port 8080 (with hot reload)..."
echo "Auto-reload enabled: any file changes will restart the server"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
