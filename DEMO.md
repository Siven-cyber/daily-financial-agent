# Demo script and acceptance gates

Draft only. No video or new live acceptance is claimed by this document.
Target: a 3-4 minute English presentation within the official 1-5 minute limit.

## Before recording

Obtain separate approval for real provider calls and Telegram delivery. Use a separate
demo bot, private chat, fresh synthetic ledger and isolated SDK state, not customer
state. Follow the README in a fresh private checkout. Do not regenerate the running
bot configuration, restart production or delete historical records for a clean take.

Record the exact commit and installed SDK. Verify the selected provider and requested
model alias from sanitized outbound metadata or a correlated provider record. Never
show authorization headers, tokens, .env, generated private configuration, session
archives or raw production logs. An auto alias proves the request alias only.

Use a fresh ledger and select English then IDR. Preflight `coffee 20rb` with the chosen
model. Verify the final confirmation and the ledger row before recording. If the
model clarifies or fails, preserve that outcome in acceptance notes; a successful
repeat does not erase the failure. Fix or disclose any blocker before a qualification
claim. Do not replace a failed live run with fabricated replies.

## Recording sequence

### 0:00-0:25: problem and project

Show the public project page and private demo bot.

Suggested narration:
"Daily Financial Agent turns a private Telegram message into a personal finance
record. It supports Indonesian and English, with separate IDR and USD ledgers.
OpenMinion interprets the message; the backend owns money and authorization."

### 0:25-1:35: real model-backed recording

Show `/start`, English and IDR selections. Send `coffee 20rb`, then wait for the
processing reply and final saved confirmation. Keep visible that inference is real.

Suggested narration:
"This message goes through OpenMinion APIRuntime. The model proposes JSON, but cannot
write the ledger. The backend checks the amount, currency, direction and category.
The saved confirmation is built from a database readback."

Show sanitized evidence of the requested alias and one persisted synthetic row if
available. Do not imply that the source/config screen alone proves inference.

### 1:35-2:30: useful, repeatable result

Send `/recent`, wait for the official list and any subsequent insight. Send `/summary`
and wait for the official summary. For a ledger containing only the demo expense,
verify expense is 20,000 IDR and income is zero. Do not imply that these are measured
results until the actual run passes.

Suggested narration:
"The backend computes these totals. Summary commentary is selected from allowed
facts using the same saved aggregate snapshot. If commentary fails, the official
numeric summary is still available. Currencies are never summed or converted."

### 2:30-3:20: SDK contribution and lessons

Show the small relevant source sections: FinanceAgent.answer in agent.py,
interpretation.interpret and validate_proposal, and the findings document.

Suggested narration:
"OpenMinion is in the interpretation and answer path. We use explicit tool-free
turns and caller-owned delivery. Earlier MCP and decorated-tool experiments are
reported with their affected versions, not presented as current defects. A useful
lesson was to distinguish runtime completion from a verified financial write."

### 3:20-3:45: close

Show public source, setup instructions and findings links.

Suggested narration:
"The repository includes setup instructions and a repeatable synthetic example.
The model handles language; authenticated ownership, exact money and confirmations
remain in the application. The findings document lists tested blocks and limitations."

## Timing and editing rules

These are planned time slots, not measured latency. Rehearse with the selected backend.
Portal/Gemma4 may require more time than a custom endpoint. If waiting is trimmed or
sped up, visibly label it and disclose actual elapsed time; never present an edited
response as real-time. Do not squeeze many unrelated features into the video.
If total duration exceeds five minutes, simplify the narrative rather than inventing
fast results or silently swapping the backend. A shorter recording + summary workflow
is sufficient; general Q&A and edit/delete demonstrations are optional.

## Acceptance record to complete after the run

- Demonstrated commit and SDK version:
- Date/time and reporting timezone:
- Selected provider and observed requested alias:
- Evidence source for the alias, without credentials:
- Recording input and validated persisted row:
- Official recent/summary values:
- Model completion latency versus Telegram delivery latency:
- Failed/clarified attempts and remaining limitations:
- Evidence that only synthetic state was used:
- Video URL, measured duration and unauthenticated-view check:

Leave these blank until observed. Publishing a video, posting a PR or sending messages
requires its own approval; preparing this script does not authorize those actions.
