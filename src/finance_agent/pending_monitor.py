"""Opt-in aged-pending alerts, independent of the active failed-work monitor."""
import fcntl
import json
import os
import sqlite3
from pathlib import Path

from .pending_health import inspect_pending
from .queue_monitor import _save_state

FIELDS = ('old_ready', 'old_backoff', 'old_blocked', 'unknown_age')


def check_pending(database, state_path, send, *, now=None, threshold_seconds=900):
    """Use a separate private state path; never mutate queues or auto-retry work.

    Count/class changes trigger alerts, not growth in elapsed age alone. Remote
    acceptance followed by failed local acknowledgement can duplicate an alert.
    """
    database = Path(database).resolve()
    state_path = Path(state_path).absolute()
    protected = {str(database)+s for s in ('', '-wal', '-shm', '-journal')}
    if (str(state_path.resolve()) in protected or state_path.is_symlink()
            or str(Path(str(state_path)+'.lock').resolve()) in protected):
        return {'status': 'state_error', 'error_class': 'ValueError'}
    try:
        fd = os.open(str(state_path)+'.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _locked(database, state_path, send, now, threshold_seconds)
    except (OSError, ValueError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}


def _locked(database, state_path, send, now, threshold):
    baseline = {'kind': 'aged_pending_v1', 'database': str(database),
                'threshold_seconds': threshold, 'counts': [0]*8}
    try:
        previous = json.loads(state_path.read_text()) if state_path.exists() else baseline
        if (not isinstance(previous, dict) or set(previous) != set(baseline)
                or any(previous[k] != baseline[k] for k in ('kind', 'database', 'threshold_seconds'))
                or not isinstance(previous['counts'], list) or len(previous['counts']) != 8
                or any(type(n) is not int or n < 0 for n in previous['counts'])):
            raise ValueError('Invalid pending monitor state')
    except (ValueError, OSError) as exc:
        return {'status': 'state_error', 'error_class': type(exc).__name__}
    try:
        health = inspect_pending(database, now=now, threshold_seconds=threshold)
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        return {'status': 'inspection_error', 'error_class': type(exc).__name__}
    counts = [health[q][field] for q in ('inbox', 'outbox') for field in FIELDS]
    if counts == previous['counts']:
        return {**health, 'notification': 'none'}
    if not any(counts):
        message = 'Finance pending queue recovered: no aged or unknown-age pending work observed.'
    else:
        parts = [f'Finance pending attention (threshold {threshold}s; not proof of a stalled worker).']
        for q in ('inbox', 'outbox'):
            parts.append(q+': '+', '.join(f'{f}={health[q][f]}' for f in FIELDS)+'.')
        parts.append('Outbox age uses inbox receipt time as a proxy.')
        message = '\n'.join(parts)
    try:
        send(message)
    except Exception as exc:
        return {**health, 'notification': 'delivery_error', 'error_class': type(exc).__name__}
    _save_state(state_path, {**baseline, 'counts': counts})
    return {**health, 'notification': 'sent'}
