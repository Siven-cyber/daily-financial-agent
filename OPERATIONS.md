# Queue recovery and privacy

These commands apply only after the reviewed Phase B schema is deployed. Development approval does not authorize commands on the live database. Use the application's tested Python environment and PYTHONPATH=src from the repository root. No command reads .env or defaults to finance.db. Missing database paths are not created; inspection opens SQLite mode=ro without migrations.

Read failed work without printing financial payloads:

    python -m finance_agent.queue_cli --db /absolute/path/test.db list --queue inbox
    python -m finance_agent.queue_cli --db /absolute/path/test.db list --queue outbox

Explicit operator mutations, requiring production approval when applicable:

    python -m finance_agent.queue_cli --db /absolute/path/test.db --apply retry --queue inbox --id 7
    python -m finance_agent.queue_cli --db /absolute/path/test.db --apply retry --queue outbox --id 3
    python -m finance_agent.queue_cli --db /absolute/path/test.db --apply discard --queue inbox --id 7
    python -m finance_agent.queue_cli --db /absolute/path/test.db --apply cleanup

Retry only resets failed items. Completed or discarded updates cannot be reopened. Retry an inbox item only after its processing failure is understood. Retry an outbox item to resend the response without replaying the money mutation. Discard permanently abandons a failed item and removes its payload, while retaining its identifier as a deduplication tombstone. Discarding inbox work can mean a legitimate transaction will never be recorded; never do it automatically. The CLI requires --apply but does not replace operator authorization or a backup.

The bot retries automatically with bounded backoff, marks an item failed after eight attempts, and retains failed/pending payloads for explicit recovery. The operator must monitor both failed queues; no alerting integration is implemented yet.

## Retention

Completed inbox and sent outbox payloads are cleared immediately. Cleanup clears snapshots of consumed or expired confirmation tokens and keeps minimal deduplication metadata. It never deletes transaction history, sequence counters, pending payloads or failed payloads. The bot invokes logical cleanup at approximately one-minute intervals (long-running model calls can delay it).

New application DB/WAL/SHM files are restricted to mode 0600; opening an existing application database tightens permissions. This has not been run on the production DB. secure_delete is enabled for application connections, but logical redaction and SQLite secure_delete DO NOT guarantee physical erasure from WAL, filesystem snapshots, storage layers or backups. Never run VACUUM or destructive checkpoint maintenance against a live bot without a separate maintenance plan. Old backups require a separate approved retention policy.

## Backup and restore acceptance

A synthetic WAL database was copied using SQLite's backup API, restored to a separate path, then reopened. Transaction amount and durable delivery offset matched, quick_check returned ok, and foreign_key_check returned no violations. This does not certify production backup coverage. Before live migration: stop only finance-bot, create a private consistent backup, verify an isolated restore, run reviewed migration, compare counts and currency-separated totals, then start only after approval. Do not overwrite post-cutover writes with an old backup.

## Verification commands

    TMPDIR=/root/.hermes/cache/scratch PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
    TMPDIR=/root/.hermes/cache/scratch PYTHONDONTWRITEBYTECODE=1 python tests/test_parser.py
    TMPDIR=/root/.hermes/cache/scratch PYTHONDONTWRITEBYTECODE=1 python tests/test_db_service.py

The two legacy suites contain function tests and are not collected by unittest discovery, so all three commands are required. Model and Telegram acceptance must use explicitly approved synthetic data. Do not run a second Telegram poller beside production.
