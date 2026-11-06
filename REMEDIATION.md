# Audit remediation status

## Phase A (2026-11-06)

Implemented in source, NOT deployed:

- Ignore non-private Telegram messages and callbacks before accessing financial data.
- Route questions before the transaction-writing parser.
- Parse edits in the owned transaction's original currency, not the user's current selection.
- Reject negative, multiple, incompatible-suffix, malformed and overflowing amounts; use Decimal for amount parsing.
- Bound currency words to avoid false positives such as AUD inside audio.
- Prevent suffixes from consuming the beginning of the next word.
- Reject non-integer and out-of-range amounts before transaction insertion/update.

Verification: 15 parser tests + 15 DB/service tests + 7 safety regression tests passed with both installed OpenMinion 0.1.4 and isolated OpenMinion 0.1.18. Regression failures were observed before fixes. Tests use synthetic data only. API imports/signatures for APIRuntime.from_config_path and submit_turn checked on 0.1.18. No live model/Telegram E2E acceptance has been performed. git diff --check passed.

OpenMinion latest stable was queried directly from PyPI: 0.1.18. Project dependency pin updated to 0.1.18; the running bot's venv remains 0.1.4 until a separately approved deployment. Isolated validation environment: /root/.hermes/cache/scratch/finance-openminion-latest. Always check latest stable when resuming development, then verify compatibility before deployment.

Upstream changelog says decorated tools, returned tool outputs, approval events, empty tool allowlists and cancellation received fixes after the original 0.1.4 investigation. FINDINGS.md records historical observations; do not assume those SDK defects remain in 0.1.18 without retesting.

## Phase B implementation (not deployed)

Durable receipt offset and inbox deduplication, transactional financial mutations with reply outbox, bounded failed-item retry, monotonic per-user IDs, transactional versioned migrations and rollback, and single-use expiring deletion confirmations are implemented. Confirmation tokens are bound to owner/chat/sent message and transaction snapshot; old buttons are rejected. Cancellation consumes the token. Non-private content is discarded before persistence.

Validation on isolated OpenMinion 0.1.18: 30 unittest cases plus the two legacy suites (15 parser and 15 DB/service) pass. Covered concurrent SQLite connections, legacy migration idempotence/index checks, fault-injected migration rollback, expired/changed/cancelled/replayed confirmations, integrated send/bind/delete, repeated updates after processor reconstruction, and reply failure without repeated money writes. No real Telegram/model calls or production DB migration performed.

Single-process delivery remains intentional; running multiple poller/outbox workers is not supported. Financial mutations are deduplicated; Telegram replies can duplicate across the send/mark crash window. Retention policy, private file permissions, failed-queue operator tooling and live backup/restore acceptance remain deployment prerequisites. Raw completed inbox/outbox payloads are cleared, but SQLite WAL/free-page persistence and confirmation snapshots still need retention/privacy treatment. Phase C concurrency and model behavior remain unverified.

## Remaining work

- Production acceptance for Phase B and operator monitoring/alerts. Queue recovery CLI, logical retention and private file modes are implemented and tested offline; see OPERATIONS.md. Latest run: 35 unittest cases plus 15 parser and 15 DB/service tests passed on OpenMinion 0.1.18. CLI was exercised against a synthetic file: list, unauthorized-mutation rejection, retry and cleanup passed. Production DB permissions and data remain unchanged.
- Currency-scoped budgets and explicit reporting timezone.
- MCP generated path repair, currency-aware integration and log redaction.
- Explicit answer tool allowlist and tested cancellation/concurrency behavior.
- Polling backoff, output chunking and agent queue limits.
- Dependency advisory scan, CI/lockfile and backup restoration proof.

No production customer rows were changed and no service was restarted. Schema changes and deployment require separate approval. Full initial audit: /root/.hermes/cache/scratch/daily-financial-agent-audit-2026-11-06.md.
