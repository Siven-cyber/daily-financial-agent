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


class DeferredRecord(DeferredQuestion):
    """Interpret outside the financial transaction, then commit atomically."""


class ReplyCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict:
        from .reply_text import split_text
        parts = split_text(text)
        for index, part in enumerate(parts):
            options = dict(kwargs)
            if index < len(parts) - 1:
                options.pop('reply_markup', None)
            self.calls.append(('sendMessage', {'chat_id': chat_id, 'text': part, **options}))
        return {'ok': True, 'result': {}}

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict:
        self.calls.append(('answerCallbackQuery', {'callback_query_id': callback_query_id, 'text': text}))
        return {'ok': True}


class UpdateProcessor:
    def __init__(self, bot: Any, async_questions: bool = False) -> None:
        self.bot = bot
        self.store = DeliveryStore(bot._db)
        from .question_worker import QuestionWorker
        self.questions = QuestionWorker() if async_questions else None
        import threading
        self.stopping = threading.Event()

    def close(self) -> None:
        self.stopping.set()
        agent = getattr(self.bot, '_agent', None)
        try:
            if agent is not None:
                agent.cancel_active()
        finally:
            try:
                if self.questions is not None:
                    self.questions.close()
            finally:
                agent = getattr(self.bot, '_agent', None)
                if agent is not None:
                    agent.close()

    def _collect_answers(self) -> None:
        if self.questions is None:
            return
        from .i18n import t
        for update_id, future in self.questions.completed():
            try:
                chat_id, user_id, lang, answer = future.result()
                collector = ReplyCollector()
                if isinstance(answer, dict) and answer.get('_edit'):
                    from .edit_processing import complete
                    complete(self, update_id, chat_id, user_id, lang, answer)
                    continue
                if isinstance(answer, dict) and answer.get('_record'):
                    self._complete_record(update_id, chat_id, user_id, lang, answer.get('proposal'))
                    continue
                if answer is None:
                    transport = self.bot._tg
                    self.bot._tg = collector
                    try:
                        self.bot._send_summary(chat_id, user_id, lang)
                    finally:
                        self.bot._tg = transport
                else:
                    collector.send_message(chat_id, str(answer))
                with self.bot._db.atomic():
                    for ordinal, (method, payload) in enumerate(collector.calls, start=1):
                        self.store.enqueue(update_id, ordinal, method, payload, user_id)
                    self.store.complete(update_id)
            except Exception as exc:
                self.store.fail_update(update_id, exc)

    def _complete_record(self, update_id, chat_id, user_id, lang, proposal):
        from .i18n import t
        collector = ReplyCollector()
        transport = self.bot._tg
        self.bot._tg = collector
        try:
            with self.bot._db.atomic():
                row = self.bot._db._conn.execute('SELECT status FROM inbox_updates WHERE update_id=?', (update_id,)).fetchone()
                if row is None or row[0] != 'pending':
                    return
                if proposal is None:
                    collector.send_message(chat_id, t(lang, 'not_understood'))
                else:
                    result = self.bot._service.record(user_id, **proposal)
                    self.bot._send_record_confirmation(chat_id, lang, result)
                for ordinal, (method, payload) in enumerate(collector.calls, start=1):
                    self.store.enqueue(update_id, ordinal, method, payload, user_id)
                self.store.complete(update_id)
        finally:
            self.bot._tg = transport

    def _submit_record(self, update, record):
        from .interpretation import interpret
        from .i18n import t
        chat_id, user_id, lang, text, currency = record.args_to_call
        def compute():
            proposal = None
            try:
                if self.stopping.is_set():
                    raise RuntimeError('Processor stopping')
                agent = self.bot._get_agent()
                if self.stopping.is_set():
                    raise RuntimeError('Processor stopping')
                if agent is None:
                    raise RuntimeError('Model unavailable')
                proposal = interpret(agent, text, currency, f'update-{update["update_id"]}')
            except ValueError:
                logger.warning('transaction interpretation invalid; clarification required')
            return chat_id, user_id, lang, {'_record': True, 'proposal': proposal}
        if self.questions is None:
            _, _, _, answer = compute()
            self._complete_record(update['update_id'], chat_id, user_id, lang, answer['proposal'])
        elif self.questions.submit(update['update_id'], compute):
            with self.bot._db.atomic():
                self.store.enqueue(update['update_id'], 0, 'sendMessage', {'chat_id': chat_id, 'text': t(lang, 'processing')}, user_id)

    def _submit_question(self, update: dict, question: DeferredQuestion) -> None:
        from .i18n import t
        chat_id, user_id, lang, text = question.args_to_call
        context = self.bot._service.summary_context(user_id)
        def compute():
            try:
                if self.stopping.is_set():
                    return chat_id, user_id, lang, None
                agent = self.bot._get_agent()
                if self.stopping.is_set():
                    return chat_id, user_id, lang, None
                answer = agent.answer(text, context=context, session_id=f'user-{user_id}') if agent is not None else None
            except Exception:
                answer = None
            return chat_id, user_id, lang, answer or None
        assert self.questions is not None
        if self.questions.submit(update['update_id'], compute):
            with self.bot._db.atomic():
                self.store.enqueue(update['update_id'], 0, 'sendMessage', {'chat_id': chat_id, 'text': t(lang, 'processing')}, user_id)

    def receive(self, updates: list[dict]) -> None:
        self.store.receive(updates)

    def _save_replies(self, update: dict, collector: ReplyCollector) -> None:
        subject = update.get('message') or update.get('callback_query') or {}
        user_id = subject.get('from', {}).get('id') or 0
        for ordinal, (method, payload) in enumerate(collector.calls):
            self.store.enqueue(update['update_id'], ordinal, method, payload, user_id)
        self.store.complete(update['update_id'])

    def process_pending(self) -> None:
        self._collect_answers()
        for update in self.store.pending_updates():
            if self.questions is not None and update['update_id'] in self.questions.jobs:
                continue
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
                    from .edit_processing import DeferredEdit, submit
                    if isinstance(question, DeferredEdit):
                        submit(self, update, question)
                    elif isinstance(question, DeferredRecord):
                        self._submit_record(update, question)
                    elif self.questions is not None:
                        self._submit_question(update, question)
                    else:
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
