#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Starting statsrag..."
echo "Open: http://localhost:8501"
echo ""
echo "To stop: press Ctrl+C, then run: docker compose down"
echo ""

docker compose up
