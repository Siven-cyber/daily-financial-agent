"""Opt-in commentary-age alerts with independent, threshold-bound state."""
import fcntl
import json
import math
import os
import sqlite3
from pathlib import Path

from .commentary_pending_health import inspect_pending
from .queue_monitor import _save_state

FIELDS = ('old_ready', 'old_backoff', 'unknown_age')


def check_pending(database, state_path, send, *, now=None, threshold_seconds=900):
    """Do not mutate queues. A remote-accept/local-ack crash may duplicate alerts."""
    try:
        if (type(threshold_seconds) not in (int, float)
                or not math.isfinite(threshold_seconds) or threshold_seconds <= 0):
            raise ValueError('Invalid threshold')
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
            return _locked(database, state_path, send, now, threshold_seconds)
    except (OSError, ValueError, RuntimeError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}


def _locked(database, state_path, send, now, threshold):
    baseline = {'kind': 'commentary_pending_v1', 'database': str(database),
                'threshold_seconds': threshold, 'counts': [0] * len(FIELDS)}
    try:
        previous = json.loads(state_path.read_text()) if state_path.exists() else baseline
        if (not isinstance(previous, dict) or set(previous) != set(baseline)
                or any(previous[k] != baseline[k] for k in ('kind', 'database', 'threshold_seconds'))
                or type(previous['threshold_seconds']) not in (int, float)
                or not isinstance(previous['counts'], list) or len(previous['counts']) != len(FIELDS)
                or any(type(n) is not int or n < 0 for n in previous['counts'])):
            raise ValueError('Invalid commentary pending state')
    except (ValueError, OSError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}
    try:
        health = inspect_pending(database, now=now, threshold_seconds=threshold)
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        return {'status': 'inspection_error', 'error_class': type(exc).__name__}
    if health['status'] not in {'pending_attention', 'no_aged_pending'}:
        return {**health, 'notification': 'none'}
    counts = [health['pending'][field] for field in FIELDS]
    if counts == previous['counts']:
        return {**health, 'notification': 'none'}
    message = ('Finance commentary pending recovered: no aged or unknown-age pending work observed.'
               if not any(counts) else
               f'Finance commentary pending attention (threshold {threshold}s; not proof of a stalled worker). '
               + ', '.join(f'{field}={health["pending"][field]}' for field in FIELDS)
               + '. Age basis: inbox receipt proxy, which may overestimate commentary age.')
    try:
        send(message)
    except Exception as exc:
        return {**health, 'notification': 'delivery_error', 'error_class': type(exc).__name__}
    _save_state(state_path, {**baseline, 'counts': counts})
    return {**health, 'notification': 'sent'}
