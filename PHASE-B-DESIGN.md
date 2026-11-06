# Phase B: durable transaction safety

Status: implemented and offline-tested; live migration and deployment remain unapproved. See REMEDIATION.md for tested scope and remaining prerequisites.
OpenMinion latest stable checked against PyPI: 0.1.18.

## Scope and invariants

Preserve existing users, amounts, currencies, dates and visible transaction numbers. Do not renumber or modify historical money. Develop against synthetic SQLite databases only. Existing Phase A changes remain undeployed.

### 1. Monotonic per-user sequence

Add user_sequences(user_id PRIMARY KEY, last_seq INTEGER NOT NULL). Initialize from each user's current MAX(seq), without rewriting transactions. Allocate and increment the sequence in the same BEGIN IMMEDIATE transaction as the insert, so a failed insert rolls back the allocation. Deletion never lowers the sequence. Across multiple connections, writer serialization plus the primary key protects allocation.

Historical deleted IDs cannot be reconstructed. Existing del:<seq> callbacks MUST be rejected after cutover; users must request a new confirmation. This is necessary even with monotonic allocation because older buttons may already refer to a reused ID.

### 2. Single-use deletion confirmation

Add deletion_confirmations(token TEXT PRIMARY KEY, user_id, chat_id, seq, snapshot TEXT, expires_at, state). Generate tokens using secrets.token_urlsafe; use UTC expiry, proposed TTL 5 minutes. Bind to authenticated sender, private chat, current target row snapshot and the confirmation message ID once Telegram returns it. Store the confirmation before sending and mark it sent only when a message ID is available; unsent tokens cannot execute. Callback formats use a new prefix distinct from legacy del:/delcancel:.

Confirm uses one BEGIN IMMEDIATE transaction: validate pending state, owner/chat/message, expiry and unchanged row snapshot; delete the exact owned row and consume the token. Cancel consumes the token without deleting. Replays, expired confirmations, old callbacks, another user/chat, and edits after preview never delete anything. Use localized expiry/invalid-state replies. A failed Telegram acknowledgement must not undo an already committed deletion.

### 3. Durable Telegram inbox and reply outbox

Add inbox_updates(update_id PRIMARY KEY, payload TEXT, status, attempts, next_attempt_at, last_error, created_at), plus reply_outbox(id PRIMARY KEY, update_id, ordinal, payload TEXT, status, attempts, next_attempt_at, UNIQUE(update_id, ordinal)). Persist a received batch before advancing Telegram's acknowledged offset. Read durable offset from stored batch receipt, not transient iterator state. Deduplicate update IDs using database uniqueness.

For deterministic local mutations: transaction creation/edit/delete, inbox completion and confirmation outbox insertion share one database transaction. Network operations NEVER run while that transaction is open. Crash before commit permits retry; crash after commit retries only the outbox, never the mutation. Outbox send failures retain the reply for bounded retry with backoff. Telegram sendMessage has no caller idempotency key, so crash after successful send but before marking sent can duplicate a reply; document this limitation rather than promise exactly-once delivery. Financial mutations must remain exactly-once per accepted update.

Questions do not mutate money. Keep model calls outside database transactions, and do not infer financial write success from model text. Queue isolation/concurrency enhancements belong to Phase C.

Inbox raw payloads contain personal data. Minimize stored fields, redact last_error, restrict file permissions, and define retention before deployment. Do not silently drop failed updates after retry exhaustion; retain visible failed state for operator review.

### 4. Transactions and migrations

Use explicit transaction boundaries and rollback on BaseException, including cancellation. Avoid nested implicit commits and executescript inside a transaction. Refactor migration execution into transactional individual statements with schema version tracking. Preserve historical fixtures for pre-currency and pre-composite layouts, ensure indexes are recreated after table rebuild, and test rollback after injected faults.

## Offline acceptance tests

- Replay identical update before and after application reconstruction: exactly one money mutation.
- Simulate failure before commit, after commit/before reply, and failed reply: no lost or duplicated financial record.
- Concurrent writes from separate SQLite connections: unique monotonic user sequences.
- Delete highest/all records, restart, insert: numbers never reused after migration.
- Old deletion callback after cutover: never executes.
- Confirm twice, cancel then confirm, expired token, wrong user/chat/message, edited target: no unintended deletion.
- Confirm valid current token: exact target removed once and confirmation queued atomically.
- Migration preserves rows, totals, currencies and visible seq; repeated migration is idempotent.
- Fault-injected migration restores original schema/data; quick_check and foreign_key_check pass on fixtures.
- Existing Phase A tests remain green on OpenMinion 0.1.18.

## Production cutover (not authorized)

1. Separate explicit approval for maintenance window and migration.
2. Stop only finance-bot, create consistent SQLite backup via SQLite backup API with private permissions, record hash, and verify restoration to an isolated path.
3. Run reviewed migration once; compare counts, currency-separated totals and row fingerprints without printing customer details.
4. Install tested dependency pin in live venv only with deployment approval, start bot, verify health and synthetic owner-approved Telegram checks.
5. On failure stop bot and follow reviewed rollback. Restoring an old DB after new writes can lose records; never blindly overwrite post-cutover activity.

Do not deploy Phase A alone while assuming Phase B issues are resolved. No production migration or service restart has been performed.
