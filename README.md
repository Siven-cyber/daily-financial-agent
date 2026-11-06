# Finance Agent

A personal finance logger as a Telegram bot, built on the
[OpenMinion 0.1 Python SDK](https://github.com/openminion/openminion). You chat with it
like a normal person ("makan siang 25rb", "salary 6m"), and it records your income and
expenses, answers questions, and sends monthly summaries. The bot speaks Indonesian and
English; the user picks the language on first contact.

Built for the Cortensor Hackathon #5. The project targets OpenMinion 0.1.18, checked against PyPI before the latest changes. Cortensor Portal (gemma4) and a custom OpenAI-compatible development backend are configurable. Live deployment is separate from source updates; see REMEDIATION.md.

## How it works

```
Telegram user ->  bot.py  ->  local parser (fast path, no model)      ->  SQLite (source of truth)
                           ->  OpenMinion agent (slow path)
                                 - interpret via MCP tool
                                 - answer questions / summaries
```

Two paths on purpose:

- **Fast path (no model).** A local parser (`parser.py`) understands Indonesian and
  English amount shorthand ("20rb", "1,5jt", "25k", "150.000") and records instantly.
  This keeps the common case fast and cheap, and it works even when the model backend is
  slow or down.
- **Model path (OpenMinion).** For free-form questions and summaries, the bot passes the
  numbers it already computed from the database to the agent, which phrases the answer.
  An experimental MCP interpretation tool exists, but the current Telegram handler does not call it for ambiguous logging; it asks for clarification instead.

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

Financial operations are restricted to private chats. Questions are routed before transaction parsing. Negative, multiple or ambiguous amounts are rejected. Transaction identifiers increase per user and are never reused after deletion. See OPERATIONS.md for durable inbox/outbox recovery and retention, and PHASE-B-DESIGN.md for migration/cutover constraints.

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
