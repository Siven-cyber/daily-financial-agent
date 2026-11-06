"""Synthetic end-to-end edit tests; no credentials, models or disk ledger."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.bot import FinanceBot
from finance_agent.db import Database
from finance_agent.service import FinanceService
from finance_agent.processing import UpdateProcessor


class EditTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.db.ensure_user(1, language='en', currency='IDR')
        self.db.ensure_user(2, currency='IDR')
        self.tx = self.db.add_transaction(user_id=1, kind='expense', amount=500,
                                          currency='USD', category='other', note='coffee')
        self.bot: Any = FinanceBot.__new__(FinanceBot)
        self.bot._db = self.db
        self.bot._service = FinanceService(self.db)
        self.bot._tg = SimpleNamespace(send_message=lambda *a, **k: None)
        self.calls = []
        self.proposal = {'amount': 650, 'category': None}
        def answer(*args, **kwargs):
            self.assertFalse(self.db._conn.in_transaction)
            self.calls.append((args, kwargs))
            return json.dumps(self.proposal)
        self.bot._agent = SimpleNamespace(answer=answer, close=lambda: None, cancel_active=lambda: None)
        self.processor = UpdateProcessor(self.bot)

    def run_edit(self, text='change #1 to $6.50', uid=1, update_id=1):
        update = {'update_id': update_id, 'message': {'chat': {'id': uid, 'type': 'private'},
                    'from': {'id': uid}, 'text': text}}
        self.processor.receive([update])
        self.processor.process_pending()
        return update

    def test_explicit_amount_original_currency_readback_and_replay(self):
        update = self.run_edit()
        tx = self.db.get_transaction(1, 1)
        self.assertEqual(tx.amount, 650)
        self.assertEqual(tx.currency, 'USD')
        self.assertEqual(tx.note, 'coffee')
        self.assertIn('$6.50', self.processor.store.pending_replies()[0]['payload']['text'])
        self.processor.receive([update])
        self.processor.process_pending()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.db.recent_transactions(1)), 1)

    def test_category_from_ai_with_unique_note_reference(self):
        self.proposal = {'amount': None, 'category': 'food'}
        self.run_edit('ubah coffee kategori makan')
        tx = self.db.get_transaction(1, 1)
        self.assertEqual(tx.category, 'food')
        self.assertEqual(tx.amount, 500)
        self.assertIn('Food', self.processor.store.pending_replies()[0]['payload']['text'])

    def test_sdk_display_prefix_and_json_fence_are_supported(self):
        self.bot._agent.answer = lambda *a, **k: 'openminion: ```json\n{"amount":650,"category":null}\n```'
        self.run_edit()
        self.assertEqual(self.db.get_transaction(1, 1).amount, 650)

    def test_duplicate_json_fields_rejected(self):
        self.bot._agent.answer = lambda *a, **k: '{"amount":999,"amount":650,"category":null}'
        self.run_edit()
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_explicit_last_reference_and_indonesian_readback(self):
        self.db.set_language(1, 'id')
        self.proposal = {'amount': None, 'category': 'food'}
        self.run_edit('ubah terakhir kategori makan')
        self.assertEqual(self.db.get_transaction(1, 1).category, 'food')
        self.assertIn('Makan', self.processor.store.pending_replies()[0]['payload']['text'])

    def test_ambiguous_category_source_clarifies(self):
        self.proposal = {'amount': None, 'category': 'food'}
        self.run_edit('change #1 category food or transport')
        self.assertEqual(self.db.get_transaction(1, 1).category, 'other')

    def test_malformed_injected_and_invented_proposals_do_not_write(self):
        for index, proposal in enumerate([
            {'amount': True, 'category': None}, {'amount': 650.0, 'category': None},
            {'amount': -1, 'category': None}, {'amount': 999, 'category': None},
            {'amount': 650, 'category': None, 'user_id': 2},
            {'amount': 650, 'category': 'food'}, {'amount': None, 'category': []},
            None, [], {'delete': True}], 1):
            with self.subTest(proposal=proposal):
                self.proposal = proposal
                self.run_edit(update_id=index)
                self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_multiple_amounts_and_foreign_currency_clarify(self):
        for index, value in enumerate(['$6.50 or $7', '-6.50', '6rb', 'Rp6500', '6.50 please'], 1):
            self.run_edit('change #1 to ' + value, update_id=index)
            self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_ownership_unknown_and_ambiguous_notes_do_not_write(self):
        self.run_edit(uid=2)
        self.assertEqual(self.calls, [])
        self.db.add_transaction(user_id=1, kind='expense', amount=500, currency='USD', category='other', note='coffee')
        self.run_edit('change coffee to $6.50', update_id=2)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_set_and_recategorize_are_intercepted_before_recording(self):
        for index, text in enumerate(['set #1 to $6.50', 'recategorize coffee 20k'], 1):
            self.run_edit(text, update_id=index)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.db.recent_transactions(1)), 1)
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_unhandled_edit_and_delete_never_record_or_answer(self):
        for index, text in enumerate(['please correct lunch 20k?', 'hapus coffee 20k', 'change something 20k', 'ganti 20rb'], 1):
            self.run_edit(text, update_id=index)
        self.assertEqual(len(self.db.recent_transactions(1)), 1)
        self.assertEqual(self.calls, [])

    def test_timeout_preserves_durable_retry_without_mutation(self):
        def timeout(*a, **k):
            raise TimeoutError('synthetic')
        self.bot._agent.answer = timeout
        self.run_edit()
        row = self.db._conn.execute('SELECT status,payload FROM inbox_updates').fetchone()
        self.assertEqual(row[0], 'pending')
        self.assertIn('change #1', row[1])
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)
        self.assertEqual(self.processor.store.pending_replies(), [])

    def test_outbox_failure_rolls_back_mutation(self):
        def fail(*a, **k):
            raise RuntimeError('synthetic enqueue failure')
        self.processor.store.enqueue = fail
        self.run_edit()
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'pending')

    def test_async_success_without_worker_database_or_telegram(self):
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        # SQLite thread-affinity is independently enforced by all database helpers
        # being invoked only before submission and after future completion.
        self.run_edit()
        self.processor.questions.jobs[1].result(timeout=2)
        self.processor.process_pending()
        self.assertEqual(self.db.get_transaction(1, 1).amount, 650)
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'done')

    def test_async_new_duplicate_note_invalidates_resolution(self):
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.run_edit('change coffee to $6.50')
        self.processor.questions.jobs[1].result(timeout=2)
        self.db.add_transaction(user_id=1, kind='expense', amount=500, currency='USD', category='other', note='coffee')
        self.processor.process_pending()
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)

    def test_async_worker_and_stale_snapshot(self):
        import threading
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        main = threading.get_ident()
        original = self.bot._agent.answer
        def answer(*a, **k):
            self.assertNotEqual(threading.get_ident(), main)
            return original(*a, **k)
        self.bot._agent.answer = answer
        self.run_edit()
        self.processor.questions.jobs[1].result(timeout=2)
        self.assertEqual(self.db.get_transaction(1, 1), self.tx)
        self.db.update_transaction_amount(1, 1, 700)
        self.processor.process_pending()
        self.assertEqual(self.db.get_transaction(1, 1).amount, 700)
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'done')


if __name__ == '__main__':
    unittest.main()
