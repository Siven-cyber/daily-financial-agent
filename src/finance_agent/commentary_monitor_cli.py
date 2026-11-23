"""Standalone commentary monitor. Read-only dry run unless --notify is explicit."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

from .commentary_health import inspect_commentary
from .commentary_monitor import check_and_notify
from .queue_monitor_cli import telegram_sender


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--notify', action='store_true')
    args = parser.parse_args(argv)
    if args.state and not args.notify:
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
            result = check_and_notify(args.db, args.state, sender)
    else:
        try:
            result = {**inspect_commentary(args.db), 'notification': 'dry_run'}
        except (sqlite3.Error, OSError, ValueError) as exc:
            result = {'status': 'inspection_error', 'error_class': type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    if (result['status'] not in {'failed_work', 'no_failed_work'}
            or result.get('notification') == 'delivery_error'):
        return 2
    return 1 if result['status'] == 'failed_work' else 0


if __name__ == '__main__':
    raise SystemExit(main())
