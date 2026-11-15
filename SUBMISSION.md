# Daily Financial Agent: submission draft

Status: preparation only, not submitted. Video, final model-backed demonstration,
account participation checks and the destination submission PR remain outstanding.

## Project

- Public source: https://github.com/Siven-cyber/daily-financial-agent
- Setup and repeatable example: [README](README.md)
- Building Blocks Tested and What We Learned: [FINDINGS](FINDINGS.md)
- Recording script and acceptance gates: [DEMO](DEMO.md)
- SDK target: OpenMinion 0.1.20, exactly pinned in pyproject.toml.
- Demo video: pending recording and public-access verification.
- Selected backend: custom OpenAI-compatible endpoint, alias `lv/gpt-6.1-terra`.
- Isolated acceptance: 2026-11-15, OpenMinion 0.1.20; interpretation and synthetic
  ledger readback passed. Final integrated Telegram demo and demonstrated commit: pending.

## Useful outcome

A private-chat Telegram assistant records personal income and expenses in Indonesian
or English. Users select IDR or USD; money is stored as integer minor units and never
converted or combined across currencies. The narrow demonstration is one synthetic
expense, its persisted recent-list entry, and an authoritative monthly summary with
optional model-selected explanatory insights.

## Meaningful SDK workflow

1. The bot durably receives a private Telegram update and determines the owner.
2. The bounded worker calls the application adapter using OpenMinion APIRuntime and
   submit_turn. Active financial interpretation uses answer() with allowed_tools=[].
3. The model proposes strict JSON. The backend validates the schema, supported source
   amount, direction, currency and category; invalid proposals do not write money.
4. On the main thread, a validated proposal is committed with its readback-based reply
   and inbox completion. Application-owned outbox delivery sends the confirmation.
5. Summary totals are computed by the backend. AI chooses allowlisted insight facts;
   the backend renders them rather than trusting model-authored financial numbers.

OpenMinion is on the semantic runtime path, not just a declared dependency. Financial
writes, authenticated ownership, arithmetic and deletion confirmation remain trusted
application responsibilities. Historical MCP experiments are documented separately;
the retained MCP helper is not evidence of active recording tool execution.

## Evidence boundaries

Prior maintainer notes record isolated real-model acceptance on SDK 0.1.20 with the
requested alias lv/auto, including changed-context turns and IDR/USD proposals. Those
results do not replace the final demo, prove an underlying automatically routed model,
or establish current Telegram delivery. The new isolated preflight installed the public source copy and dependencies successfully,
but its real-model gate failed: the selected lv/auto endpoint returned HTTP 400 provider
errors, and the interpretation adapter rejected the non-JSON failure response. No
transaction was saved. This does not establish semantic model failure. Final workflow
and Telegram acceptance remain blocked, not passed.

A subsequent approved raw Portal/gemma4 synthetic baseline timed out at the client
after 150.65 seconds without a response. Authenticated model listing returned HTTP
200 and included gemma4, but that is not inference acceptance. No SDK finance turn
was attempted after this failed baseline, and no inference retry was launched.
Portal capacity and server-side completion remain unverified for that raw attempt.
A subsequent isolated SDK test with a Gemma4-only 300-second budget returned the
expected marker in 143.88 seconds, although its secondary request returned HTTP 502.
That establishes bounded SDK connectivity, not stable finance workflow acceptance.

The selected replacement `lv/gpt-6.1-terra` then passed isolated interpretation in
5.35 seconds with the normal 180-second limit. `coffee 20rb` validated as expense
20000 IDR, category food; the application service saved one synthetic row and read
back monthly expense 20000 and income 0. Both observed outgoing model fields matched
the selected alias. This is adapter plus direct service acceptance, not integrated
bot inbox/outbox or Telegram acceptance. Requested alias is verified; the underlying
relay-selected model has not been independently inspected.

The private synthetic test suite is deliberately excluded from publication. Juries
can reproduce the README workflow from public source; unpublished tests are not a
required setup step. No customer data or private operational evidence should be added.

## Required submission checks

- [x] Public project repository exists.
- [x] README includes setup and a bounded repeatable example.
- [x] SDK workflow, tested blocks and actionable lessons are documented.
- [ ] Independently verify fresh-checkout setup, including effective provider settings.
- [ ] Run the final synthetic workflow with a real model and verify saved records.
- [ ] Verify Telegram delivery separately from inference and database effects.
- [ ] Record and host a 1-5 minute video; verify unauthenticated viewing.
- [ ] Record the demonstrated commit, SDK, requested model alias and observed timings.
- [ ] Verify fork/clone/star of OpenMinion and GitHub/X follow actions requested by the event.
- [ ] Verify event registration and any DoraHacks Build submission requirements in the account UI.
- [ ] Confirm the official Hackathon #5 submission repository with the organizers.
- [ ] Submit the required PR and read back its URL/content before marking submitted.
- [ ] Review license packaging: pyproject declares MIT, but no LICENSE file is tracked.
- [ ] Review final diff, dependencies and demo frames for secrets/private data.

The reviewed official pages still describe the destination repository as forthcoming.
Do not guess it or assume an unrelated community-projects PR is sufficient. Account
registration and Build-form status have not been checked; the written rules explicitly
require the submission PR.

## Optional bonus, not a qualification blocker

Historical reports:
- https://github.com/openminion/openminion/issues/248
- https://github.com/openminion/openminion/issues/249

Recheck their current status and affected versions before claiming a current defect.
Bug-fix bonus requires a reproducible report, team acknowledgement/scope confirmation,
and a substantive fix attempt submitted as a PR. Reports alone do not qualify. No
bonus fix PR is claimed in this draft. Security-sensitive findings belong in private
reporting channels.

## Dependencies, disclosure and limitations

The project depends on OpenMinion, Telegram's Bot API, SQLite and a selected external
model provider. Setup supports Cortensor Portal/gemma4 and a custom OpenAI-compatible
backend; Portal/Gemma4 are optional under the event rules. Model calls can consume
credits and disclose synthetic transaction text to the selected provider. AI-assisted
development is permitted by the rules; the presenter must understand the workflow.

Natural-language edit/delete forms are bounded, not unrestricted language support.
General Q&A prose can be wrong; official aggregates remain authoritative. Outbox
transport is at-least-once, not guaranteed exactly-once Telegram delivery. SDK storage
and diagnostics are separate privacy controls; disabling telemetry is not proof of
zero persistence. No claim is made that all SDK building blocks were exercised.

## Event sources

- https://dorahacks.io/hackathon/2418/detail
- https://docs.cortensor.network/community-and-ecosystem/hackathon/hackathon-5

DoraHacks currently displays a cutoff equivalent to 2026-12-19 14:59 WIB. Recheck the
live event page before submission; the prose timeline labels December 18 in Pacific
Time. Awards and eligibility remain at the organizers' discretion.
