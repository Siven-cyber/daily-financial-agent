"""Currency metadata and formatting.

Design (per the product decision): no conversion between currencies. Each transaction
is stored with its own currency code, and summaries group by currency. Each user has one
primary currency chosen at onboarding.

Amount notation differs per currency:
- IDR uses Indonesian shorthand (rb/ribu=thousand, jt/juta=million) and treats '.'/','
  as thousands separators when there is no shorthand suffix. It has no minor units.
- USD uses '.' as a decimal point and supports k/m shorthand. It has 2 minor units
  (cents), stored internally as integer cents.

To keep the database integer-only and currency-agnostic, every amount is stored as an
integer in the currency's minor unit:
- IDR minor unit = 1 rupiah   (decimals = 0)
- USD minor unit = 1 cent     (decimals = 2)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Currency:
    code: str          # ISO code, e.g. "IDR", "USD"
    symbol: str        # display symbol, e.g. "Rp", "$"
    decimals: int      # number of minor-unit digits (0 for IDR, 2 for USD)
    label: str         # human label for the picker
    # Minimum plausible amount in MAJOR units for a bare number (no shorthand suffix).
    min_plausible_major: float


_CURRENCIES: dict[str, Currency] = {
    "IDR": Currency(
        code="IDR", symbol="Rp", decimals=0, label="Rupiah (IDR)",
        min_plausible_major=100,
    ),
    "USD": Currency(
        code="USD", symbol="$", decimals=2, label="US Dollar (USD)",
        min_plausible_major=0.01,
    ),
}

DEFAULT_CURRENCY = "IDR"
SUPPORTED_CURRENCIES = tuple(_CURRENCIES.keys())


def normalize_currency(code: str | None) -> str:
    c = (code or "").strip().upper()
    return c if c in _CURRENCIES else DEFAULT_CURRENCY


def get_currency(code: str | None) -> Currency:
    return _CURRENCIES[normalize_currency(code)]


def minor_from_major(amount_major: float, code: str) -> int:
    """Convert a major-unit amount (e.g. dollars) to integer minor units (e.g. cents)."""
    cur = get_currency(code)
    return int(round(amount_major * (10 ** cur.decimals)))


def format_amount(amount_minor: int, code: str) -> str:
    """Format an integer minor-unit amount for display, e.g. 'Rp10.000' or '$5.00'.

    IDR uses '.' as the thousands separator (Indonesian style). USD uses ',' for
    thousands and '.' for the cents decimal (US style).
    """
    cur = get_currency(code)
    if cur.decimals == 0:
        whole = int(amount_minor)
        grouped = f"{whole:,}".replace(",", ".")
        return f"{cur.symbol}{grouped}"
    # Currencies with minor units (e.g. USD cents).
    scale = 10 ** cur.decimals
    whole, frac = divmod(int(amount_minor), scale)
    grouped = f"{whole:,}"  # keep ',' thousands for USD
    return f"{cur.symbol}{grouped}.{frac:0{cur.decimals}d}"
