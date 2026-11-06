"""Apply durable Telegram updates and send replies after committing money writes."""
from __future__ import annotations

import logging
from typing import Any

from .delivery import DeliveryStore

logger = logging.getLogger(__name__)


class DeferredQuestion(Exception):
    def __init__(self, args: tuple, kwargs: dict):
        self.args_to_call = args
        self.kwargs_to_call = kwargs


class ReplyCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict:
        self.calls.append(('sendMessage', {'chat_id': chat_id, 'text': text, **kwargs}))
        return {'ok': True, 'result': {}}

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict:
        self.calls.append(('answerCallbackQuery', {'callback_query_id': callback_query_id, 'text': text}))
        return {'ok': True}


class UpdateProcessor:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.store = DeliveryStore(bot._db)

    def receive(self, updates: list[dict]) -> None:
        self.store.receive(updates)

    def _save_replies(self, update: dict, collector: ReplyCollector) -> None:
        subject = update.get('message') or update.get('callback_query') or {}
        user_id = subject.get('from', {}).get('id') or 0
        for ordinal, (method, payload) in enumerate(collector.calls):
            self.store.enqueue(update['update_id'], ordinal, method, payload, user_id)
        self.store.complete(update['update_id'])

    def process_pending(self) -> None:
        for update in self.store.pending_updates():
            real_transport = self.bot._tg
            answer_question = self.bot._answer_question
            collector = ReplyCollector()
            def defer(*args: Any, **kwargs: Any) -> None:
                raise DeferredQuestion(args, kwargs)
            self.bot._tg = collector
            self.bot._answer_question = defer
            try:
                try:
                    with self.bot._db.atomic():
                        # Recheck inside the write transaction, including other workers.
                        row = self.bot._db._conn.execute('SELECT status FROM inbox_updates WHERE update_id=?', (update['update_id'],)).fetchone()
                        if row is None or row[0] != 'pending':
                            continue
                        self.bot.handle_update(update)
                        self._save_replies(update, collector)
                except DeferredQuestion as question:
                    # No network/model I/O inside the financial transaction.
                    collector.calls.clear()
                    answer_question(*question.args_to_call, **question.kwargs_to_call)
                    with self.bot._db.atomic():
                        self._save_replies(update, collector)
            except Exception as exc:
                self.store.fail_update(update['update_id'], exc)
                logger.warning('update processing failed: %s', type(exc).__name__)
            finally:
                self.bot._tg = real_transport
                self.bot._answer_question = answer_question

    def deliver_pending(self) -> None:
        for reply in self.store.pending_replies():
            payload = reply['payload']
            try:
                if reply['method'] == 'sendMessage':
                    result = self.bot._tg.send_message(**payload)
                    if not result.get('ok'):
                        raise RuntimeError('Telegram rejected response')
                    message_id = result.get('result', {}).get('message_id')
                    with self.bot._db.atomic():
                        for row in payload.get('reply_markup', {}).get('inline_keyboard', []):
                            for button in row:
                                data = button.get('callback_data', '')
                                if data.startswith('dyes:') and message_id is not None:
                                    self.bot._db.bind_delete_confirmation(data[5:], reply['user_id'], payload['chat_id'], message_id)
                        self.store.sent(reply['id'])
                else:
                    # Callback acknowledgement is best-effort and cannot gate writes.
                    try:
                        self.bot._tg.answer_callback_query(**payload)
                    except Exception:
                        pass
                    self.store.sent(reply['id'])
            except Exception as exc:
                self.store.fail_reply(reply['id'], exc)
                logger.warning('reply delivery failed: %s', type(exc).__name__)
