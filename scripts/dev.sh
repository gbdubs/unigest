#!/usr/bin/env bash
set -euo pipefail

echo "Starting Unigest dev environment..."
echo ""

# Start postgres + server
docker compose up -d --build

echo ""
echo "Server running at http://localhost:8000"
echo "API docs at http://localhost:8000/docs"
echo ""
echo "To start the worker:"
echo "  pip install -e .[worker]"
echo "  python -m worker.main"
echo ""
echo "To stop:"
echo "  docker compose down"
