"""Queue operator CLI. Explicit database path; mutations require --apply."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from .queue_ops import QueueOperations


class Connection:
    def __init__(self, path: Path, write: bool):
        self._conn = sqlite3.connect(path.resolve().as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True)
        self._conn.row_factory = sqlite3.Row
        self.write = write
    @contextmanager
    def atomic(self):
        self._conn.execute('BEGIN IMMEDIATE' if self.write else 'BEGIN')
        try:
            yield
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Authorize a database mutation')
    parser.add_argument('action', choices=['list', 'retry', 'discard', 'cleanup'])
    parser.add_argument('--queue', choices=['inbox', 'outbox'], default='inbox')
    parser.add_argument('--id', type=int)
    args = parser.parse_args(argv)
    if args.action != 'list' and not args.apply:
        parser.error('Mutation requires --apply; use list for read-only inspection')
    if args.action in ('retry', 'discard') and (args.id is None or args.id < 0):
        parser.error('retry/discard requires a non-negative --id')
    db = Connection(args.db, args.action != 'list')
    try:
        ops = QueueOperations(db)
        if args.action == 'list':
            result = ops.failed(args.queue)
        elif args.action == 'cleanup':
            result = ops.cleanup()
        else:
            result = {'changed': getattr(ops, args.action)(args.queue, args.id)}
        print(json.dumps(result))
    finally:
        db._conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
