"""Read-only queue monitoring core with injected alert transport.

No scheduler, credentials or network transport is installed by this module.
"""
import fcntl
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Callable

from .queue_health import inspect_queue


def _read_state(path: Path, database: str) -> dict:
    if not path.exists():
        return {'database': database, 'failed': [0, 0]}
    state = json.loads(path.read_text())
    if (not isinstance(state, dict) or set(state) != {'database', 'failed'}
            or state['database'] != database
            or not isinstance(state['failed'], list) or len(state['failed']) != 2
            or any(type(n) is not int or n < 0 for n in state['failed'])):
        raise ValueError('Invalid monitor state')
    return state


def _save_state(path: Path, state: dict) -> None:
    fd, name = tempfile.mkstemp(prefix='.queue-monitor-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def check_and_notify(database: Path, state_path: Path,
                     send: Callable[[str], None]) -> dict:
    """Send only aggregate count changes/recovery, acknowledging after delivery.

    The caller supplies a trusted private existing directory and a synchronous
    sender that raises on delivery failure. It must use one state file per DB.
    The lock serializes overlapping cooperating monitors, including send/ack.
    A remote-accept/local-ack crash can duplicate an alert (at-least-once).
    """
    database, state_path = Path(database).resolve(), Path(state_path).absolute()
    # Never allow a state file/lock to replace the observed database or sidecars.
    protected = {str(database) + suffix for suffix in ('', '-wal', '-shm', '-journal')}
    if (str(state_path.resolve()) in protected or
            str(Path(str(state_path) + '.lock').resolve()) in protected or
            state_path.is_symlink()):
        return {'status': 'state_error', 'error_class': 'ValueError'}
    try:
        fd = os.open(str(state_path) + '.lock',
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _check_locked(database, state_path, send)
    except (OSError, ValueError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}


def _check_locked(database: Path, state_path: Path,
                  send: Callable[[str], None]) -> dict:
    try:
        previous = _read_state(state_path, str(database))
    except (OSError, ValueError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}
    try:
        health = inspect_queue(database)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {'status': 'inspection_error', 'error_class': type(exc).__name__}
    failed = [health['queues'][q].get('failed', 0) for q in ('inbox', 'outbox')]
    result = {**health, 'notification': 'none'}
    if failed == previous['failed']:
        return result
    message = ('Finance queue recovered: no failed work observed.' if not any(failed)
               else f'Finance queue alert: failed inbox={failed[0]}, failed outbox={failed[1]}.')
    try:
        send(message)
    except Exception as exc:
        return {**health, 'notification': 'delivery_error',
                'error_class': type(exc).__name__}
    _save_state(state_path, {'database': str(database), 'failed': failed})
    return {**health, 'notification': 'sent'}
