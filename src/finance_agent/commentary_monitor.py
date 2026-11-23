"""Optional commentary alerts; no scheduler or transport is installed."""
import fcntl
import json
import os
import sqlite3
from pathlib import Path

from .commentary_health import inspect_commentary
from .queue_monitor import _save_state


def check_and_notify(database: Path, state_path: Path, send) -> dict:
    """Serialize inspection/send/ack; sender must raise unless accepted remotely.

    Use a trusted private existing directory and a separate state per database.
    Remote acceptance followed by a local crash can duplicate alerts.
    """
    try:
        database = Path(database).resolve()
        state_path = Path(state_path).absolute()
        lock_path = Path(str(state_path) + '.lock')
        protected = [Path(str(database) + suffix)
                     for suffix in ('', '-wal', '-shm', '-journal')]
        for path in (state_path, lock_path):
            if (path.is_symlink() or path.resolve() in protected
                    or any(path.exists() and target.exists() and path.samefile(target)
                           for target in protected)):
                raise ValueError('Unsafe monitor path')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            if os.fstat(lock.fileno()).st_nlink != 1:
                raise ValueError('Unsafe lock')
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _check_locked(database, state_path, send)
    except (OSError, ValueError, RuntimeError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}


def _check_locked(database, state_path, send):
    # The private directory and cooperating lock protect state replacement.
    try:
        previous = (json.loads(state_path.read_text()) if state_path.exists()
                    else {'kind': 'commentary', 'database': str(database), 'failed': 0})
        if (not isinstance(previous, dict)
                or set(previous) != {'kind', 'database', 'failed'}
                or previous['kind'] != 'commentary'
                or previous['database'] != str(database)
                or type(previous['failed']) is not int or previous['failed'] < 0):
            raise ValueError('Invalid commentary state')
    except (OSError, ValueError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}
    try:
        health = inspect_commentary(database)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {'status': 'inspection_error', 'error_class': type(exc).__name__}
    if health['status'] not in {'failed_work', 'no_failed_work'}:
        return {**health, 'notification': 'none'}
    failed = health['counts'].get('failed', 0)
    result = {**health, 'notification': 'none'}
    if failed == previous['failed']:
        return result
    try:
        send('Finance commentary recovered: no failed work observed.' if not failed
             else f'Finance commentary alert: failed={failed}.')
    except Exception as exc:
        return {**health, 'notification': 'delivery_error',
                'error_class': type(exc).__name__}
    _save_state(state_path, {'kind': 'commentary', 'database': str(database), 'failed': failed})
    return {**health, 'notification': 'sent'}
