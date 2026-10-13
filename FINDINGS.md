# Building Blocks Tested and What We Learned

Submission notes for Cortensor Hackathon #5. Everything here was observed on real runs
against OpenMinion 0.1.x with Cortensor Portal (gemma4) and, for faster iteration, an
OpenAI-compatible endpoint (deepseek-v4-pro). Telemetry quoted below is from the local
OpenMinion telemetry database.

## Building blocks tested

| Block | Result |
|---|---|
| Agent + APIRuntime (submit_turn, streaming) | Works. One runtime per process; streamed turns used for interpret and Q&A. |
| Providers (Cortensor Portal preset, gemma4) | Works. Configured via `openminion setup --provider cortensor-portal`. Slow (see below). |
| MCP tools (stdio server) | Works. Custom `interpret_transaction` tool reaches the model and executes. |
| Action policy (auto-approve rule) | Works. Rule `{"match": {"tool_name": ...}, "mode": "auto"}` lets the read-only tool run without a prompt. |
| Sessions | Works. One session id per Telegram user isolates state. |
| @tool-decorated Python functions via `Agent(tools=[...])` | Broken on 0.1.3/0.1.4 (see issue #248). We route around it with MCP. |
| `approval_callback` / streamed `resolve_approval` | Did not receive the MCP approval request (see below). |

## What worked

- The MCP path is the reliable way to give the model a custom tool on 0.1.4. The tool is
  exposed (`tool_schema_count=1`), the model calls it, the stdio server receives the call,
  and the structured output returns to the runtime.
- The Cortensor Portal preset works with no code changes; swapping providers is config only.
- gemma4 handled Indonesian amount shorthand correctly when called directly (for example
  "25rb" became `amount=25000` with a correct tool call).

## What broke (actionable feedback)

1. **`@tool` functions are never exposed to the model on 0.1.3+ (issue #248).**
   `Agent(tools=[decorated_fn])` sends the entry LLM call with `tool_schema_count=0`, the
   tool never runs, and the turn is still marked `agent.turn.completed`. Reproduced with
   the unmodified `examples/sdk/tool_agent.py`, in both daemon and single-process mode, on
   two providers. Permanent registration via `runtime.tools.add` did not help. Worked on
   0.1.2. Built-in tools (for example `time`) and MCP tools are fine, so it is specific to
   the decorated-tool registration path.

2. **`@tool` return value is dropped on 0.1.2 (issue #249).**
   On 0.1.2 the tool runs, but its string return value reaches the model as empty
   (`tool.call.completed` output `{"outputs": {}}`), so the model answers as if the tool
   returned nothing. Over MCP on 0.1.4 the output does reach the runtime, so the MCP path
   avoids this too.

3. **MCP tool approval could not be resolved programmatically.**
   A write-capable MCP tool was blocked by an `UNKNOWN_REVERSIBILITY` confirmation. Neither
   `agent.run(approval_callback=...)` nor `submit_turn().stream()` + `resolve_approval()`
   received the request; it only came back as plain final text asking the user to reply
   "allow_once". An `action_policy` auto-rule was the only way to let it run unattended.
   For a bot, that means the documented approval hooks did not work for MCP tools.

4. **`openminion mcp add` wrote to the global config by default.**
   Without `--config`, `mcp add` wrote to `~/.openminion/agents.json` instead of the
   project-local `./.openminion/agents.json` the runtime was using, so the server appeared
   "added" but was not visible. Passing `--config` to every subcommand fixed it.

5. **Portal latency and the default turn timeout.**
   gemma4 on Portal took roughly 45 to 55 seconds per call, and OpenMinion makes more than
   one model call per turn (entry plus a freshness-classify fallback). With the default
   `chat_turn_timeout_seconds=90`, SDK turns timed out. We raised it to 300. Portal also
   kept processing a request (logged 435.8s, HTTP 504 "Router timeout") after the client
   had already cancelled at 330s, and returned HTTP 502 "model tool contract violation" on
   some turns where a direct curl with the same tool succeeded.

6. **Agent instructions did not reliably steer the final text.**
   With a "finance logger" system prompt, the model's free-form reply often drifted (for
   example into lunch recommendations) instead of confirming the record. Not yet filed as
   an issue; needs an isolated repro. The bot does not depend on the model's free text for
   money: confirmations are composed from the database row, not the model.

## Design consequences

Because of items 1, 2, and 6, the bot treats the model as a language helper, not a system
of record. All writes and verification happen in `db.py`, keyed to the authenticated
Telegram user id. The model interprets ambiguous language (via the MCP tool) and phrases
summaries, but it never decides what is stored or whose data is touched.

## Upstream issues filed

- openminion/openminion#248: @tool functions passed via `Agent(tools=...)` are never
  exposed to the model (0.1.3+).
- openminion/openminion#249: string return value of a @tool function reaches the model as
  empty output (0.1.2).
