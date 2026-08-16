#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python3 scripts/check_environment.py
test -f .env || cp .env.example .env
docker compose up --build -d
printf '\nAI Fashion Video Director started.\n\nFrontend:  http://127.0.0.1:3000\nBackend:   http://127.0.0.1:8000\nAPI Docs:  http://127.0.0.1:8000/docs\n\nLogs: docker compose logs -f\n'

