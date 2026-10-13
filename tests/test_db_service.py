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
    assert result.transaction.id > 0


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
