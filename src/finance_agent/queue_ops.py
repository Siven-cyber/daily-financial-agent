"""Explicit operator recovery and logical retention, without deleting ledger rows."""
from typing import Any
import time

_TARGETS = {'inbox': ('inbox_updates', 'update_id'), 'outbox': ('reply_outbox', 'id')}


class QueueOperations:
    def __init__(self, db: Any):
        self.db = db

    def _target(self, queue: str) -> tuple[str, str]:
        if queue not in _TARGETS:
            raise ValueError('Queue must be inbox or outbox')
        return _TARGETS[queue]

    def failed(self, queue: str) -> list[dict]:
        table, key = self._target(queue)
        with self.db.atomic():
            rows = self.db._conn.execute(f"SELECT {key} AS id,status,attempts,last_error FROM {table} WHERE status='failed' ORDER BY {key}").fetchall()
            return [dict(row) for row in rows]

    def retry(self, queue: str, row_id: int) -> bool:
        table, key = self._target(queue)
        with self.db.atomic():
            cur = self.db._conn.execute(f"UPDATE {table} SET status='pending',attempts=0,next_attempt_at=0,last_error=NULL WHERE {key}=? AND status='failed' AND payload<>'{{}}'", (row_id,))
            return cur.rowcount == 1

    def discard(self, queue: str, row_id: int) -> bool:
        """Explicit abandonment of a failed item; preserve its deduplication identity."""
        table, key = self._target(queue)
        with self.db.atomic():
            cur = self.db._conn.execute(f"UPDATE {table} SET status='discarded',payload='{{}}',last_error=NULL WHERE {key}=? AND status='failed'", (row_id,))
            return cur.rowcount == 1

    def cleanup(self) -> dict[str, int]:
        """Redact terminal data immediately; never age-delete pending/failed work."""
        with self.db.atomic():
            confirmations = self.db._conn.execute("UPDATE deletion_confirmations SET snapshot='',state='invalid' WHERE snapshot<>'' AND (expires_at<=? OR state<>'pending')", (time.time(),)).rowcount
            inbox = self.db._conn.execute("UPDATE inbox_updates SET payload='{}',last_error=NULL WHERE status IN ('done','discarded') AND payload<>'{}'").rowcount
            outbox = self.db._conn.execute("UPDATE reply_outbox SET payload='{}',last_error=NULL WHERE status IN ('sent','discarded') AND payload<>'{}'").rowcount
            return {'confirmations': confirmations, 'inbox': inbox, 'outbox': outbox}
