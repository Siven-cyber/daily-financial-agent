"""Local, model-free parser for simple finance messages.

Handles the common fast path ("kopi 20rb", "gajian 6jt", "lunch 25k", "coffee $4.50")
so the bot can record a transaction instantly and cheaply, without waiting on a slow
model call. Anything this parser cannot confidently read is handed to the agent.

Parsing is currency-aware. The user picks a primary currency (IDR or USD) at onboarding,
and the amount is interpreted and returned in that currency's minor unit:
- IDR: shorthand rb/ribu=thousand, jt/juta/mio=million; '.'/',' are thousands separators
  when there is no shorthand suffix; no minor unit (minor == rupiah).
- USD: k=thousand, m=million; ',' is a thousands separator and '.' a decimal point;
  minor unit is cents.

If a message carries a currency marker that does not match the user's currency (for
example "$5" for an IDR user), the parser reports a mismatch so the bot can ask the user
to restate the amount, instead of silently recording a wrong value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from .currency import get_currency, minor_from_major, normalize_currency

# Numeric scale for shorthand suffixes (same scale across currencies).
_THOUSAND = 1_000
_MILLION = 1_000_000

# IDR accepts the full Indonesian shorthand set; USD accepts only k/m.
_SUFFIX_MULTIPLIER = {
    "rb": _THOUSAND, "ribu": _THOUSAND, "k": _THOUSAND,
    "jt": _MILLION, "juta": _MILLION, "m": _MILLION, "mio": _MILLION,
}
_SUFFIXES_BY_CURRENCY = {
    "IDR": ("rb", "ribu", "jt", "juta", "mio", "k", "m"),
    "USD": ("k", "m"),
}

# Words that signal income rather than expense (ID + EN).
_INCOME_WORDS = {
    "gaji", "gajian", "gaj", "pemasukan", "masuk", "terima", "dapat", "bonus",
    "thr", "untung", "profit", "salary", "income", "received", "earned", "got paid",
}

# number + optional suffix, e.g. "20rb", "1,5jt", "25k", "150.000", "5.50"
_AMOUNT_RE = re.compile(
    r"(?P<num>\d{1,3}(?:[.,]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s*(?P<suf>ribu|rb|juta|jt|mio|k|m)\b)?",
    re.IGNORECASE,
)

# Currency markers mapped to a currency code. Markers not listed here are "unsupported".
_MARKER_TO_CODE = [
    (re.compile(r"(\$|\busd\b|\bus\$|\bdollar\b|\bdolar\b)", re.IGNORECASE), "USD"),
    (re.compile(r"(\brp\b|\brp(?=\d)|\bidr\b|\brupiah\b)", re.IGNORECASE), "IDR"),
]
# Any non-IDR/USD currency marker we do not support at all.
_UNSUPPORTED_MARKER_RE = re.compile(
    r"(€|£|¥|₩|฿|\b(?:eur|gbp|jpy|sgd|myr|aud|cny|rmb|won|yen|euro|pound)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedTransaction:
    kind: str          # 'expense' or 'income'
    amount: int        # integer, in minor units of `currency`
    currency: str      # currency code
    category: str
    note: str


def detected_currency_mismatch(text: str, user_currency: str) -> Optional[str]:
    """Return a currency code/marker that conflicts with the user's currency, else None.

    - An unsupported currency marker (e.g. EUR) returns the uppercased marker text.
    - A supported marker for a different currency (e.g. "$" when the user is on IDR)
      returns that currency code.
    """
    user_code = normalize_currency(user_currency)
    if _UNSUPPORTED_MARKER_RE.search(text):
        return _UNSUPPORTED_MARKER_RE.search(text).group(0).upper()  # type: ignore[union-attr]
    for pattern, code in _MARKER_TO_CODE:
        if pattern.search(text) and code != user_code:
            return code
    return None


def _parse_amount_minor(
    num_text: str, suffix: Optional[str], currency_code: str
) -> Optional[int]:
    """Convert a matched number + suffix into integer minor units for the currency."""
    cur = get_currency(currency_code)
    suffix = (suffix or "").lower()
    if suffix and suffix not in _SUFFIXES_BY_CURRENCY[cur.code]:
        return None
    if suffix:
        pattern = r"\d+(?:[.,]\d+)?" if cur.code == "IDR" else r"\d+(?:\.\d+)?"
        if not re.fullmatch(pattern, num_text):
            return None
        normalized = num_text.replace(",", ".")
    elif cur.code == "IDR":
        if not re.fullmatch(r"(?:\d+|\d{1,3}(?:\.\d{3})+|\d{1,3}(?:,\d{3})+)", num_text):
            return None
        normalized = num_text.replace(".", "").replace(",", "")
    else:
        if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", num_text):
            return None
        normalized = num_text.replace(",", "")
    try:
        value = Decimal(normalized) * _SUFFIX_MULTIPLIER.get(suffix, 1) * (10 ** cur.decimals)
        if value != value.to_integral_value() or not 0 < value <= 9_223_372_036_854_775_807:
            return None
        return int(value)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _guess_category(note: str, kind: str) -> str:
    """Map common keywords to a language-neutral category code.

    Codes (not human labels) are stored, so the bot can render them in the user's
    language at display time. See i18n.category_label() for the localized names.
    """
    text = note.lower()
    table = {
        "food": ["makan", "kopi", "coffee", "lunch", "dinner", "sarapan", "jajan",
                 "food", "warteg", "nasi", "mie", "snack"],
        "transport": ["transport", "bensin", "grab", "gojek", "ojek", "parkir",
                      "tol", "bus", "kereta", "fuel", "taxi"],
        "shopping": ["belanja", "beli", "shopping", "baju", "clothes", "mall"],
        "bills": ["listrik", "pulsa", "wifi", "internet", "token", "bill", "tagihan",
                  "pln", "air"],
        "entertainment": ["nonton", "film", "game", "netflix", "spotify", "entertainment"],
        "health": ["obat", "dokter", "rumah sakit", "health", "medicine", "apotek"],
    }
    for category, keywords in table.items():
        if any(k in text for k in keywords):
            return category
    if kind == "income":
        return "income"
    return "other"


def parse_message(
    text: str, user_currency: str = "IDR"
) -> Optional[ParsedTransaction]:
    """Try to read a simple transaction from free text, in the user's currency.

    Returns None when the message is ambiguous, carries a mismatched currency, has no
    clear amount, or has an implausibly small bare amount. The caller should then ask
    for clarification or fall back to the model, rather than record a wrong value.
    """
    stripped = text.strip()
    if not stripped:
        return None

    code = normalize_currency(user_currency)

    # A currency marker for a different currency makes the amount ambiguous.
    if detected_currency_mismatch(stripped, code) is not None:
        return None

    # Only accept the shorthand suffixes valid for this currency; strip others out of
    # the match by checking against the per-currency allow-list below.
    matches = list(_AMOUNT_RE.finditer(stripped))
    if len(matches) != 1 or re.search(r"[-−]\s*\d", stripped):
        return None
    match = matches[0]
    if match.end() < len(stripped) and stripped[match.end()].isalnum():
        return None

    suffix = (match.group("suf") or "").lower()
    if suffix and suffix not in _SUFFIXES_BY_CURRENCY.get(code, ()):  # e.g. "rb" on USD
        return None

    amount = _parse_amount_minor(match.group("num"), suffix, code)
    if amount is None or amount <= 0:
        return None

    # A bare amount (no shorthand suffix) below the plausible floor is almost always a
    # misread, so treat it as ambiguous instead of recording it.
    cur = get_currency(code)
    min_minor = minor_from_major(cur.min_plausible_major, code)
    if not suffix and amount < min_minor:
        return None

    lowered = stripped.lower()
    tokens = set(re.findall(r"[a-z]+", lowered))
    kind = "income" if tokens & _INCOME_WORDS else "expense"

    # The note is the message with the matched amount text removed.
    note = (stripped[: match.start()] + stripped[match.end():]).strip()
    note = re.sub(r"\s{2,}", " ", note).strip(" -:,")
    if not note:
        note = stripped

    category = _guess_category(note, kind)
    return ParsedTransaction(
        kind=kind, amount=amount, currency=code, category=category, note=note
    )


def parse_amount(text: str, user_currency: str = "IDR") -> Optional[int]:
    """Parse a bare amount (e.g. "75rb", "4.50", "50000") into minor units.

    Used by the edit command, which supplies only a number without a category/note.
    Returns None if no valid amount can be read.
    """
    stripped = text.strip()
    if not stripped:
        return None
    code = normalize_currency(user_currency)
    if detected_currency_mismatch(stripped, code) is not None:
        return None
    matches = list(_AMOUNT_RE.finditer(stripped))
    if len(matches) != 1 or re.search(r"[-−]\s*\d", stripped):
        return None
    match = matches[0]
    if match.end() < len(stripped) and stripped[match.end()].isalnum():
        return None
    suffix = (match.group("suf") or "").lower()
    if suffix and suffix not in _SUFFIXES_BY_CURRENCY.get(code, ()):
        return None
    remainder = stripped[:match.start()] + stripped[match.end():]
    if not re.fullmatch(r"\s*(?:(?:Rp|IDR|USD|US\$|\$)\s*)?", remainder, re.IGNORECASE):
        return None
    amount = _parse_amount_minor(match.group("num"), suffix, code)
    if amount is None or amount <= 0:
        return None
    return amount
