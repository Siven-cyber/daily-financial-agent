"""Synthetic inbox/outbox regression tests, with no external calls."""
import json
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.delivery import DeliveryStore


class FixtureDatabase:
    def __init__(self):
        self._conn = sqlite3.connect(':memory:')
        self._conn.row_factory = sqlite3.Row
    @contextmanager
    def atomic(self):
        try:
            self._conn.execute('BEGIN IMMEDIATE')
            yield
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.store = DeliveryStore(self.db)
    def tearDown(self):
        self.db._conn.close()
    def test_retrying_chunk_blocks_later_chunks_but_not_other_replies(self):
        self.store.enqueue(1, 0, 'sendMessage', {'chat_id': 1, 'text': 'first'}, 1)
        self.store.enqueue(1, 1, 'sendMessage', {'chat_id': 1, 'text': 'second'}, 1)
        self.store.enqueue(2, 0, 'sendMessage', {'chat_id': 2, 'text': 'other'}, 2)
        self.db._conn.commit()
        first = self.store.pending_replies()[0]
        self.store.fail_reply(first['id'], OSError('synthetic'))
        self.assertEqual([r['payload']['text'] for r in self.store.pending_replies()], ['other'])
        self.store.sent(first['id'])
        self.assertEqual([r['payload']['text'] for r in self.store.pending_replies()], ['second', 'other'])

    def test_receipt_is_durable_and_deduplicated(self):
        update = {'update_id': 10, 'message': {'text': 'kopi 20rb', 'chat': {'type': 'private', 'id': 1}}}
        self.store.receive([update, update])
        self.assertEqual(self.store.offset(), 11)
        self.assertEqual(len(self.store.pending_updates()), 1)
        self.store = DeliveryStore(self.db)
        self.store.receive([update])
        self.assertEqual(len(self.store.pending_updates()), 1)
    def test_payload_minimizes_identity_metadata(self):
        self.store.receive([{'update_id': 1, 'message': {'text': 'kopi 20rb', 'from': {'id': 5, 'first_name': 'secret'}, 'chat': {'id': 5, 'type': 'private', 'username': 'secret'}}}])
        payload = self.store.pending_updates()[0]
        self.assertNotIn('secret', json.dumps(payload))
    def test_failed_processing_rolls_back_money_and_reply(self):
        self.store.receive([{'update_id': 1}])
        self.db._conn.execute('CREATE TABLE money(amount INTEGER)')
        with self.assertRaises(RuntimeError):
            with self.db.atomic():
                self.db._conn.execute('INSERT INTO money VALUES (20)')
                self.store.enqueue(1, 0, 'sendMessage', {'chat_id': 1, 'text': 'saved'}, 1)
                self.store.complete(1)
                raise RuntimeError('crash before commit')
        self.assertEqual(self.db._conn.execute('SELECT COUNT(*) FROM money').fetchone()[0], 0)
        self.assertEqual(len(self.store.pending_updates()), 1)
        self.assertEqual(self.store.pending_replies(), [])
    def test_commit_then_failed_reply_never_reopens_update(self):
        self.store.receive([{'update_id': 1}])
        with self.db.atomic():
            self.store.enqueue(1, 0, 'sendMessage', {'chat_id': 1, 'text': 'saved'}, 1)
            self.store.complete(1)
        reply = self.store.pending_replies()[0]
        self.store.fail_reply(reply['id'], RuntimeError('sensitive token'))
        self.assertEqual(self.store.pending_updates(), [])
        row = self.db._conn.execute('SELECT * FROM reply_outbox').fetchone()
        self.assertEqual(row['last_error'], 'RuntimeError')
        self.assertEqual(row['attempts'], 1)
    def test_group_content_is_never_persisted(self):
        self.store.receive([{'update_id': 2, 'message': {'text': 'private secret', 'from': {'id': 5}, 'chat': {'id': -1, 'type': 'group'}}}])
        self.assertEqual(self.store.pending_updates(), [{'update_id': 2}])

    def test_invalid_batch_does_not_acknowledge_partial_receipt(self):
        with self.assertRaises(ValueError):
            self.store.receive([{'update_id': 1}, {'update_id': 'bad'}])
        self.assertIsNone(self.store.offset())
        self.assertEqual(self.store.pending_updates(), [])

    def test_reply_unique_per_update_and_ordinal(self):
        with self.db.atomic():
            for _ in range(2):
                self.store.enqueue(1, 0, 'sendMessage', {'chat_id': 1, 'text': 'saved'}, 1)
        self.assertEqual(len(self.store.pending_replies()), 1)


if __name__ == '__main__':
    unittest.main()
