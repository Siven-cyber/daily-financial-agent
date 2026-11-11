"""Queue monitor CLI. Dry-run unless --send is explicitly supplied."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

from .queue_health import inspect_queue
from .queue_monitor import check_and_notify
from .telegram_client import TelegramClient


def telegram_sender(token: str, chat_id: int):
    """Return a sender that acknowledges only accepted Telegram messages."""
    client = TelegramClient(token, timeout=15)

    def send(text: str) -> None:
        response = client.send_message(chat_id, text, parse_mode=None)
        if (not isinstance(response, dict) or response.get('ok') is not True
                or not isinstance(response.get('result'), dict)
                or type(response['result'].get('message_id')) is not int):
            raise RuntimeError('Telegram notification rejected')
    return send


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--pending', action='store_true', help='Opt in to aged-pending monitoring with a separate state file')
    parser.add_argument('--threshold-seconds', type=int, default=900)
    args = parser.parse_args(argv)
    if args.send:
        token = os.environ.get('FINANCE_MONITOR_BOT_TOKEN', '')
        chat = os.environ.get('FINANCE_MONITOR_CHAT_ID', '')
        try:
            if not args.state or not token or not chat:
                raise ValueError('Explicit notification configuration required')
            chat_id = int(chat)
            if chat_id == 0:
                raise ValueError('Invalid destination')
            sender = telegram_sender(token, chat_id)
        except (ValueError, TypeError):
            print(json.dumps({'status': 'configuration_error'}))
            return 2
        if args.pending:
            from .pending_monitor import check_pending
            result = check_pending(args.db, args.state, sender,
                                   threshold_seconds=args.threshold_seconds)
        else:
            result = check_and_notify(args.db, args.state, sender)
    else:
        try:
            if args.pending:
                from .pending_health import inspect_pending
                health = inspect_pending(args.db, threshold_seconds=args.threshold_seconds)
            else:
                health = inspect_queue(args.db)
            result = {**health, 'notification': 'dry_run'}
        except (sqlite3.Error, OSError, ValueError) as exc:
            result = {'status': 'inspection_error', 'error_class': type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    if (result['status'] in {'inspection_error', 'state_error'}
            or result.get('notification') == 'delivery_error'):
        return 2
    return 1 if result['status'] in {'failed_work', 'pending_attention'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
