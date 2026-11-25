"""Standalone commentary-age monitor. Read-only dry run unless --notify is explicit."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

from .commentary_pending_health import inspect_pending
from .commentary_pending_monitor import check_pending
from .queue_monitor_cli import telegram_sender


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--notify', action='store_true')
    parser.add_argument('--threshold-seconds', type=int, default=900)
    args = parser.parse_args(argv)
    if args.threshold_seconds <= 0 or (args.state and not args.notify):
        result = {'status': 'configuration_error', 'error_class': 'ValueError'}
    elif args.notify:
        try:
            token = os.environ.get('FINANCE_MONITOR_BOT_TOKEN', '')
            chat = os.environ.get('FINANCE_MONITOR_CHAT_ID', '')
            if not args.state or not token or not chat or int(chat) == 0:
                raise ValueError('Explicit notification configuration required')
            sender = telegram_sender(token, int(chat))
        except (ValueError, TypeError) as exc:
            result = {'status': 'configuration_error', 'error_class': type(exc).__name__}
        else:
            result = check_pending(args.db, args.state, sender, threshold_seconds=args.threshold_seconds)
    else:
        try:
            result = {**inspect_pending(args.db, threshold_seconds=args.threshold_seconds), 'notification': 'dry_run'}
        except (sqlite3.Error, OSError, ValueError) as exc:
            result = {'status': 'inspection_error', 'error_class': type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    if (result['status'] not in {'pending_attention', 'no_aged_pending'}
            or result.get('notification') == 'delivery_error'):
        return 2
    return 1 if result['status'] == 'pending_attention' else 0


if __name__ == '__main__':
    raise SystemExit(main())
