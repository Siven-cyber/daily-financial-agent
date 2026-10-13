#!/usr/bin/env bash
# Reproducible OpenMinion setup for the finance agent.
#
# Builds openminion/agents.json, registers the local MCP finance server, and patches in
# the settings this project needs. Safe to re-run: it rewrites the config each time.
#
# Backend is selected by FINANCE_BACKEND (default: cortensor):
#   cortensor  -> Cortensor Portal preset, model from FINANCE_MODEL (default gemma4),
#                 credential CORTENSOR_API_KEY
#   lapakvip   -> custom OpenAI-compatible endpoint (LapakVIP), model FINANCE_MODEL
#                 (default lv/deepseek-v4-pro), base url FINANCE_BASE_URL,
#                 credential OPENAI_COMPATIBLE_API_KEY
#
# The submission target is Cortensor Portal; LapakVIP is used for development while
# Portal capacity/latency is limited.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${HERE}/.." && pwd)"
CONFIG="${HERE}/agents.json"
PY="${PY:-python3}"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  # shellcheck disable=SC1090
  set -a; source "${PROJECT_ROOT}/.env"; set +a
fi

BACKEND="${FINANCE_BACKEND:-cortensor}"

echo "Writing OpenMinion config to ${CONFIG} (backend: ${BACKEND})"

if [[ "${BACKEND}" == "lapakvip" ]]; then
  MODEL="${FINANCE_MODEL:-lv/deepseek-v4-pro}"
  BASE_URL="${FINANCE_BASE_URL:-https://router.lapakvip.com/api/v1}"
  openminion --config "${CONFIG}" setup \
    --provider custom-openai-compatible \
    --api-format openai-compatible \
    --base-url "${BASE_URL}" \
    --model "${MODEL}" \
    --no-chat
else
  MODEL="${FINANCE_MODEL:-gemma4}"
  openminion --config "${CONFIG}" setup \
    --provider cortensor-portal \
    --model "${MODEL}" \
    --no-chat
fi

# Register the local stdio MCP finance server (trusted, local to this project).
openminion --config "${CONFIG}" mcp add finance \
  --trusted \
  --cwd "${PROJECT_ROOT}" \
  --command "${PY}" "${HERE}/mcp_finance_server.py"

# Patch runtime + policy settings that the SDK setup does not expose as flags.
"${PY}" - "${CONFIG}" <<'PYEOF'
import json, sys

path = sys.argv[1]
with open(path) as fh:
    cfg = json.load(fh)

runtime = cfg.setdefault("runtime", {})
# Keep a long turn budget (slow models) and run in-process (no stray daemon).
runtime["chat_turn_timeout_seconds"] = 300.0
runtime["process_mode"] = "single-process"

# Auto-approve only our read-only interpret tool; everything else still prompts.
policy = cfg.setdefault("action_policy", {})
rules = policy.setdefault("rules", [])
tool_name = "mcp.finance.interpret_transaction"
if not any(r.get("match", {}).get("tool_name") == tool_name for r in rules):
    rules.append({"match": {"tool_name": tool_name}, "mode": "auto"})

with open(path, "w") as fh:
    json.dump(cfg, fh, indent=1)
print("Patched runtime timeout, single-process mode, and auto-approve rule.")
PYEOF

echo "Done. Config ready at ${CONFIG}"
