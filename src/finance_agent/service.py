"""Application service layer: ties the DB, parser, i18n, and (optionally) the agent
together into operations the bot calls. All money reads/writes go through here, scoped
to the authenticated user_id and that user's chosen currency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .currency import format_amount, normalize_currency
from .db import Database, Transaction
from .i18n import t
from .parser import parse_message


@dataclass(frozen=True)
class RecordResult:
    transaction: Transaction
    budget_warning: Optional[str]


def _month_window(now: Optional[datetime] = None) -> tuple[str, str]:
    """Return [start, end) ISO timestamps for the current UTC month."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


class FinanceService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def user_currency(self, user_id: int) -> str:
        return normalize_currency(self._db.get_currency(user_id))

    # ----- recording -------------------------------------------------------

    def record_from_text(self, user_id: int, text: str) -> Optional[RecordResult]:
        """Fast path: parse locally in the user's currency and store.

        Returns None if nothing parseable (caller then clarifies or asks the model).
        """
        currency = self.user_currency(user_id)
        parsed = parse_message(text, user_currency=currency)
        if parsed is None:
            return None
        return self.record(
            user_id,
            kind=parsed.kind,
            amount=parsed.amount,
            currency=parsed.currency,
            category=parsed.category,
            note=parsed.note,
        )

    def record(
        self,
        user_id: int,
        *,
        kind: str,
        amount: int,
        currency: str,
        category: str,
        note: str,
    ) -> RecordResult:
        """Store a transaction and read it back, then compute any budget warning."""
        tx = self._db.add_transaction(
            user_id=user_id,
            kind=kind,
            amount=amount,
            currency=currency,
            category=category,
            note=note,
        )
        warning = (
            self._budget_warning(user_id, category, currency)
            if kind == "expense"
            else None
        )
        return RecordResult(transaction=tx, budget_warning=warning)

    def _budget_warning(
        self, user_id: int, category: str, currency: str
    ) -> Optional[str]:
        cap = self._db.get_budget(user_id, category)
        if not cap:
            return None
        since, until = _month_window()
        # Budget is tracked in the user's currency.
        by_cat = dict(
            self._db.sum_by_category(
                user_id,
                kind="expense",
                currency=currency,
                since_iso=since,
                until_iso=until,
            )
        )
        cat_spent = by_cat.get(category, 0)
        if cat_spent < int(cap * 0.8):
            return None
        lang = self._db.get_language(user_id) or "id"
        percent = int(round(cat_spent / cap * 100))
        return t(
            lang,
            "budget_warning",
            category=category,
            percent=percent,
            spent=format_amount(cat_spent, currency),
            cap=format_amount(cap, currency),
        )

    # ----- reads -----------------------------------------------------------

    def recent(self, user_id: int, limit: int = 10) -> list[Transaction]:
        return self._db.recent_transactions(user_id, limit)

    def month_summary(self, user_id: int) -> dict:
        """Summary for the user's current currency."""
        currency = self.user_currency(user_id)
        since, until = _month_window()
        expense = self._db.total(
            user_id, kind="expense", currency=currency, since_iso=since, until_iso=until
        )
        income = self._db.total(
            user_id, kind="income", currency=currency, since_iso=since, until_iso=until
        )
        by_cat = self._db.sum_by_category(
            user_id, kind="expense", currency=currency, since_iso=since, until_iso=until
        )
        return {
            "currency": currency,
            "expense": expense,
            "income": income,
            "by_category": by_cat,
        }

    def summary_context(self, user_id: int) -> str:
        """Plain-text context passed to the agent for free-form questions.

        Amounts are given in major units with the currency code, so the model phrases
        answers in the right currency without doing any conversion.
        """
        s = self.month_summary(user_id)
        currency = s["currency"]
        lines = [
            f"currency={currency}",
            f"month_expense={format_amount(s['expense'], currency)}",
            f"month_income={format_amount(s['income'], currency)}",
            "expense_by_category="
            + ", ".join(f"{c}:{format_amount(v, currency)}" for c, v in s["by_category"]),
        ]
        return "\n".join(lines)
