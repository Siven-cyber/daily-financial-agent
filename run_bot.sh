#!/usr/bin/env bash
# Start the finance bot. Used by the systemd service so the full command is in one
# place instead of being inlined in the unit file.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HERE}"

source .venv/bin/activate
# Export .env variables (skip blank/comment lines).
set -a
source .env
set +a

export PYTHONPATH="${HERE}/src:${PYTHONPATH:-}"

exec python -m finance_agent.bot
