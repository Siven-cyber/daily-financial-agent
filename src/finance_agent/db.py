"""SQLite persistence layer. This is the single source of truth for all money data.

Design rules:
- Money is stored as an integer in the currency's minor unit (rupiah for IDR, cents for
  USD), never as a float, to avoid rounding errors.
- Amounts of different currencies are never mixed or converted. Each transaction carries
  its own currency code, and reads are always scoped to one currency.
- The caller always identifies the user by the authenticated Telegram user_id.
  The model never supplies the user id, so one user can never touch another's data.
- Transaction ids are independent per user: each user's transactions are numbered 1, 2, 3
  with a composite primary key (user_id, seq). This avoids leaking the total transaction
  count across users and keeps each user's numbering intuitive.
- Every write returns the stored row read back from the database, so callers can
  confirm what was actually persisted instead of trusting an upstream claim.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,          -- Telegram user id
    language    TEXT NOT NULL DEFAULT 'id',   -- 'id' or 'en'
    currency    TEXT,                          -- primary currency; NULL = not yet chosen
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    user_id     INTEGER NOT NULL,
    seq         INTEGER NOT NULL,             -- per-user sequence, starts at 1
    kind        TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    amount      INTEGER NOT NULL CHECK (amount > 0),  -- minor units of `currency`
    currency    TEXT NOT NULL DEFAULT 'IDR',
    category    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,                 -- ISO 8601 UTC
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, seq),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_tx_user_time
    ON transactions(user_id, occurred_at);

CREATE TABLE IF NOT EXISTS budgets (
    user_id     INTEGER NOT NULL,
    category    TEXT NOT NULL,
    monthly_cap INTEGER NOT NULL CHECK (monthly_cap > 0),  -- minor units
    PRIMARY KEY (user_id, category)
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Transaction:
    seq: int      # per-user sequence number (the id the user sees)
    user_id: int
    kind: str
    amount: int   # minor units of `currency`
    currency: str
    category: str
    note: str
    occurred_at: str
    created_at: str


class Database:
    """Thread-safe SQLite wrapper.

    A single connection is guarded by a lock. That is enough for a bot whose
    traffic is modest, and it keeps the money-write path strictly serialized.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Migrate existing databases to the current schema.

        Handles two historical layouts:
        - pre-currency: users/transactions lack a `currency` column.
        - pre-composite-key: transactions use a global AUTOINCREMENT `id` primary key,
          which we replace with a per-user (user_id, seq) composite key. Existing rows
          are renumbered so each user's seq starts at 1 in chronological order.
        """
        # 1. users.currency (nullable; NULL = not yet chosen).
        if "currency" not in {
            row["name"] for row in self._conn.execute("PRAGMA table_info(users)")
        }:
            self._conn.execute("ALTER TABLE users ADD COLUMN currency TEXT")

        tx_cols = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(transactions)")
        }
        # 2. transactions.currency (default IDR: first release recorded Rupiah only).
        if "currency" not in tx_cols:
            self._conn.execute(
                "ALTER TABLE transactions ADD COLUMN currency TEXT NOT NULL DEFAULT 'IDR'"
            )

        # 3. Composite key migration: if `transactions` still has a global `id` PK
        #    (and no `seq` column), rebuild it as (user_id, seq).
        if "seq" not in tx_cols:
            self._conn.execute("ALTER TABLE transactions RENAME TO transactions_old")
            self._conn.executescript(_SCHEMA)  # creates the new transactions table
            # Renumber per user in chronological (then created) order.
            self._conn.execute(
                """
                INSERT INTO transactions
                    (user_id, seq, kind, amount, currency, category, note,
                     occurred_at, created_at)
                SELECT
                    user_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id
                        ORDER BY occurred_at ASC, id ASC
                    ),
                    kind, amount, currency, category, note, occurred_at, created_at
                FROM transactions_old
                """
            )
            self._conn.execute("DROP TABLE transactions_old")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            finally:
                cur.close()

    # ----- users -----------------------------------------------------------

    def ensure_user(
        self, user_id: int, language: str = "id", currency: Optional[str] = None
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id, language, currency, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO NOTHING",
                (user_id, language, currency, _utc_now_iso()),
            )

    def get_language(self, user_id: int) -> Optional[str]:
        with self._cursor() as cur:
            cur.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return row["language"] if row else None

    def set_language(self, user_id: int, language: str) -> None:
        self.ensure_user(user_id, language)
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET language = ? WHERE user_id = ?", (language, user_id)
            )

    def get_currency(self, user_id: int) -> Optional[str]:
        with self._cursor() as cur:
            cur.execute("SELECT currency FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return row["currency"] if row else None

    def set_currency(self, user_id: int, currency: str) -> None:
        self.ensure_user(user_id)
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET currency = ? WHERE user_id = ?", (currency, user_id)
            )

    # ----- transactions ----------------------------------------------------

    def add_transaction(
        self,
        *,
        user_id: int,
        kind: str,
        amount: int,
        currency: str,
        category: str,
        note: str = "",
        occurred_at: Optional[str] = None,
    ) -> Transaction:
        """Insert one transaction (assigned the next per-user seq) and read it back.

        `amount` is in the minor unit of `currency` (e.g. cents for USD).
        """
        if kind not in {"expense", "income"}:
            raise ValueError("kind must be 'expense' or 'income'")
        if amount <= 0:
            raise ValueError("amount must be a positive integer (minor units)")
        self.ensure_user(user_id)
        occurred = occurred_at or _utc_now_iso()
        created = _utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM transactions WHERE user_id = ?",
                (user_id,),
            )
            seq = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO transactions "
                "(user_id, seq, kind, amount, currency, category, note, occurred_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, seq, kind, amount, currency, category, note, occurred, created),
            )
        return self.get_transaction(user_id, seq)  # type: ignore[return-value]

    def get_transaction(self, user_id: int, seq: int) -> Optional[Transaction]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM transactions WHERE user_id = ? AND seq = ?",
                (user_id, seq),
            )
            row = cur.fetchone()
            return _row_to_tx(row) if row else None

    def delete_transaction(self, user_id: int, seq: int) -> bool:
        """Delete one transaction scoped to the owner. Returns True if removed."""
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM transactions WHERE user_id = ? AND seq = ?",
                (user_id, seq),
            )
            return cur.rowcount > 0

    def update_transaction_amount(
        self, user_id: int, seq: int, amount: int
    ) -> Optional[Transaction]:
        """Change the amount of one transaction (scoped to the owner).

        Returns the updated row read back from the DB, or None if no such transaction
        exists for this user. Only the amount changes; other fields stay put.
        """
        if amount <= 0:
            raise ValueError("amount must be a positive integer (minor units)")
        with self._cursor() as cur:
            cur.execute(
                "UPDATE transactions SET amount = ? WHERE user_id = ? AND seq = ?",
                (amount, user_id, seq),
            )
            if cur.rowcount == 0:
                return None
        return self.get_transaction(user_id, seq)

    def recent_transactions(self, user_id: int, limit: int = 10) -> list[Transaction]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM transactions WHERE user_id = ? "
                "ORDER BY seq DESC LIMIT ?",
                (user_id, limit),
            )
            return [_row_to_tx(r) for r in cur.fetchall()]

    def sum_by_category(
        self, user_id: int, *, kind: str, currency: str, since_iso: str, until_iso: str
    ) -> list[tuple[str, int]]:
        """Return [(category, total_amount)] for one kind and currency in a window."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT category, SUM(amount) AS total FROM transactions "
                "WHERE user_id = ? AND kind = ? AND currency = ? "
                "AND occurred_at >= ? AND occurred_at < ? "
                "GROUP BY category ORDER BY total DESC",
                (user_id, kind, currency, since_iso, until_iso),
            )
            return [(r["category"], int(r["total"])) for r in cur.fetchall()]

    def total(
        self, user_id: int, *, kind: str, currency: str, since_iso: str, until_iso: str
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
                "WHERE user_id = ? AND kind = ? AND currency = ? "
                "AND occurred_at >= ? AND occurred_at < ?",
                (user_id, kind, currency, since_iso, until_iso),
            )
            return int(cur.fetchone()["total"])

    # ----- budgets ---------------------------------------------------------

    def set_budget(self, user_id: int, category: str, monthly_cap: int) -> None:
        if monthly_cap <= 0:
            raise ValueError("monthly_cap must be a positive integer (minor units)")
        self.ensure_user(user_id)
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO budgets (user_id, category, monthly_cap) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, category) DO UPDATE SET monthly_cap = excluded.monthly_cap",
                (user_id, category, monthly_cap),
            )

    def get_budget(self, user_id: int, category: str) -> Optional[int]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT monthly_cap FROM budgets WHERE user_id = ? AND category = ?",
                (user_id, category),
            )
            row = cur.fetchone()
            return int(row["monthly_cap"]) if row else None


def _row_to_tx(row: sqlite3.Row) -> Transaction:
    return Transaction(
        seq=int(row["seq"]),
        user_id=int(row["user_id"]),
        kind=str(row["kind"]),
        amount=int(row["amount"]),
        currency=str(row["currency"]),
        category=str(row["category"]),
        note=str(row["note"]),
        occurred_at=str(row["occurred_at"]),
        created_at=str(row["created_at"]),
    )
