"""Durable handler integration, fake Telegram and synthetic SQLite only."""
import sys
import unittest
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.bot import FinanceBot
from finance_agent.db import Database
from finance_agent.service import FinanceService
from finance_agent.processing import UpdateProcessor


class Telegram:
    def __init__(self):
        self.sent = []
        self.fail = False
    def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise OSError('network failure')
        self.sent.append((chat_id, text))
        return {'ok': True, 'result': {'message_id': len(self.sent)}}
    def answer_callback_query(self, *args, **kw):
        return {'ok': True}


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.db.ensure_user(1, currency='IDR')
        self.bot: Any = FinanceBot.__new__(FinanceBot)
        self.bot._db = self.db
        self.bot._service = FinanceService(self.db)
        self.bot._tg = Telegram()
        self.bot._agent = None
        self.processor = UpdateProcessor(self.bot)
        self.update = {'update_id': 1, 'message': {'message_id': 1, 'chat': {'id': 1, 'type': 'private'}, 'from': {'id': 1}, 'text': 'kopi 20rb'}}
    def tearDown(self):
        self.db.close()
    def test_failed_create_blocks_following_edit_for_same_user(self):
        original = self.bot._send_record_confirmation
        def fail(*args):
            raise RuntimeError('temporary')
        self.bot._send_record_confirmation = fail
        edit = {'update_id': 2, 'message': {'chat': {'id': 1, 'type': 'private'}, 'from': {'id': 1}, 'text': '/edit 1 30rb'}}
        self.processor.receive([self.update, edit])
        self.processor.process_pending()
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates WHERE update_id=2').fetchone()[0], 'pending')
        self.bot._send_record_confirmation = original
        with self.db.atomic():
            self.db._conn.execute('UPDATE inbox_updates SET next_attempt_at=0')
        self.processor.process_pending()
        self.processor.process_pending()
        stored = self.db.get_transaction(1, 1)
        assert stored is not None
        self.assertEqual(stored.amount, 30000)

    def test_cleanup_attempts_runtime_close_after_cancel_failure(self):
        events = []
        class Agent:
            def cancel_active(self):
                raise RuntimeError('cancel failure')
            def close(self):
                events.append('runtime closed')
        self.bot._agent = Agent()
        with self.assertRaises(RuntimeError):
            self.processor.close()
        self.assertEqual(events, ['runtime closed'])

    def test_startup_failure_closes_database(self):
        from unittest.mock import Mock
        self.bot._tg.get_me = Mock(side_effect=OSError('startup'))
        self.bot._db = Mock()
        with self.assertRaises(OSError):
            self.bot.run()
        self.bot._db.close.assert_called_once()

    def test_shutdown_cancels_active_agent_before_closing_runtime(self):
        events = []
        class Agent:
            def cancel_active(self):
                events.append('cancel')
            def close(self):
                events.append('close')
        self.bot._agent = Agent()
        self.processor.close()
        self.assertEqual(events, ['cancel', 'close'])

    def test_async_model_failure_completes_with_numeric_summary(self):
        class Agent:
            def answer(self, *args, **kwargs):
                raise TimeoutError('synthetic')
        self.bot._get_agent = lambda: Agent()
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.update['message']['text'] = 'berapa pengeluaran?'
        self.processor.receive([self.update])
        self.processor.process_pending()
        assert self.processor.questions is not None
        future = self.processor.questions.jobs[1]
        try:
            future.result(timeout=2)
        except TimeoutError:
            pass
        self.processor.process_pending()
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'done')
        for reply in self.processor.store.pending_replies():
            self.processor.store.sent(reply['id'])
        texts = [r['payload']['text'] for r in self.processor.store.pending_replies()]
        self.assertTrue(any('Belum ada transaksi' in text for text in texts))

    def test_slow_model_does_not_block_other_user(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        class Agent:
            def answer(self, *args, **kwargs):
                entered.set()
                release.wait(2)
                return 'synthetic answer'
        self.bot._get_agent = lambda: Agent()
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.addCleanup(release.set)
        self.update['message']['text'] = 'berapa pengeluaran?'
        self.db.ensure_user(2, currency='IDR')
        other = {'update_id': 2, 'message': {'chat': {'id': 2, 'type': 'private'}, 'from': {'id': 2}, 'text': 'kopi 20rb'}}
        self.processor.receive([self.update, other])
        self.processor.process_pending()
        self.assertTrue(entered.wait(1))
        self.assertEqual(len(self.db.recent_transactions(2)), 1)
        release.set()
        assert self.processor.questions is not None
        future = self.processor.questions.jobs[1]
        future.result(timeout=2)
        self.processor.process_pending()
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates WHERE update_id=1').fetchone()[0], 'done')
        for reply in self.processor.store.pending_replies():
            self.processor.store.sent(reply['id'])
        replies = self.processor.store.pending_replies()
        self.assertTrue(any(r['payload'].get('text') == 'synthetic answer' for r in replies))

    def test_question_executes_outside_financial_transaction(self):
        def answer(chat_id, user_id, lang, text):
            self.assertFalse(self.db._conn.in_transaction)
            self.bot._tg.send_message(chat_id, 'synthetic model answer')
        self.bot._answer_question = answer
        self.update['message']['text'] = 'berapa pengeluaran?'
        self.processor.receive([self.update])
        self.processor.process_pending()
        self.assertEqual(self.db.recent_transactions(1), [])
        self.assertEqual(self.processor.store.pending_replies()[0]['payload']['text'], 'synthetic model answer')

    def test_stale_acknowledgement_is_not_requeued(self):
        def fail(*args, **kwargs):
            raise TimeoutError('stale callback')
        self.bot._tg.answer_callback_query = fail
        with self.db.atomic():
            self.processor.store.enqueue(99, 0, 'answerCallbackQuery', {'callback_query_id': 'old'}, 1)
        self.processor.deliver_pending()
        row = self.db._conn.execute('SELECT status,payload FROM reply_outbox').fetchone()
        self.assertEqual(row['status'], 'sent')
        self.assertEqual(row['payload'], '{}')

    def test_delete_flow_binds_sent_message_and_consumes_token(self):
        self.processor.receive([self.update])
        self.processor.process_pending()
        self.processor.deliver_pending()
        self.processor.receive([{'update_id': 2, 'message': {'message_id': 2, 'chat': {'id': 1, 'type': 'private'}, 'from': {'id': 1}, 'text': '/hapus 1'}}])
        self.processor.process_pending()
        reply = self.processor.store.pending_replies()[0]
        token = reply['payload']['reply_markup']['inline_keyboard'][0][0]['callback_data']
        self.processor.deliver_pending()
        cb = {'update_id': 3, 'callback_query': {'id': 'confirm', 'from': {'id': 1}, 'data': token, 'message': {'message_id': len(self.bot._tg.sent), 'chat': {'id': 1, 'type': 'private'}}}}
        self.processor.receive([cb])
        self.processor.process_pending()
        self.assertEqual(self.db.recent_transactions(1), [])
        result = self.bot._service.record_from_text(1, 'kopi 30rb')
        assert result is not None
        self.assertGreater(result.transaction.seq, 1)
        cb['update_id'] = 4
        self.processor.receive([cb])
        self.processor.process_pending()
        self.assertEqual(len(self.db.recent_transactions(1)), 1)

    def test_legacy_delete_callback_never_deletes(self):
        result = self.bot._service.record_from_text(1, 'kopi 20rb')
        assert result is not None
        self.bot.handle_update({'callback_query': {'id': 'old', 'from': {'id': 1}, 'data': f'del:{result.transaction.seq}', 'message': {'message_id': 5, 'chat': {'id': 1, 'type': 'private'}}}})
        self.assertEqual(len(self.db.recent_transactions(1)), 1)

    def test_replay_after_processor_reconstruction_records_once(self):
        self.processor.receive([self.update])
        self.processor.process_pending()
        self.processor = UpdateProcessor(self.bot)
        self.processor.receive([self.update])
        self.processor.process_pending()
        self.assertEqual(len(self.db.recent_transactions(1)), 1)
    def test_failed_reply_does_not_repeat_money(self):
        self.bot._tg.fail = True
        self.processor.receive([self.update])
        self.processor.process_pending()
        self.processor.deliver_pending()
        self.assertEqual(len(self.db.recent_transactions(1)), 1)
        self.assertEqual(self.processor.store.pending_updates(), [])
        self.assertEqual(self.db._conn.execute("SELECT status FROM reply_outbox").fetchone()[0], 'pending')
    def test_handler_failure_rolls_back_money_and_retains_update(self):
        original = self.bot._send_record_confirmation
        def fail(*args):
            raise RuntimeError('crash after write')
        self.bot._send_record_confirmation = fail
        self.processor.receive([self.update])
        self.processor.process_pending()
        self.assertEqual(self.db.recent_transactions(1), [])
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'pending')
        self.bot._send_record_confirmation = original


if __name__ == '__main__':
    unittest.main()
