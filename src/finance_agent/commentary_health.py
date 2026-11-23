"""Read-only optional commentary counts, independent of foreground monitors."""
import argparse
import json
import sqlite3
from pathlib import Path


def inspect_commentary(path: Path) -> dict:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        columns = {row[1] for row in conn.execute('PRAGMA table_info(summary_snapshots)')}
        if not columns:
            return {'status': 'unavailable', 'counts': {}}
        if 'status' not in columns:
            return {'status': 'legacy_schema', 'counts': {}}
        counts = dict(conn.execute('SELECT status,count(*) FROM summary_snapshots GROUP BY status'))
        return {'status': 'failed_work' if counts.get('failed', 0) else 'no_failed_work',
                'counts': counts}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = inspect_commentary(args.db)
    except (sqlite3.Error, OSError, ValueError) as exc:
        print(json.dumps({'status': 'inspection_error', 'error_class': type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    if result['status'] in ('unavailable', 'legacy_schema'):
        return 2
    return 1 if result['status'] == 'failed_work' else 0


if __name__ == '__main__':
    raise SystemExit(main())
