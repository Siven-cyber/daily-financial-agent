"""Synthetic summary tests: no provider, credentials, or customer database."""
import json
import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.bot import FinanceBot
from finance_agent.db import Database
from finance_agent.service import FinanceService
from finance_agent.processing import UpdateProcessor


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.db.ensure_user(1, language='id', currency='IDR')
        self.db.ensure_user(2, language='en', currency='USD')
        self.db.add_transaction(user_id=1, kind='expense', amount=20000,
                                currency='IDR', category='food', note='PRIVATE NOTE')
        self.bot = FinanceBot.__new__(FinanceBot)
        self.bot._db = self.db
        self.bot._service = FinanceService(self.db)
        self.sent = []
        def send(**kw):
            self.sent.append(kw)
            return {'ok': True, 'result': {}}
        self.bot._tg = SimpleNamespace(send_message=send)
        self.calls = []
        self.answer = '{"insights":["top_category"]}'
        def infer(*a, **kw):
            self.calls.append((a, kw))
            return self.answer
        self.bot._agent = SimpleNamespace(answer=infer, close=lambda: None, cancel_active=lambda: None)
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)

    def request(self, text='/summary', update_id=1, uid=1):
        update = {'update_id': update_id, 'message': {'chat': {'id': uid, 'type': 'private'},
                  'from': {'id': uid}, 'text': text}}
        self.processor.receive([update])
        self.processor.process_pending()
        return update

    def finish(self, uid=1):
        self.processor.questions.jobs[uid].result(timeout=2)
        self.processor.process_pending()
        self.processor.deliver_pending()

    def test_invalid_timeout_and_unavailable_keep_official_only(self):
        invalid = ['no', 'null', '[]', '{"insights":[true]}',
                   '{"insights":["empty"]}', '{"insights":["top_category","top_category"]}',
                   '{"insights":["top_category"],"user_id":2}',
                   '{"insights":[],"insights":["top_category"]}',
                   '{"insights":["top_category"]} trailing']
        for index, answer in enumerate(invalid, 1):
            self.answer = answer
            self.request(update_id=index)
            self.finish(index)
            self.assertEqual(len(self.sent), index)
        def timeout(*a, **kw):
            raise TimeoutError('synthetic')
        self.bot._agent.answer = timeout
        self.request(update_id=10)
        self.finish(10)
        self.bot._get_agent = lambda: None
        self.request(update_id=11)
        self.finish(11)
        self.assertEqual(len(self.sent), 11)
        self.assertEqual(self.db.get_transaction(1, 1).amount, 20000)
        self.assertEqual(self.db._conn.execute("SELECT count(*) FROM inbox_updates WHERE status='done'").fetchone()[0], 11)

    def test_empty_english_and_recent_no_ai(self):
        self.answer = 'openminion: ```json\n{"insights":["empty"]}\n```'
        self.request(uid=2)
        self.processor.deliver_pending()
        self.finish()
        self.assertIn('No income or expenses recorded', self.sent[-1]['text'])
        self.assertIn('language=en', self.calls[0][1]['context'])
        self.assertIn('USD', self.calls[0][1]['context'])
        self.assertNotIn('20000', self.calls[0][1]['context'])
        self.request('/recent', update_id=2)
        self.assertEqual(len(self.calls), 1)

    def test_restart_reuses_snapshot_ordinals_and_deduplicates(self):
        update = self.request()
        self.processor.questions.jobs[1].result(timeout=2)
        self.processor.deliver_pending()
        self.processor.close()
        self.db.update_transaction_amount(1, 1, 90000)
        self.processor = UpdateProcessor(self.bot, async_questions=True)
        self.addCleanup(self.processor.close)
        self.processor.process_pending()
        self.finish()
        self.processor.receive([update])
        self.processor.process_pending()
        self.processor.deliver_pending()
        self.assertEqual(len(self.sent), 2)
        self.assertIn('20.000', self.sent[-1]['text'])
        rows = self.db._conn.execute('SELECT ordinal FROM reply_outbox ORDER BY ordinal').fetchall()
        self.assertEqual([r[0] for r in rows], [0, 1])
        self.assertEqual(self.db._conn.execute('SELECT count(*) FROM summary_snapshots').fetchone()[0], 0)

    def test_outbox_rollback_then_retry_never_duplicates_official(self):
        original = self.processor.store.enqueue
        def fail(*a, **kw):
            raise RuntimeError('synthetic enqueue')
        self.processor.store.enqueue = fail
        self.request()
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.db._conn.execute("SELECT name FROM sqlite_master WHERE name='summary_snapshots'").fetchone())
        self.processor.store.enqueue = original
        self.db._conn.execute('UPDATE inbox_updates SET next_attempt_at=0')
        self.db._conn.commit()
        self.processor.process_pending()
        self.processor.questions.jobs[1].result(timeout=2)
        self.processor.store.enqueue = fail
        self.processor.process_pending()
        self.assertEqual(self.db._conn.execute('SELECT count(*) FROM reply_outbox').fetchone()[0], 1)
        self.processor.store.enqueue = original
        self.db._conn.execute('UPDATE inbox_updates SET next_attempt_at=0')
        self.db._conn.commit()
        self.processor.process_pending()
        self.finish()
        self.processor.deliver_pending()
        self.assertEqual(len(self.sent), 2)

    def test_sync_inference_outside_transaction(self):
        self.processor.close()
        self.processor = UpdateProcessor(self.bot)
        infer = self.bot._agent.answer
        def check(*a, **kw):
            self.assertFalse(self.db._conn.in_transaction)
            return infer(*a, **kw)
        self.bot._agent.answer = check
        self.request()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.db.get_transaction(1, 1).amount, 20000)

    def test_context_excludes_unrecognized_category_text(self):
        self.db.add_transaction(user_id=1, kind='expense', amount=500,
                                currency='IDR', category='PRIVATE CATEGORY', note='secret')
        self.request()
        self.finish()
        self.assertNotIn('PRIVATE', self.calls[0][1]['context'])

    def test_wib_month_boundary_currency_and_owner_isolation(self):
        self.db._conn.execute('DELETE FROM transactions')
        self.db._conn.commit()
        for uid, currency, amount, instant in [
                (1, 'IDR', 100, '2026-10-31T16:59:59+00:00'),
                (1, 'IDR', 200, '2026-10-31T17:00:00+00:00'),
                (1, 'USD', 999, '2026-10-31T17:00:00+00:00'),
                (2, 'IDR', 888, '2026-10-31T17:00:00+00:00')]:
            tx = self.db.add_transaction(user_id=uid, kind='expense', amount=amount,
                                        currency=currency, category='food', note='secret')
            self.db._conn.execute('UPDATE transactions SET occurred_at=? WHERE user_id=? AND seq=?', (instant, uid, tx.seq))
            self.db._conn.commit()
        self.db._conn.commit()
        before = self.bot._service.month_summary(1, now=datetime.fromisoformat('2026-10-31T16:59:59+00:00'))
        after = self.bot._service.month_summary(1, now=datetime.fromisoformat('2026-10-31T17:00:00+00:00'))
        self.assertEqual(before['expense'], 100)
        self.assertEqual(after['expense'], 200)
        self.assertEqual(after['month_period'], '2026-11')
        self.assertEqual(after['timezone'], 'Asia/Jakarta')
        context = self.bot._service.summary_context(1, now=datetime.fromisoformat('2026-10-31T17:00:00+00:00'))
        self.assertIn('month_expense=Rp200', context)
        self.assertIn('today_expense=Rp200', context)

    def test_immediate_official_then_ai_from_same_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        infer = self.bot._agent.answer
        def slow(*a, **kw):
            entered.set()
            release.wait(2)
            return infer(*a, **kw)
        self.bot._agent.answer = slow
        self.addCleanup(release.set)
        self.request('/ringkasan')
        self.assertTrue(entered.wait(1))
        self.processor.deliver_pending()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('20.000', self.sent[0]['text'])
        self.request('/help', 2, 2)
        self.processor.deliver_pending()
        self.assertEqual(len(self.sent), 2)
        self.db.update_transaction_amount(1, 1, 90000)
        release.set()
        self.finish()
        self.assertEqual(len(self.calls), 1)
        self.assertIn('20.000', self.sent[-1]['text'])
        self.assertNotIn('90.000', self.sent[-1]['text'])
        context = self.calls[0][1]['context']
        self.assertNotIn('PRIVATE', context)
        self.assertIn('Asia/Jakarta', context)
        self.assertIn('language=id', context)
        self.assertEqual(self.db.get_transaction(1, 1).amount, 90000)


if __name__ == '__main__':
    unittest.main()
