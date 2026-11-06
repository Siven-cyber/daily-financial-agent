"""Synthetic question context with explicit WIB daily boundaries."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.db import Database
from finance_agent.service import FinanceService


class ContextTests(unittest.TestCase):
    def test_today_uses_wib_and_excludes_other_owner(self):
        db = Database(':memory:')
        self.addCleanup(db.close)
        db.ensure_user(1, currency='IDR')
        db.ensure_user(2, currency='IDR')
        for uid, amount, timestamp in [(1, 10000, '2026-11-05T16:59:59+00:00'), (1, 20000, '2026-11-05T17:00:00+00:00'), (2, 99999, '2026-11-05T18:00:00+00:00')]:
            db.add_transaction(user_id=uid, kind='expense', amount=amount, currency='IDR', category='food', occurred_at=timestamp)
        text = FinanceService(db).summary_context(1, now=datetime(2026,11,6,3,tzinfo=timezone.utc))
        self.assertIn('timezone=Asia/Jakarta', text)
        self.assertIn('today_date=2026-11-06', text)
        self.assertIn('today_expense=Rp20.000', text)
        self.assertIn('month_expense=Rp30.000', text)
        self.assertNotIn('99.999', text)


if __name__ == '__main__':
    unittest.main()
