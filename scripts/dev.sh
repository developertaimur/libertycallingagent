#!/usr/bin/env bash
# Hot-reload Jessica agent (requires SWML_BASIC_AUTH_* in .env)
set -euo pipefail
cd "$(dirname "$0")/.."
export $(grep -v '^#' .env | xargs -d '\n' 2>/dev/null || true)
PORT="${AGENT_PORT:-3000}"
exec uvicorn agent.jessica_agent:app --reload --host 0.0.0.0 --port "$PORT"
