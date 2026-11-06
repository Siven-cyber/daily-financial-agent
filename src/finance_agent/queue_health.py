"""Read-only queue counts. No payload, owner or exception-message disclosure."""
import argparse
import json
import sqlite3
from pathlib import Path


def inspect_queue(path: Path) -> dict:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        queues = {}
        for label, table in [('inbox', 'inbox_updates'), ('outbox', 'reply_outbox')]:
            queues[label] = dict(conn.execute(
                f'SELECT status,count(*) FROM {table} GROUP BY status'
            ).fetchall())
        return {'status': 'failed_work' if any(q.get('failed', 0) for q in queues.values()) else 'no_failed_work',
                'queues': queues}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = inspect_queue(args.db)
    except (sqlite3.Error, OSError, ValueError) as exc:
        print(json.dumps({'status': 'inspection_error', 'error_class': type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result['status'] == 'failed_work' else 0


if __name__ == '__main__':
    raise SystemExit(main())
