#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

echo "StatsRAG launcher"
echo "--------------"
echo

# 1) Check Docker CLI exists
if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker is not installed."
  echo "Install Docker Desktop (macOS), then try again."
  exit 1
fi

# 2) Check Docker daemon is reachable (Docker Desktop running)
if ! docker info >/dev/null 2>&1; then
  echo "Error: Docker Desktop does not appear to be running."
  echo
  echo "Fix:"
  echo "  1) Open Docker Desktop from Applications"
  echo "  2) Wait until it shows 'Docker Desktop is running'"
  echo "  3) Run this launcher again"
  exit 1
fi

# 3) Check compose is available (Docker Compose v2)
if ! docker compose version >/dev/null 2>&1; then
  echo "Error: 'docker compose' is not available."
  echo "Update Docker Desktop to a recent version and try again."
  exit 1
fi

echo "Starting statsrag..."
echo "When the app is running, open: http://localhost:8501"
echo
echo "To stop:"
echo "  - Press Ctrl+C in this window"
echo "  - Then run: docker compose down"
echo

docker compose up
