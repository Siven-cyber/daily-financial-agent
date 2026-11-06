"""Offline recovery and retention tests."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.db import Database
from finance_agent.delivery import DeliveryStore
from finance_agent.queue_ops import QueueOperations


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.store = DeliveryStore(self.db)
        self.ops = QueueOperations(self.db)
    def tearDown(self):
        self.db.close()
    def test_new_database_and_wal_files_are_private(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private.db'
            db = Database(path)
            try:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                for suffix in ('-wal', '-shm'):
                    sidecar = Path(str(path) + suffix)
                    if sidecar.exists():
                        self.assertEqual(sidecar.stat().st_mode & 0o777, 0o600)
            finally:
                db.close()

    def test_failed_update_recovery_preserves_deduplication(self):
        update = {'update_id': 1, 'message': {'text': 'sensitive', 'chat': {'id': 1, 'type': 'private'}}}
        self.store.receive([update])
        for _ in range(8):
            self.store.fail_update(1, RuntimeError('secret'))
        rows = self.ops.failed('inbox')
        self.assertEqual(len(rows), 1)
        self.assertNotIn('sensitive', str(rows))
        self.assertTrue(self.ops.retry('inbox', 1))
        self.assertFalse(self.ops.retry('inbox', 1))
        self.assertEqual(len(self.store.pending_updates()), 1)
        with self.db.atomic():
            self.store.complete(1)
        self.assertFalse(self.ops.retry('inbox', 1))
        self.store.receive([update])
        self.assertEqual(self.store.pending_updates(), [])
    def test_outbox_retry_does_not_reopen_completed_update(self):
        self.store.receive([{'update_id': 2}])
        with self.db.atomic():
            self.store.complete(2)
            self.store.enqueue(2, 0, 'sendMessage', {'chat_id': 1, 'text': 'saved'}, 1)
        for _ in range(8):
            self.store.fail_reply(1, OSError())
        self.assertTrue(self.ops.retry('outbox', 1))
        self.assertEqual(self.store.pending_updates(), [])
        self.assertEqual(len(self.store.pending_replies()), 1)
    def test_retention_redacts_snapshots_without_losing_transactions(self):
        tx = self.db.add_transaction(user_id=1, kind='expense', amount=100, currency='IDR', category='food')
        token = self.db.create_delete_confirmation(1, 1, tx.seq, ttl_seconds=-1)
        result = self.ops.cleanup()
        self.assertEqual(result['confirmations'], 1)
        self.assertEqual(self.db._conn.execute('SELECT snapshot FROM deletion_confirmations WHERE token=?', (token,)).fetchone()[0], '')
        stored = self.db.get_transaction(1, tx.seq)
        assert stored is not None
        self.assertEqual(stored.amount, 100)
    def test_pending_and_failed_payloads_require_explicit_discard(self):
        self.store.receive([{'update_id': 3, 'message': {'text': 'keep', 'chat': {'id': 1, 'type': 'private'}}}])
        self.ops.cleanup()
        self.assertIn('keep', str(self.store.pending_updates()))
        self.assertFalse(self.ops.discard('inbox', 3))
        for _ in range(8):
            self.store.fail_update(3, RuntimeError())
        self.assertTrue(self.ops.discard('inbox', 3))
        self.assertFalse(self.ops.retry('inbox', 3))
        self.assertEqual(self.db._conn.execute('SELECT payload FROM inbox_updates WHERE update_id=3').fetchone()[0], '{}')


if __name__ == '__main__':
    unittest.main()
