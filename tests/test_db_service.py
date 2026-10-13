"""Unit tests for the DB and service layers (no model, no network)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finance_agent.db import Database  # noqa: E402
from finance_agent.service import FinanceService  # noqa: E402


def _fresh_service() -> FinanceService:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return FinanceService(Database(tmp.name))


def test_record_and_readback_idr():
    svc = _fresh_service()
    result = svc.record_from_text(42, "kopi 20rb")  # default IDR
    assert result is not None
    assert result.transaction.amount == 20_000
    assert result.transaction.currency == "IDR"
    assert result.transaction.seq > 0


def test_user_isolation():
    svc = _fresh_service()
    svc.record_from_text(1, "makan 50rb")
    svc.record_from_text(2, "makan 10rb")
    assert svc.month_summary(1)["expense"] == 50_000
    assert svc.month_summary(2)["expense"] == 10_000


def test_currency_choice_changes_parsing():
    svc = _fresh_service()
    svc._db.set_currency(5, "USD")
    r = svc.record_from_text(5, "coffee $4.50")
    assert r is not None
    assert r.transaction.currency == "USD"
    assert r.transaction.amount == 450  # cents
    s = svc.month_summary(5)
    assert s["currency"] == "USD"
    assert s["expense"] == 450


def test_summaries_do_not_mix_currencies():
    svc = _fresh_service()
    # Record an IDR transaction, then switch the user to USD.
    svc.record_from_text(9, "makan 30rb")
    svc._db.set_currency(9, "USD")
    svc.record_from_text(9, "lunch $5")
    s = svc.month_summary(9)  # now USD
    assert s["currency"] == "USD"
    assert s["expense"] == 500  # only the USD transaction, not the IDR one


def test_budget_warning_triggers():
    svc = _fresh_service()
    svc._db.set_language(9, "id")
    svc._db.set_budget(9, "food", 100_000)
    r1 = svc.record_from_text(9, "makan 70rb")
    assert r1 is not None and r1.budget_warning is None
    r2 = svc.record_from_text(9, "makan 20rb")  # total 90k, 90% of 100k
    assert r2 is not None and r2.budget_warning is not None
    assert "90" in r2.budget_warning


def test_migration_adds_currency_to_existing_db(tmp_path=None):
    import sqlite3
    import tempfile

    # Build an old-schema DB (no currency columns), then open it with Database.
    path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, language TEXT NOT NULL
            DEFAULT 'id', created_at TEXT NOT NULL);
        CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL,
            category TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            occurred_at TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO users (user_id, language, created_at) VALUES (1, 'id', '2026-01-01T00:00:00+00:00');
        INSERT INTO transactions (user_id, kind, amount, category, note, occurred_at, created_at)
            VALUES (1, 'expense', 10000, 'Makan', 'old', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
        """
    )
    con.commit()
    con.close()

    db = Database(path)  # should migrate without error
    assert db.get_currency(1) is None  # existing user has not chosen a currency yet
    tx = db.recent_transactions(1, 10)
    assert tx and tx[0].currency == "IDR"  # existing rows keep their recorded currency


def test_unparseable_returns_none():
    svc = _fresh_service()
    assert svc.record_from_text(1, "halo apa kabar") is None


def test_edit_amount_updates_and_reads_back():
    svc = _fresh_service()
    r = svc.record_from_text(1, "makan 20rb")
    assert r is not None
    tx_id = r.transaction.seq
    updated = svc.edit_amount(1, tx_id, "30rb")
    assert updated is not None
    assert updated.seq == tx_id
    assert updated.amount == 30_000
    # Read back from DB confirms persistence.
    assert svc.get_transaction(1, tx_id).amount == 30_000


def test_edit_amount_preserves_other_fields():
    svc = _fresh_service()
    r = svc.record_from_text(1, "kopi 20rb")
    assert r is not None
    tx_id = r.transaction.seq
    updated = svc.edit_amount(1, tx_id, "25rb")
    assert updated is not None
    assert updated.category == "food"  # unchanged
    assert updated.kind == "expense"   # unchanged
    assert updated.currency == "IDR"   # unchanged


def test_edit_nonexistent_returns_none():
    svc = _fresh_service()
    assert svc.edit_amount(1, 9999, "10rb") is None


def test_edit_invalid_amount_returns_none():
    svc = _fresh_service()
    r = svc.record_from_text(1, "makan 20rb")
    assert r is not None
    assert svc.edit_amount(1, r.transaction.seq, "bukan angka") is None


def test_delete_removes_transaction():
    svc = _fresh_service()
    r = svc.record_from_text(1, "makan 20rb")
    assert r is not None
    tx_id = r.transaction.seq
    assert svc.delete(1, tx_id) is True
    assert svc.get_transaction(1, tx_id) is None


def test_delete_scoped_to_owner():
    svc = _fresh_service()
    r = svc.record_from_text(1, "makan 20rb")
    assert r is not None
    # User 2 cannot delete user 1's transaction.
    assert svc.delete(2, r.transaction.seq) is False
    assert svc.get_transaction(1, r.transaction.seq) is not None


def test_seq_is_independent_per_user():
    svc = _fresh_service()
    a1 = svc.record_from_text(1, "makan 10rb")
    a2 = svc.record_from_text(1, "makan 20rb")
    b1 = svc.record_from_text(2, "makan 5rb")
    b2 = svc.record_from_text(2, "makan 7rb")
    # Each user's sequence starts at 1 and increments independently.
    assert a1.transaction.seq == 1
    assert a2.transaction.seq == 2
    assert b1.transaction.seq == 1
    assert b2.transaction.seq == 2


def test_seq_reuses_after_delete():
    svc = _fresh_service()
    r1 = svc.record_from_text(1, "makan 10rb")
    assert r1.transaction.seq == 1
    svc.delete(1, 1)
    r2 = svc.record_from_text(1, "makan 20rb")
    # seq is computed as MAX(seq)+1 for the user; after deleting the only row, the
    # next transaction is #1 again (per-user numbering, gaps may be reused).
    assert r2.transaction.seq == 1


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS {name}")
            except Exception:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
