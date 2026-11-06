"""Offline database safety regression tests using synthetic SQLite files only."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from finance_agent.db import Database


class DatabaseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "test.db"
        self.db = Database(self.path)
        self.addCleanup(lambda: self.db.close())

    def add(self, db=None, user=1):
        return (db or self.db).add_transaction(
            user_id=user, kind="expense", amount=100, currency="IDR", category="food"
        )

    def test_atomic_rolls_back_base_exception_and_external_sql(self):
        class Abort(BaseException):
            pass
        with self.assertRaises(Abort):
            with self.db.atomic():
                self.add()
                self.db._conn.execute("INSERT INTO budgets VALUES (?, ?, ?)", (1, "x", 50))
                raise Abort()
        self.assertEqual(self.db.recent_transactions(1), [])
        self.assertIsNone(self.db.get_budget(1, "x"))
        self.assertFalse(self.db._conn.in_transaction)

    def test_nested_failure_uses_savepoint(self):
        with self.db.atomic():
            self.add()
            with self.assertRaises(ValueError):
                with self.db.atomic():
                    self.add()
                    raise ValueError("abort nested")
            self.assertEqual(len(self.db.recent_transactions(1)), 1)
            self.add()
        self.assertEqual([t.seq for t in self.db.recent_transactions(1)], [2, 1])

    def test_confirmation_is_bound_single_use_and_cancellable(self):
        tx = self.add()
        token = self.db.create_delete_confirmation(1, 1, tx.seq)
        assert token is not None
        self.assertFalse(self.db.resolve_delete_confirmation(token, 1, 1, 10, confirm=True))
        self.assertTrue(self.db.bind_delete_confirmation(token, 1, 1, 10))
        self.assertFalse(self.db.resolve_delete_confirmation(token, 2, 1, 10, confirm=True))
        self.assertFalse(self.db.resolve_delete_confirmation(token, 1, 2, 10, confirm=True))
        self.assertFalse(self.db.resolve_delete_confirmation(token, 1, 1, 11, confirm=True))
        self.assertTrue(self.db.resolve_delete_confirmation(token, 1, 1, 10, confirm=False))
        self.assertFalse(self.db.resolve_delete_confirmation(token, 1, 1, 10, confirm=True))
        self.assertIsNotNone(self.db.get_transaction(1, tx.seq))
        token = self.db.create_delete_confirmation(1, 1, tx.seq)
        assert token is not None
        self.db.bind_delete_confirmation(token, 1, 1, 12)
        self.assertTrue(self.db.resolve_delete_confirmation(token, 1, 1, 12, confirm=True))
        self.assertFalse(self.db.resolve_delete_confirmation(token, 1, 1, 12, confirm=True))
        self.assertIsNone(self.db.get_transaction(1, tx.seq))

    def test_confirmation_rejects_expiry_and_changed_target(self):
        tx = self.add()
        for expiry in (True, False):
            token = self.db.create_delete_confirmation(1, 1, tx.seq, ttl_seconds=-1 if expiry else 300)
            assert token is not None
            self.db.bind_delete_confirmation(token, 1, 1, 12)
            if not expiry:
                self.db.update_transaction_amount(1, tx.seq, 200)
            self.assertFalse(self.db.resolve_delete_confirmation(token, 1, 1, 12, confirm=True))
            self.assertIsNotNone(self.db.get_transaction(1, tx.seq))

    def test_concurrent_connections_allocate_unique_sequences(self):
        from concurrent.futures import ThreadPoolExecutor
        def insert(_):
            db = Database(self.path)
            try:
                return self.add(db).seq
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(insert, range(12)))
        self.assertEqual(sorted(ids), list(range(1, 13)))

    def test_migration_fault_rolls_back_schema_and_rows(self):
        from unittest.mock import patch
        from finance_agent import db_migrations
        path = Path(self.tmp.name) / 'fault.db'
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE users(user_id INTEGER PRIMARY KEY, language TEXT, created_at TEXT)')
            conn.execute("INSERT INTO users VALUES(1,'id','old')")
        original = db_migrations.statements
        def fail(conn, schema):
            original(conn, schema)
            conn.execute('ALTER TABLE users ADD COLUMN injected TEXT')
            raise RuntimeError('synthetic migration failure')
        with patch.object(db_migrations, 'statements', fail):
            with self.assertRaises(RuntimeError):
                Database(path)
        with sqlite3.connect(path) as conn:
            self.assertEqual([r[1] for r in conn.execute('PRAGMA table_info(users)')], ['user_id', 'language', 'created_at'])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='transactions'").fetchone())
            self.assertEqual(conn.execute('PRAGMA quick_check').fetchone()[0], 'ok')

    def test_sequences_never_reuse_after_restart(self):
        self.assertEqual(self.add().seq, 1)
        self.assertTrue(self.db.delete_transaction(1, 1))
        other = Database(self.path)
        try:
            self.assertEqual(self.add(other).seq, 2)
            self.assertEqual(self.add(other, user=2).seq, 1)
        finally:
            other.close()

    def test_legacy_migration_preserves_data_and_rebuilds_index(self):
        path = Path(self.tmp.name) / "legacy.db"
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE users (user_id INTEGER PRIMARY KEY, language TEXT,
                                    created_at TEXT);
                CREATE TABLE transactions (id INTEGER PRIMARY KEY, user_id INTEGER,
                    kind TEXT, amount INTEGER, category TEXT, note TEXT,
                    occurred_at TEXT, created_at TEXT);
                CREATE INDEX idx_tx_user_time ON transactions(user_id, occurred_at);
                INSERT INTO users VALUES (1, 'en', '2020');
                INSERT INTO transactions VALUES (7, 1, 'expense', 123, 'food',
                    'original', '2020', '2020');
            """)
        for _ in range(2):
            db = Database(path)
            try:
                tx = db.get_transaction(1, 1)
                self.assertEqual((tx.amount, tx.currency, tx.note), (123, "IDR", "original"))
                self.assertGreater(db._conn.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(db._conn.execute(
                    "SELECT tbl_name FROM sqlite_master WHERE name = ?", ("idx_tx_user_time",)
                ).fetchone()[0], "transactions")
                self.assertEqual(db._conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(db._conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
