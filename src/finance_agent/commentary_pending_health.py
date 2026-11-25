"""Read-only commentary age inspection using original receipt time as a proxy."""
import math
import sqlite3
import time
from pathlib import Path


def inspect_pending(path, *, now=None, threshold_seconds=900):
    if (type(threshold_seconds) not in (int, float)
            or not math.isfinite(threshold_seconds) or threshold_seconds <= 0):
        raise ValueError('Invalid threshold')
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('Invalid observation time')
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        required = {'summary_snapshots': {'update_id', 'status', 'next_attempt_at'},
                    'inbox_updates': {'update_id', 'created_at'}}
        for table, fields in required.items():
            columns = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
            if not columns:
                return {'status': 'unavailable'}
            if not fields <= columns:
                return {'status': 'legacy_schema'}
        rows = conn.execute("SELECT i.created_at,s.next_attempt_at FROM summary_snapshots s LEFT JOIN inbox_updates i ON i.update_id=s.update_id WHERE s.status='pending'")
        stats = dict(pending=0, old_pending=0, old_ready=0, old_backoff=0,
                     unknown_age=0, oldest_age_seconds=None, age_basis='inbox_receipt_proxy')
        oldest = None
        for created, retry in rows:
            stats['pending'] += 1
            if (type(created) not in (int, float) or not math.isfinite(created)
                    or created > now or created < 0):
                stats['unknown_age'] += 1
                continue
            age = now - created
            oldest = age if oldest is None else max(oldest, age)
            if age >= threshold_seconds:
                stats['old_pending'] += 1
                stats['old_backoff' if type(retry) in (int, float)
                      and math.isfinite(retry) and retry > now else 'old_ready'] += 1
        stats['oldest_age_seconds'] = int(oldest) if oldest is not None else None
        attention = stats['old_pending'] or stats['unknown_age']
        return {'status': 'pending_attention' if attention else 'no_aged_pending',
                'threshold_seconds': threshold_seconds, 'pending': stats}
    finally:
        conn.close()
