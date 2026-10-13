"""Unit tests for the local message parser (no model, no network).

Amounts are returned in minor units of the given currency (rupiah for IDR, cents for USD).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finance_agent.parser import (  # noqa: E402
    detected_currency_mismatch,
    parse_message,
)


# ----- IDR -----------------------------------------------------------------

def test_idr_simple_expense_rb():
    p = parse_message("kopi 20rb", "IDR")
    assert p is not None
    assert p.kind == "expense"
    assert p.amount == 20_000  # rupiah
    assert p.currency == "IDR"
    assert p.category == "Makan"


def test_idr_income_juta():
    p = parse_message("gajian 6jt", "IDR")
    assert p is not None
    assert p.kind == "income"
    assert p.amount == 6_000_000
    assert p.category == "Pemasukan"


def test_idr_decimal_shorthand():
    p = parse_message("bonus 1,5jt", "IDR")
    assert p is not None
    assert p.amount == 1_500_000


def test_idr_thousands_separator_literal():
    p = parse_message("beli baju 150.000", "IDR")
    assert p is not None
    assert p.amount == 150_000
    assert p.category == "Belanja"


def test_idr_rejects_dollar_marker():
    # "$5" for an IDR user is ambiguous, not a Rp5 record.
    assert parse_message("lunch $5", "IDR") is None


def test_idr_implausibly_small_bare_amount_rejected():
    assert parse_message("makan 5", "IDR") is None


# ----- USD -----------------------------------------------------------------

def test_usd_decimal_cents():
    p = parse_message("coffee 4.50", "USD")
    assert p is not None
    assert p.kind == "expense"
    assert p.amount == 450  # cents
    assert p.currency == "USD"
    assert p.category == "Makan"


def test_usd_dollar_sign_ok():
    p = parse_message("lunch $5", "USD")
    assert p is not None
    assert p.amount == 500  # 5.00 USD in cents


def test_usd_k_shorthand():
    p = parse_message("salary 6k", "USD")
    assert p is not None
    assert p.kind == "income"
    assert p.amount == 600_000  # 6000.00 USD in cents


def test_usd_rejects_rupiah_marker():
    assert parse_message("makan rp20000", "USD") is None


def test_usd_rejects_idr_shorthand_as_suffix():
    # "20rb" has no meaning in USD; "rb" is dropped and 20 stands alone, which is a
    # plausible $20.00, so it should record 2000 cents rather than silently x1000.
    p = parse_message("lunch 20rb", "USD")
    assert p is not None
    assert p.amount == 2_000  # $20.00


# ----- currency mismatch detection ----------------------------------------

def test_mismatch_detects_dollar_for_idr_user():
    assert detected_currency_mismatch("lunch $5", "IDR") == "USD"


def test_mismatch_detects_unsupported_currency():
    assert detected_currency_mismatch("dinner 10 eur", "IDR") == "EUR"


def test_no_mismatch_when_currency_matches():
    assert detected_currency_mismatch("lunch $5", "USD") is None
    assert detected_currency_mismatch("makan 20rb", "IDR") is None


def test_empty_returns_none():
    assert parse_message("   ", "IDR") is None


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
