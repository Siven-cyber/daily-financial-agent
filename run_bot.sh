#!/usr/bin/env bash
# Start the finance bot. Used by the systemd service so the full command is in one
# place instead of being inlined in the unit file.
set -euo pipefail
# SDK state, SQLite sidecars and archives must be private at creation time.
umask 077


HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HERE}"

# Export .env variables (skip blank/comment lines).
set -a
source .env
set +a

export PYTHONPATH="${HERE}/src:${PYTHONPATH:-}"

exec "${HERE}/.venv/bin/python" -m finance_agent.bot;
