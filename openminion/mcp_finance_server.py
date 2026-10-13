"""Stdio MCP server exposing finance tools to the OpenMinion agent.

Security model: this server never touches the database and never sees a user id.
Its only job is to turn a free-text money message into structured fields. The bot
(which knows the authenticated Telegram user_id) performs the actual database write
and verifies it. That keeps the model from ever choosing whose data is written.

Pure standard library: newline-delimited JSON-RPC 2.0 over stdin/stdout, so no extra
dependency is needed and OpenMinion's MCP client can speak to it directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow importing the shared parser from the project src/ tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finance_agent.parser import parse_message  # noqa: E402

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

TOOLS = [
    {
        "name": "interpret_transaction",
        "description": (
            "Interpret one personal finance message written in Indonesian or English "
            "and return structured fields. Does not store anything. Use this to turn a "
            "user message like 'makan siang 25rb' into {kind, amount, category, note}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The raw user message to interpret.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["expense", "income"],
                    "description": "Override the detected kind when the text is ambiguous.",
                },
                "amount": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Override the detected amount in integer IDR.",
                },
                "category": {
                    "type": "string",
                    "description": "Override the detected category.",
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        # MCP annotations: this tool is read-only and non-destructive.
        "annotations": {
            "title": "Interpret transaction",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
]


def log(message: str) -> None:
    """Diagnostics go to stderr; stdout is reserved for protocol messages."""
    print(f"[mcp-finance] {message}", file=sys.stderr, flush=True)


def interpret(args: dict) -> dict:
    """Return structured transaction fields for a message, applying any overrides."""
    text = str(args.get("text", "")).strip()
    parsed = parse_message(text)
    result = {
        "kind": "expense",
        "amount": 0,
        "category": "Lainnya",
        "note": text,
        "recognized": parsed is not None,
    }
    if parsed is not None:
        result.update(
            kind=parsed.kind,
            amount=parsed.amount,
            category=parsed.category,
            note=parsed.note,
        )
    # Apply explicit overrides from the model when provided.
    if args.get("kind") in {"expense", "income"}:
        result["kind"] = args["kind"]
    if isinstance(args.get("amount"), int) and args["amount"] > 0:
        result["amount"] = args["amount"]
        result["recognized"] = True
    if isinstance(args.get("category"), str) and args["category"].strip():
        result["category"] = args["category"].strip()
    return result


def _tool_result(payload: dict) -> dict:
    """Wrap a payload as an MCP tools/call result (text content + structured content)."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
        "isError": False,
    }


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    if msg_id is None:
        return None  # notification (e.g. notifications/initialized)

    if method == "initialize":
        requested = str(params.get("protocolVersion", ""))
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        result: dict = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "finance", "version": "0.1.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        if name != "interpret_transaction":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32602, "message": f"unknown tool {name}"},
            }
        payload = interpret(params.get("arguments") or {})
        log(f"interpret -> {payload}")
        result = _tool_result(payload)
    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    log("started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
