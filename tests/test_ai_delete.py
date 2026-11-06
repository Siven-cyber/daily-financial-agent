"""Synthetic deletion integration tests; in-memory ledger and fake inference only."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.bot import FinanceBot
from finance_agent.db import Database
from finance_agent.service import FinanceService
from finance_agent.processing import UpdateProcessor


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.db.ensure_user(1, language='id', currency='IDR')
        self.db.ensure_user(2, language='en', currency='IDR')
        self.tx = self.db.add_transaction(user_id=1, kind='expense', amount=20000,
                                          currency='IDR', category='food', note='pentol')
        self.bot = FinanceBot.__new__(FinanceBot)
        self.bot._db = self.db
        self.bot._service = FinanceService(self.db)
        self.bot._tg = SimpleNamespace(send_message=lambda **k: {'ok': True, 'result': {'message_id': 90}},
                                       answer_callback_query=lambda **k: {'ok': True})
        self.calls = []
        self.answer = '{"intent":"delete"}'
        def infer(*a, **k):
            self.calls.append((a, k))
            return self.answer
        self.bot._agent = SimpleNamespace(answer=infer, close=lambda: None, cancel_active=lambda: None)
        self.processor = UpdateProcessor(self.bot)

    def request(self, text='hapus transaksi pentol terakhir', update_id=1, uid=1):
        update = {'update_id': update_id, 'message': {'chat': {'id': uid, 'type': 'private'},
                  'from': {'id': uid}, 'text': text}}
        self.processor.receive([update])
        self.processor.process_pending()
        return update

    def test_sdk_display_prefix_and_json_fence(self):
        self.answer = 'openminion: ```json\n{"intent":"delete"}\n```'
        self.request()
        self.assertEqual(len(self.confirmations()), 1)
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def confirmations(self):
        return self.db._conn.execute('SELECT * FROM deletion_confirmations').fetchall()

    def test_negated_question_or_compound_source_never_confirms_even_if_model_approves(self):
        for index, note in enumerate(['not pentol', 'pentol?', 'pentol jangan', 'pentol and record 20k'], 1):
            self.db.add_transaction(user_id=1, kind='expense', amount=500, currency='IDR', category='food', note=note)
            self.request('delete ' + note, update_id=index)
        self.assertEqual(self.confirmations(), [])
        self.assertEqual(self.calls, [])

    def test_unsupported_deletion_word_forms_never_reach_recording(self):
        for index, text in enumerate(['erase pentol 20rb', 'jangan menghapus pentol 20rb',
                'hapuskan pentol 20rb', 'deleting pentol 20rb', 'remove pentol 20rb'], 1):
            self.request(text, update_id=index)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.confirmations(), [])
        self.assertEqual(len(self.db.recent_transactions(1)), 1)

    def test_bulk_uncertain_or_conditional_reference_is_never_a_note_target(self):
        for index, note in enumerate(['all', 'semua', 'maybe pentol', 'pentol if possible', 'pentol mungkin'], 1):
            self.db.add_transaction(user_id=1, kind='expense', amount=500, currency='IDR', category='food', note=note)
            self.request('delete ' + note, update_id=index)
        self.assertEqual(self.confirmations(), [])
        self.assertEqual(self.calls, [])

    def test_async_completion_enqueues_confirmation_on_main_thread(self):
        import threading
        main = threading.get_ident()
        def infer(*a, **k):
            self.assertNotEqual(threading.get_ident(), main)
            return self.answer
        self.bot._agent.answer = infer
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.request('delete #1')
        self.processor.questions.jobs[1].result(timeout=2)
        self.assertEqual(self.confirmations(), [])
        self.processor.process_pending()
        self.assertEqual(len(self.confirmations()), 1)
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def callback(self, token, update_id=2, uid=1, chat=1, message=90, confirm=True):
        self.processor.receive([{'update_id': update_id, 'callback_query': {
            'id': str(update_id), 'from': {'id': uid},
            'message': {'message_id': message, 'chat': {'id': chat, 'type': 'private'}},
            'data': ('dyes:' if confirm else 'dno:') + token}}])
        self.processor.process_pending()

    def token(self):
        return self.confirmations()[0]['token']

    def test_confirm_once_and_dedup_without_inference(self):
        update = self.request('delete #1')
        token = self.token()
        self.processor.deliver_pending()
        self.callback(token)
        self.assertIsNone(self.db.get_transaction(1, 1))
        self.callback(token, update_id=3)
        self.processor.receive([update])
        self.processor.process_pending()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.confirmations()), 1)

    def test_cancel_keeps_ledger_and_consumes_token(self):
        self.request('delete pentol')
        token = self.token()
        self.processor.deliver_pending()
        self.callback(token, confirm=False)
        self.callback(token, update_id=3)
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_wrong_owner_chat_message_cannot_consume_confirmation(self):
        self.request('delete last')
        token = self.token()
        self.processor.deliver_pending()
        for index, kwargs in enumerate([{'uid': 2}, {'chat': 2}, {'message': 91}], 2):
            self.callback(token, update_id=index, **kwargs)
            self.assertEqual(self.db.get_transaction(1, 1), self.tx)
        self.callback(token, update_id=5)
        self.assertIsNone(self.db.get_transaction(1, 1))

    def test_expiry_and_stale_confirmation_never_delete(self):
        self.request('delete #1')
        self.processor.deliver_pending()
        self.db._conn.execute('UPDATE deletion_confirmations SET expires_at=0')
        self.db._conn.commit()
        self.callback(self.token())
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)
        self.request('delete #1', update_id=3)
        token = self.confirmations()[1]['token']
        self.processor.deliver_pending()
        self.db.update_transaction_amount(1, 1, 25000)
        self.callback(token, update_id=4)
        self.assertEqual(self.db.get_transaction(1, 1).amount, 25000)

    def test_strict_invalid_json_duplicate_and_injected_fields_clarify(self):
        for index, answer in enumerate(['no', 'null', '[]', '{"intent":true}',
                '{"intent":"delete","user_id":2}', '{"intent":"delete","seq":1}',
                '{"intent":"clarify","intent":"delete"}', '{"intent":"clarify"}',
                '```json\n{"intent":"delete"} garbage\n```'], 1):
            self.answer = answer
            self.request('delete #1', update_id=index)
        self.assertEqual(self.confirmations(), [])
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)
        self.assertEqual(self.db._conn.execute("SELECT count(*) FROM inbox_updates WHERE status='done'").fetchone()[0], 9)

    def test_ambiguous_note_unsupported_and_question_do_not_record(self):
        self.db.add_transaction(user_id=1, kind='expense', amount=30000, currency='IDR', category='food', note='pentol')
        for index, text in enumerate(['delete pentol', 'hapus pentol 20rb', 'jangan hapus #1',
                'can you delete #1?', 'hapus semua', 'delete #999'], 1):
            self.request(text, update_id=index)
        self.assertEqual(self.confirmations(), [])
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.db.recent_transactions(1)), 2)
        self.request('hapus transaksi pentol terakhir', update_id=7)
        self.assertEqual(self.confirmations()[0]['seq'], 2)

    def test_changed_reference_during_inference_clarifies(self):
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.request('delete pentol')
        self.processor.questions.jobs[1].result(timeout=2)
        self.db.add_transaction(user_id=1, kind='expense', amount=500, currency='IDR', category='food', note='pentol')
        self.processor.process_pending()
        self.assertEqual(self.confirmations(), [])

    def test_latest_matching_reference_rechecked_during_inference(self):
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.request()
        self.processor.questions.jobs[1].result(timeout=2)
        self.db.add_transaction(user_id=1, kind='expense', amount=500, currency='IDR', category='food', note='pentol')
        self.processor.process_pending()
        self.assertEqual(self.confirmations(), [])

    def test_timeout_retry_and_outbox_rollback_are_durable(self):
        infer = self.bot._agent.answer
        def timeout(*a, **k):
            self.assertFalse(self.db._conn.in_transaction)
            raise TimeoutError('synthetic')
        self.bot._agent.answer = timeout
        self.request('delete #1')
        self.assertEqual(self.confirmations(), [])
        row = self.db._conn.execute('SELECT status,payload FROM inbox_updates').fetchone()
        self.assertEqual(row[0], 'pending')
        self.assertIn('delete #1', row[1])
        self.bot._agent.answer = infer
        original = self.processor.store.enqueue
        def fail(*a, **k):
            raise RuntimeError('synthetic enqueue failure')
        self.processor.store.enqueue = fail
        self.db._conn.execute('UPDATE inbox_updates SET next_attempt_at=0')
        self.db._conn.commit()
        self.processor.process_pending()
        self.assertEqual(self.confirmations(), [])
        self.processor.store.enqueue = original
        self.db._conn.execute('UPDATE inbox_updates SET next_attempt_at=0')
        self.db._conn.commit()
        self.processor.process_pending()
        self.assertEqual(len(self.confirmations()), 1)
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_shutdown_after_initialization_blocks_inference(self):
        def initialize():
            self.processor.stopping.set()
            return self.bot._agent
        self.bot._get_agent = initialize
        self.request('delete #1')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.confirmations(), [])
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'pending')

    def test_async_shutdown_after_inference_keeps_input_pending(self):
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.request('delete #1')
        self.processor.questions.jobs[1].result(timeout=2)
        self.processor.stopping.set()
        self.processor.process_pending()
        self.assertEqual(self.confirmations(), [])
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'pending')

    def test_last_and_snapshot_are_rechecked(self):
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.request('delete last')
        self.processor.questions.jobs[1].result(timeout=2)
        self.db.add_transaction(user_id=1, kind='expense', amount=500, currency='IDR', category='other', note='new')
        self.processor.process_pending()
        self.assertEqual(self.confirmations(), [])
        self.request('delete #1', update_id=2)
        self.processor.questions.jobs[2].result(timeout=2)
        self.db.update_transaction_amount(1, 1, 25000)
        self.processor.process_pending()
        self.assertEqual(self.confirmations(), [])

    def test_no_owner_snapshot_or_ledger_is_disclosed_to_model(self):
        self.request('delete #1')
        args, kwargs = self.calls[0]
        self.assertNotIn('user_id', str((args, kwargs)))
        self.assertNotIn('20000', kwargs['context'])
        self.assertNotIn('pentol', kwargs['context'])

    def test_english_preview_and_slash_delete_remain_supported(self):
        self.db.set_language(1, 'en')
        self.request('/delete 1')
        self.assertEqual(self.calls, [])
        text = self.processor.store.pending_replies()[0]['payload']['text']
        self.assertIn('Delete transaction', text)
        self.assertIn('Food', text)
        self.assertIn('pentol', text)

    def test_latest_matching_note_requests_confirmation_without_deleting(self):
        self.request()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)
        self.assertEqual(len(self.confirmations()), 1)
        payload = self.processor.store.pending_replies()[0]['payload']
        self.assertIn('pentol', payload['text'])
        self.assertIn('20.000', payload['text'])
        self.assertIn('Makan', payload['text'])
        self.assertTrue(payload['reply_markup']['inline_keyboard'][0][0]['callback_data'].startswith('dyes:'))


if __name__ == '__main__':
    unittest.main()
