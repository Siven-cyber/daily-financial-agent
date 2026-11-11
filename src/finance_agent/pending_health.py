"""Read-only aged-pending inspection; no retry, discard or delivery."""
import argparse
import json
import math
import sqlite3
import time
from pathlib import Path


def inspect_pending(path: Path, *, now=None, threshold_seconds=900) -> dict:
    if (type(threshold_seconds) not in (int, float)
            or not math.isfinite(threshold_seconds) or threshold_seconds <= 0):
        raise ValueError('Invalid threshold')
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('Invalid observation time')
    conn = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        output = {}
        reply_columns = {r[1] for r in conn.execute('PRAGMA table_info(reply_outbox)')}
        has_timestamp = 'created_at' in reply_columns
        for label in ('inbox', 'outbox'):
            if label == 'inbox':
                source = 'inbox_updates r'
                age = 'r.created_at'
                blocked = "EXISTS (SELECT 1 FROM inbox_updates b WHERE b.user_id=r.user_id AND b.update_id<r.update_id AND b.status IN ('pending','failed'))"
            else:
                source = 'reply_outbox r LEFT JOIN inbox_updates i ON i.update_id=r.update_id'
                age = 'COALESCE(r.created_at,i.created_at)' if has_timestamp else 'i.created_at'
                blocked = "EXISTS (SELECT 1 FROM reply_outbox b WHERE b.update_id=r.update_id AND b.ordinal<r.ordinal AND b.status IN ('pending','failed'))"
            # Fetch only operational metadata. Never select identities or payloads.
            actual = 'r.created_at IS NOT NULL' if label == 'outbox' and has_timestamp else '0'
            rows = conn.execute(f"SELECT {age},r.next_attempt_at,{blocked},{actual} FROM {source} WHERE r.status='pending'").fetchall()
            stats: dict = dict(pending=len(rows), old_pending=0, old_ready=0,
                         old_backoff=0, old_blocked=0, unknown_age=0,
                         oldest_age_seconds=None,
                         age_basis='receipt' if label == 'inbox' else 'inbox_receipt_proxy')
            if label == 'outbox':
                count = sum(row[3] for row in rows)
                stats['actual_timestamp_count'] = count
                stats['receipt_proxy_count'] = len(rows)-count
                stats['age_basis'] = ('mixed' if 0 < count < len(rows) else
                                      'outbox_creation' if count else 'inbox_receipt_proxy')
            ages = []
            for created, retry_at, is_blocked, _ in rows:
                if (type(created) not in (int, float) or not math.isfinite(created)
                        or created > now):
                    stats['unknown_age'] += 1
                    continue
                age_seconds = now-created
                ages.append(age_seconds)
                if age_seconds < threshold_seconds:
                    continue
                stats['old_pending'] += 1
                if is_blocked:
                    stats['old_blocked'] += 1
                elif retry_at > now:
                    stats['old_backoff'] += 1
                else:
                    stats['old_ready'] += 1
            stats['oldest_age_seconds'] = int(max(ages)) if ages else None
            output[label] = stats
        attention = any(x['old_pending'] or x['unknown_age'] for x in output.values())
        return {'status': 'pending_attention' if attention else 'no_aged_pending',
                'threshold_seconds': threshold_seconds, **output}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--threshold-seconds', type=int, default=900)
    args = parser.parse_args()
    try:
        result = inspect_pending(args.db, threshold_seconds=args.threshold_seconds)
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        print(json.dumps({'status': 'inspection_error', 'error_class': type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result['status'] == 'pending_attention' else 0


if __name__ == '__main__':
    raise SystemExit(main())
