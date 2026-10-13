"""Bilingual user-facing text (Indonesian / English).

Code and comments stay in English; only these strings are shown to users.
Style rule: no em-dashes in user-facing copy (use commas or parentheses).
Use t(lang, key, **kwargs) to fetch and format a string.
"""

from __future__ import annotations

LANGUAGES = ("id", "en")
DEFAULT_LANGUAGE = "id"

_TEXT: dict[str, dict[str, str]] = {
    # --- onboarding / language ---
    "choose_language": {
        "id": "Pilih bahasa / Choose your language:",
        "en": "Pilih bahasa / Choose your language:",
    },
    "language_set": {
        "id": "Bahasa diatur ke Indonesia.",
        "en": "Language set to English.",
    },
    "choose_currency": {
        "id": "Pilih mata uang utama Anda:",
        "en": "Choose your primary currency:",
    },
    "currency_set": {
        "id": "Mata uang diatur ke {currency}. Ketik /help untuk melihat yang bisa saya lakukan.",
        "en": "Currency set to {currency}. Type /help to see what I can do.",
    },
    "welcome": {
        "id": (
            "Halo! Saya pencatat keuangan pribadi Anda.\n\n"
            "Cukup kirim seperti chat biasa, contohnya:\n"
            "- makan siang 25rb\n"
            "- gajian 6jt\n"
            "- bensin 50rb\n\n"
            "Tanya kapan saja, misalnya: berapa pengeluaran saya bulan ini?"
        ),
        "en": (
            "Hi! I am your personal finance logger.\n\n"
            "Just message me like a normal chat, for example:\n"
            "- lunch 25k\n"
            "- salary 6m\n"
            "- fuel 50k\n\n"
            "Ask me anything, like: how much did I spend this month?"
        ),
    },
    "help": {
        "id": (
            "Yang bisa saya lakukan:\n"
            "- Catat pengeluaran/pemasukan: kirim teks biasa (kopi 20rb)\n"
            "- /ringkasan : ringkasan bulan ini\n"
            "- /terakhir : 10 transaksi terakhir\n"
            "- /bahasa : ganti bahasa\n"
            "- /matauang : ganti mata uang\n"
            "- /help : bantuan ini"
        ),
        "en": (
            "What I can do:\n"
            "- Log expense/income: send plain text (coffee 20k)\n"
            "- /summary : this month summary\n"
            "- /recent : last 10 transactions\n"
            "- /language : change language\n"
            "- /currency : change currency\n"
            "- /help : this help"
        ),
    },
    # --- recording ---
    "recorded_expense": {
        "id": "Tercatat: pengeluaran {amount} ({category}).",
        "en": "Recorded: expense {amount} ({category}).",
    },
    "recorded_income": {
        "id": "Tercatat: pemasukan {amount} ({category}).",
        "en": "Recorded: income {amount} ({category}).",
    },
    "not_understood": {
        "id": (
            "Maaf, saya belum paham. Coba sebut nominalnya, contoh: makan 25rb. "
            "Atau tanya langsung, misalnya: total transport bulan ini?"
        ),
        "en": (
            "Sorry, I did not catch that. Try including an amount, like: lunch 25k. "
            "Or just ask, like: total transport this month?"
        ),
    },
    "wrong_currency": {
        "id": (
            "Mata uang Anda {currency}. Tolong tulis nominalnya dalam {currency}, "
            "atau ganti mata uang lewat /matauang."
        ),
        "en": (
            "Your currency is {currency}. Please write the amount in {currency}, "
            "or change it with /currency."
        ),
    },
    "processing": {
        "id": "Sedang memproses...",
        "en": "Working on it...",
    },
    # --- summaries ---
    "summary_title": {
        "id": "Ringkasan bulan ini",
        "en": "This month summary",
    },
    "summary_line_expense": {
        "id": "Pengeluaran: {amount}",
        "en": "Expense: {amount}",
    },
    "summary_line_income": {
        "id": "Pemasukan: {amount}",
        "en": "Income: {amount}",
    },
    "summary_by_category": {
        "id": "Per kategori (pengeluaran):",
        "en": "By category (expense):",
    },
    "summary_empty": {
        "id": "Belum ada transaksi bulan ini.",
        "en": "No transactions yet this month.",
    },
    "recent_title": {
        "id": "10 transaksi terakhir",
        "en": "Last 10 transactions",
    },
    "recent_empty": {
        "id": "Belum ada transaksi.",
        "en": "No transactions yet.",
    },
    # --- budget warnings ---
    "budget_warning": {
        "id": "Perhatian: pengeluaran {category} sudah {percent}% dari budget ({spent} dari {cap}).",
        "en": "Heads up: {category} spending is {percent}% of budget ({spent} of {cap}).",
    },
    # --- errors ---
    "error_generic": {
        "id": "Maaf, terjadi kesalahan. Coba lagi sebentar.",
        "en": "Sorry, something went wrong. Please try again shortly.",
    },
}


def normalize_language(language: str | None) -> str:
    lang = (language or "").strip().lower()
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


# Language-neutral category code -> localized label.
_CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "food": {"id": "Makan", "en": "Food"},
    "transport": {"id": "Transport", "en": "Transport"},
    "shopping": {"id": "Belanja", "en": "Shopping"},
    "bills": {"id": "Tagihan", "en": "Bills"},
    "entertainment": {"id": "Hiburan", "en": "Entertainment"},
    "health": {"id": "Kesehatan", "en": "Health"},
    "income": {"id": "Pemasukan", "en": "Income"},
    "other": {"id": "Lainnya", "en": "Other"},
}


def category_label(category: str, language: str | None) -> str:
    """Localized display name for a stored category code."""
    lang = normalize_language(language)
    entry = _CATEGORY_LABELS.get(category)
    if entry is None:
        # Unknown/legacy code: show it as-is (defensive).
        return category
    return entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or category


def t(language: str | None, key: str, **kwargs: object) -> str:
    """Return the localized string for key, formatted with kwargs."""
    lang = normalize_language(language)
    entry = _TEXT.get(key)
    if entry is None:
        return key
    template = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template
