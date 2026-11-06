"""Synthetic recent insight integration, without provider or customer data."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.bot import FinanceBot
from finance_agent.db import Database
from finance_agent.service import FinanceService
from finance_agent.processing import UpdateProcessor


class RecentTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.db.ensure_user(1, language='id', currency='IDR')
        self.db.add_transaction(user_id=1, kind='expense', amount=20000,
                                currency='IDR', category='food', note='SECRET NOTE')
        self.sent, self.contexts = [], []
        self.answer = '{"insights":["IDR:top_category"]}'
        self.bot = FinanceBot.__new__(FinanceBot)
        self.bot._db = self.db
        self.bot._service = FinanceService(self.db)
        self.bot._tg = SimpleNamespace(send_message=self.send)
        self.bot._agent = SimpleNamespace(answer=self.infer, cancel_active=lambda: None, close=lambda: None)
        self.p = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(lambda: self.p.close())

    def send(self, **kw):
        self.sent.append(kw['text'])
        return {'ok': True, 'result': {}}

    def infer(self, *a, **kw):
        self.assertFalse(self.db._conn.in_transaction)
        self.contexts.append(kw['context'])
        return self.answer

    def request(self, uid=1, update_id=1, text='/recent'):
        update = {'update_id': update_id, 'message': {'from': {'id': uid},
                  'chat': {'id': uid, 'type': 'private'}, 'text': text}}
        self.p.receive([update]); self.p.process_pending(); self.p.deliver_pending()
        return update

    def finish(self, update_id=1):
        self.p.questions.jobs[update_id].result(timeout=2)
        self.p.process_pending(); self.p.deliver_pending()

    def test_official_then_private_grounded_insight(self):
        self.request()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('SECRET NOTE', self.sent[0])
        self.finish()
        self.assertEqual(len(self.sent), 2)
        self.assertIn('20.000', self.sent[1])
        self.assertNotIn('SECRET', self.contexts[0])
        self.assertNotIn('user_id', self.contexts[0])
        self.assertIn('ditampilkan', self.sent[1])
        self.assertEqual(self.db.get_transaction(1, 1).amount, 20000)

    def test_mixed_currency_and_unknown_category_privacy(self):
        self.db.add_transaction(user_id=1, kind='expense', amount=650,
                                currency='USD', category='PRIVATE CATEGORY', note='PRIVATE USD')
        self.answer = 'openminion: ```json\n{"insights":["IDR:totals","USD:top_category"]}\n```'
        self.request(); self.finish()
        self.assertNotIn('PRIVATE', self.contexts[0])
        self.assertNotIn('20650', self.contexts[0])
        self.assertIn('20.000', self.sent[1])
        self.assertIn('6.50', self.sent[1])
        self.assertNotIn('bulan', self.sent[1])

    def test_window_is_only_ten_displayed_rows_and_owner_scoped(self):
        for _ in range(11):
            self.db.add_transaction(user_id=1, kind='expense', amount=1000,
                                    currency='IDR', category='food', note='coffee')
        self.db.ensure_user(2, language='en', currency='USD')
        self.db.add_transaction(user_id=2, kind='expense', amount=99999,
                                currency='USD', category='food', note='OTHER OWNER')
        self.request(); self.finish()
        self.assertIn('10000', self.contexts[0])
        self.assertNotIn('20000', self.contexts[0])
        self.assertNotIn('99999', self.contexts[0])
        self.assertEqual(self.sent[0].count('#'), 10)

    def test_invalid_proposals_leave_official_only(self):
        for uid, answer in enumerate(['null', '{"insights":["empty"]}',
                '{"insights":["IDR:totals"],"amount":1}',
                '{"insights":[],"insights":["IDR:totals"]}',
                '{"insights":["IDR:totals"]} trailing'], 1):
            self.answer = answer
            self.request(update_id=uid); self.finish(uid)
            self.assertEqual(len(self.sent), uid)
        self.assertEqual(self.db.get_transaction(1, 1).amount, 20000)

    def test_slow_inference_does_not_delay_official_or_other_owner(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        def slow(*a, **kw):
            entered.set()
            release.wait(2)
            return self.answer
        self.addCleanup(release.set)
        self.bot._agent.answer = slow
        self.request()
        self.assertTrue(entered.wait(1))
        self.assertEqual(len(self.sent), 1)
        self.db.ensure_user(2, language='en', currency='USD')
        self.request(uid=2, update_id=2, text='/help')
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates WHERE update_id=2').fetchone()[0], 'done')
        release.set(); self.finish()

    def test_timeout_keeps_official_and_completes(self):
        def timeout(*a, **kw):
            raise TimeoutError('synthetic')
        self.bot._agent.answer = timeout
        self.request(); self.finish()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.db._conn.execute('SELECT status FROM inbox_updates').fetchone()[0], 'done')

    def test_empty_english_alias(self):
        self.db.ensure_user(2, language='en', currency='USD')
        self.answer = '{"insights":["empty"]}'
        self.request(uid=2, text='/terakhir'); self.finish()
        self.assertIn('No transactions in the displayed list.', self.sent[1])
        self.assertNotIn('20000', self.contexts[0])

    def test_restart_snapshot_reused_and_replay_deduplicated(self):
        update = self.request()
        self.p.questions.jobs[1].result(timeout=2)
        self.p.close()
        self.db.update_transaction_amount(1, 1, 90000)
        self.p = UpdateProcessor(self.bot, async_questions=True)
        self.p.process_pending(); self.finish()
        self.assertEqual(len(self.sent), 2)
        self.assertIn('20.000', self.sent[1])
        self.p.receive([update]); self.p.process_pending(); self.p.deliver_pending()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.db._conn.execute('SELECT count(*) FROM summary_snapshots').fetchone()[0], 0)

    def test_initial_enqueue_rollback_then_retry(self):
        original = self.p.store.enqueue
        def fail(*a, **kw):
            raise RuntimeError('synthetic')
        self.p.store.enqueue = fail
        self.request()
        self.assertEqual(self.contexts, [])
        self.assertEqual(self.sent, [])
        self.p.store.enqueue = original
        self.db._conn.execute('UPDATE inbox_updates SET next_attempt_at=0'); self.db._conn.commit()
        self.p.process_pending(); self.finish(); self.p.deliver_pending()
        self.assertEqual(len(self.sent), 2)

if __name__ == '__main__':
    unittest.main()
