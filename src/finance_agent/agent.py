"""Thin wrapper around the OpenMinion Agent for this project.

Two capabilities are used:

1. interpret(text): run a turn that calls the MCP `interpret_transaction` tool to turn
   a free-text money message into structured fields. This is only used as a fallback
   when the local parser is not confident; the local parser handles the common case.

2. answer(question, context): run a plain turn (no tools) to answer a user question or
   write a summary, given data the bot already read from the database and passes in as
   context. The model never reads the database itself.

Why this split: on OpenMinion 0.1.3/0.1.4 the model-generated final text does not reliably
follow instructions, and @tool functions are not exposed (see upstream issues #248/#249).
So the bot never trusts the model's free-text claims for money. Writes and verification
happen in db.py; the model only interprets language and drafts prose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# MCP runtime tool name = "mcp.<server>.<tool>".
INTERPRET_TOOL = "mcp.finance.interpret_transaction"


@dataclass(frozen=True)
class Interpretation:
    recognized: bool
    kind: str
    amount: int
    category: str
    note: str


class FinanceAgent:
    """Owns one OpenMinion runtime for the process lifetime."""

    def __init__(self, config_path: Path | str, agent_id: Optional[str] = None) -> None:
        # Imported lazily so unit tests that do not need the model can import this module.
        from openminion.api import APIRuntime

        self._config_path = str(config_path)
        self._agent_id = agent_id
        self._runtime = APIRuntime.from_config_path(self._config_path)

    def close(self) -> None:
        self._runtime.close()

    def interpret(self, text: str, *, session_id: str) -> Optional[Interpretation]:
        """Ask the agent to interpret a message via the MCP tool.

        Returns None if the tool did not run or produced no usable structured output,
        so the caller can fall back to a clarification prompt.
        """
        payload: dict[str, object] = {
            "message": (
                "Call interpret_transaction with the user's message as the `text` "
                f"argument. User message: {text}"
            ),
            "session_id": session_id,
            "deliver": False,
            "override_system_prompt": (
                "You interpret personal finance messages. Always call the "
                "interpret_transaction tool with the user's raw message."
            ),
            "allowed_tools": [INTERPRET_TOOL],
            "forced_tools": [INTERPRET_TOOL],
        }
        if self._agent_id:
            payload["agent_id"] = self._agent_id

        structured = self._run_and_extract_tool_output(payload)
        if structured is None:
            return None
        return Interpretation(
            recognized=bool(structured.get("recognized", False)),
            kind=str(structured.get("kind", "expense")),
            amount=int(structured.get("amount", 0) or 0),
            category=str(structured.get("category", "Lainnya")),
            note=str(structured.get("note", text)),
        )

    def answer(self, question: str, *, context: str, session_id: str) -> str:
        """Answer a user question using only the context the bot provides.

        The model has no tools here and no database access; it only phrases the
        answer from the numbers we already computed.
        """
        payload: dict[str, object] = {
            "message": f"Context (already computed, treat as truth):\n{context}\n\nQuestion: {question}",
            "session_id": session_id,
            "deliver": False,
            "override_system_prompt": (
                "You are a concise personal finance assistant. Answer only from the "
                "provided context. Do not invent numbers. Reply in the user's language."
            ),
        }
        if self._agent_id:
            payload["agent_id"] = self._agent_id
        response = self._runtime.submit_turn(payload=payload).result(timeout_s=180.0)
        return str(getattr(response, "final_text", "") or "")

    def _run_and_extract_tool_output(self, payload: dict) -> Optional[dict]:
        """Run a streamed turn and pull the structured output of the interpret tool."""
        handle = self._runtime.submit_turn(payload=payload)
        structured: Optional[dict] = None
        for chunk in handle.stream():
            data = getattr(chunk, "data", {}) or {}
            # Tool completion chunks carry the structured output we need.
            if chunk.kind in {"tool", "tool_result"}:
                candidate = _find_structured(data)
                if candidate is not None:
                    structured = candidate
        handle.result(timeout_s=180.0)
        return structured


def _find_structured(data: dict) -> Optional[dict]:
    """Best-effort extraction of the interpret tool's structured payload from a chunk."""
    # Direct structuredContent.
    for key in ("structuredContent", "structured_content", "outputs", "output"):
        value = data.get(key)
        if isinstance(value, dict) and "kind" in value and "amount" in value:
            return value
    # Text content holding JSON.
    content = data.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    parsed = json.loads(item.get("text", ""))
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(parsed, dict) and "kind" in parsed:
                    return parsed
    return None
