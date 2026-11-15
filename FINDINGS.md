# Building Blocks Tested and What We Learned

Submission notes for Cortensor Hackathon #5. Evidence is separated below into current
source review, previously recorded acceptance, and historical SDK experiments. These
are not interchangeable. No new provider call or Telegram delivery was performed as
part of the submission-documentation preparation.

## Current building blocks and evidence (OpenMinion 0.1.20)

| Building block | Current use and evidence | Remaining limitation |
|---|---|---|
| APIRuntime and submit_turn | Active adapter constructs a shared runtime and waits on bounded turn handles. | A final full Telegram workflow still needs demo acceptance. |
| Tool-free turns | Active recording uses answer() with an explicit empty tool allowlist. | Source intent and offline ingress checks do not prove adversarial model/tool enforcement. |
| Caller-owned delivery | Adapter sends deliver=False and caller_handles_delivery=true; application owns inbox/outbox. | Telegram remote acceptance followed by a local crash can still duplicate delivery. |
| Sessions | Versioned operation/caller-scoped keys. Prior synthetic same-session turns returned changed markers. | Session scoping is not the financial authorization boundary. |
| Provider configuration | Portal/gemma4 and custom OpenAI-compatible options. Prior isolated acceptance observed outbound alias lv/auto. | An auto alias does not prove the underlying selected model. |
| MCP and policy | Retained helper/configuration, historically exercised below. | Not the active recording path; no current MCP-execution claim. |

The previous 0.1.20 isolated model acceptance recorded two fresh-context turns and
validated proposals for `beli pentol 7rb` (7000 IDR, food) and `coffee $6.50`
(650 USD cents, food). Outbound HTTP instrumentation observed the requested alias
`lv/auto`. This is a maintainer-recorded bounded result, not a newly reproduced public
artifact or a Telegram end-to-end demonstration. The public demo must establish its
own selected backend and evidence. Offline application tests use synthetic fixtures;
they do not establish real-model reliability.

## Latest isolated acceptance

The selected custom backend alias `lv/gpt-6.1-terra` passed a real SDK interpretation
on 2026-11-15 in 5.35 seconds with a 180-second limit. Input `coffee 20rb` validated
as expense 20000 IDR, category food. A direct application-service write and readback
on a synthetic ledger produced one row and monthly expense 20000, income 0. Both
observed outbound model fields matched the alias. This does not establish Telegram,
integrated durable dispatch, or the underlying relay-selected model identity.

Earlier attempts remain relevant failures: lv/auto returned provider HTTP 400;
a raw Gemma4 baseline timed out; a subsequent Gemma4 SDK marker test completed in
143.88 seconds with a 300-second budget but included a secondary HTTP 502. The
purpose of that secondary call was not established. These observations support
reporting provider variability, not claiming unrestricted reliability or SDK defects.

## What we learned (actionable feedback)

- Runtime completion is not financial completion. Validate proposals and confirm a
  database readback before telling a user that a transaction was saved. SDK examples
  should distinguish final text, tool execution and authoritative application effects.
- Caller-managed transports need explicit delivery ownership. Document and demonstrate
  deliver=False together with caller_handles_delivery and two consecutive fresh turns.
- Make effective provider/model selection inspectable without exposing credentials.
  Configuration intent and an automatic routing alias are not underlying-model proof.
- Separate telemetry, message/session persistence and archives in privacy documentation.
  A previous offline 0.1.20 bootstrap recorded local diagnostic events despite
  telemetry_enabled=false; this bounded observation is not a claim about every runtime
  path or a security vulnerability. Persistent-state controls need separate tests.
- Show a small reproducible SDK sample with strict JSON validation, explicit tool
  restrictions, cancellation and caller-owned delivery. This is more useful here than
  adding unrelated delegation or memory solely for the hackathon.

## Historical experiments: OpenMinion 0.1.2 to 0.1.4

The remaining sections describe earlier Portal/gemma4 and custom OpenAI-compatible
experiments. Historical telemetry supported those observations. They have not all
been rerun on 0.1.20, and are not claims of current upstream defects. Issue status,
maintainer acknowledgement and any fix PR must be checked before bonus claims.

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

The original MCP workaround informed the design, but it is not today's recording
path. Current recording requests a strict JSON proposal through the SDK answer adapter;
the backend validates it, including amount/currency/direction, and keeps model-selected
categories only when valid. Supported edits and deletion intents have their own guarded
paths. Summary insights select allowlisted fact codes rendered by the backend; general
questions use model prose grounded in supplied aggregates. All authoritative ledger
access stays in the authenticated application backend. The model is not the system
of record and never selects the owner.

## Upstream issues filed

- openminion/openminion#248: @tool functions passed via `Agent(tools=...)` are never
  exposed to the model (0.1.3+).
- openminion/openminion#249: string return value of a @tool function reaches the model as
  empty output (0.1.2).
