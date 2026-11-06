# Finance Agent

A personal finance logger as a Telegram bot, built on the
[OpenMinion 0.1 Python SDK](https://github.com/openminion/openminion). You chat with it
like a normal person ("makan siang 25rb", "salary 6m"), and it records your income and
expenses, answers questions, and sends monthly summaries. The bot speaks Indonesian and
English; the user picks the language on first contact.

Built for the Cortensor Hackathon #5. The project targets OpenMinion 0.1.18, checked against PyPI before the latest changes. Cortensor Portal (gemma4) and a custom OpenAI-compatible development backend are configurable. Live deployment is separate from source updates.

## How it works

```
Telegram -> durable inbox -> bounded OpenMinion worker
                              -> validated transaction proposal -> SQLite + reply outbox
                              -> grounded financial question    -> reply outbox
```

- **AI-first recording.** Every supported free-text transaction is interpreted by
  OpenMinion. The backend validates the JSON schema, currency, category, amount and
  transaction direction before committing. The local parser validates amount safety;
  it does not select the stored category or provide a recording fallback.
- **Failure handling.** Invalid or ambiguous proposals prompt clarification. Runtime
  failures retain the durable input for bounded retry. No financial write occurs on
  interpretation failure. Model calls run outside SQL transactions.
- **Grounded answers.** Questions receive backend-computed daily and monthly context.
  Slash edit/delete and onboarding remain deterministic.
  `/recent` (`/terakhir`) first queues the unchanged last 10 transactions, then adds
  AI-selected insights from aggregates of exactly that displayed window. Notes,
  transaction IDs, dates and owner identity are excluded from model context.
  Each currency is aggregated separately; insights never imply monthly/all-history
  totals. Invalid output or model failure leaves the official list available.
  Both read-only insight paths reuse durable snapshots and outbox ordering.
  `/summary` (`/ringkasan`) first queues the unchanged authoritative numeric summary,
  then asks AI to select one or two explanatory fact codes from the same durable
  aggregate snapshot. The backend validates that selection and renders localized
  ID/EN prose; model prose, numbers, unknown fields and duplicate fields are rejected.
  Empty ledgers support an explicit no-recorded-activity insight. Failure or timeout
  leaves the official summary available without recursively calling AI.
  Summary periods use half-open WIB (`Asia/Jakarta`) calendar-month boundaries,
  converted to UTC for queries; currencies are never combined or converted.
  Only aggregates, currency, explicit month and selected language reach the summary
  model, not notes, owner identity or arbitrary historical category labels.
  Summary snapshots and official outbox chunks are committed before inference;
  restart/retry reuses the snapshot and stable ordinals, then removes it on completion.
  The bounded single worker performs no SQL or Telegram calls. Inference can consume
  provider credits and take up to the adapter's 180-second deadline. Other owners'
  deterministic commands continue while it runs. A crash before completion may repeat
  inference, but not create duplicate outbox rows. Telegram itself has no idempotency
  key: a crash after remote acceptance but before local acknowledgement can still
  redeliver a message (existing at-least-once transport limitation).
  Confirmation buttons and reply retries do not invoke the model again.
- **AI edits (amount/category only).** Use `change #1 to $6.50`,
  `ubah #1 menjadi 25rb`, `change coffee category food`, or
  `ubah terakhir kategori makan`. References are an explicit `#id`, an exact unique
  note (case-insensitive), or `last`/`terakhir` (highest owned sequence). Ambiguity
  requests clarification rather than guessing. One field changes per request.
  Category input is conservatively limited to one alphabetic word; AI chooses the
  stored category code. Unsupported edit/delete phrases are intercepted before
  recording. This is a bounded grammar, not arbitrary-language coverage.
  The model receives only the scoped target snapshot, never an owner id; the backend
  rechecks status, full snapshot and reference resolution before an atomic edit,
  readback confirmation, outbox enqueue and inbox completion. New amounts must match
  the source exactly in the original transaction currency. `/edit` remains unchanged
  and amount-only.
- **AI deletion requests, never AI deletion execution.** Use `hapus transaksi pentol terakhir`,
  `delete last pentol`, `delete #1`, `hapus terakhir`, or `delete coffee` (exact unique
  case-insensitive note). `last` means highest owned sequence, including for a matching
  note. The backend resolves targets; the model validates intent only using strict
  JSON with no tools, identity or target fields. Negated, question, conditional,
  compound, bulk and ambiguous requests clarify, never record or create a confirmation.
  This deliberately bounded grammar is not arbitrary-language understanding.
  Inference runs outside SQL on the existing bounded worker. Completion rechecks the
  pending inbox, full target snapshot and original reference, then atomically queues
  the existing confirmation capability and completes the inbox. Nothing is deleted
  until the user presses the confirmation button on its delivered preview (amount,
  localized category and note). The single-use capability is bound to user/chat/message,
  expires after five minutes, and rejects a changed target. `/delete` remains supported.
- **Latency and privacy.** Recording, supported edits and deletion intent validation
  consume provider credit and send entry text (plus the selected transaction snapshot for edits) to the configured
  model. The bot sends a processing reply while inference runs. Tests are synthetic;
  model interpretation, Telegram delivery and production deployment need separate approval.

**Money safety.** The database (`db.py`) is the single source of truth. The user is always
identified by the authenticated Telegram `user_id`, never by anything the model produces,
so one user can never read or write another user's data. Every write is read back from the
database before the bot confirms it, so the bot never reports a save it cannot verify.

## Setup

Requirements: Python 3.11+, a Telegram bot token from @BotFather, and a Cortensor Portal
API key.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, CORTENSOR_API_KEY

# build the OpenMinion config (Cortensor Portal + MCP finance server + auto-approve rule)
bash openminion/setup_agent.sh

python -m finance_agent.bot
```

## Commands

- Send plain text to log a transaction: `kopi 20rb`, `gajian 6jt`, `lunch 25k`
- `/summary` (`/ringkasan`): this month's totals and category breakdown
- `/recent` (`/terakhir`): last 10 transactions
- `/language` (`/bahasa`): change language
- `/currency` (`/matauang`): choose IDR or USD, without converting historical records
- `/edit <id> <amount>` (`/ubah`): edit using the original transaction currency
- `/delete <id>` (`/hapus`): request a single-use deletion confirmation
- `/help`: help

Financial operations are restricted to private chats. Questions are routed before transaction parsing. Negative, multiple or ambiguous amounts are rejected. Transaction identifiers increase per user and are never reused after deletion. Production migration requires a consistent backup, isolated restore verification, and explicit operator approval.

## Tests

```bash
python -m unittest discover -s tests -v
python tests/test_parser.py
python tests/test_db_service.py
```

## OpenMinion building blocks used

- **Agent + runtime** (`openminion.api.APIRuntime`, `submit_turn`): one shared runtime per
  process; streamed turns for both interpretation and question answering.
- **MCP tools** (stdio server): a custom `interpret_transaction` tool exposed to the model.
- **Action policy**: an auto-approve rule for the read-only interpret tool, so routine
  interpretation runs without a prompt, while write/destructive tools would still prompt.
- **Sessions**: one session id per Telegram user, isolating conversational state.
- **Providers**: the Cortensor Portal preset (gemma4), configured without code changes.

See `FINDINGS.md` for historical 0.1.3/0.1.4 observations and upstream issues. Those findings are not evidence that newer releases retain the same defects. Current finance tests on 0.1.18 are offline acceptance only, not proof of real-model/tool compatibility.
