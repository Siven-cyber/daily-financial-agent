"""Aggregate only the displayed recent window; never disclose ledger notes to AI."""
from .summary_processing import DeferredSummary
from .currency import format_amount
from .i18n import category_label
from .interpretation import CATEGORIES


class DeferredRecent(DeferredSummary):
    """Reuse durable read-only summary snapshot and delivery machinery."""
    recent = True


def prepare(chat_id, user_id, lang):
    raise DeferredRecent((chat_id, user_id, lang), {})


def snapshot(rows):
    groups = {}
    for tx in rows:
        group = groups.setdefault(tx.currency, {'expense': 0, 'income': 0, 'categories': {}})
        group[tx.kind] += tx.amount
        if tx.kind == 'expense':
            code = tx.category if tx.category in CATEGORIES else 'other'
            group['categories'][code] = group['categories'].get(code, 0) + tx.amount
    return {'window': 'displayed_recent', 'count': len(rows), 'currencies': groups}


def facts(data, lang):
    en = lang == 'en'
    if not data['count']:
        return {'empty': 'No transactions in the displayed list.' if en else
                'Tidak ada transaksi dalam daftar yang ditampilkan.'}
    result = {}
    for currency, group in sorted(data['currencies'].items()):
        categories = group['categories']
        if categories:
            maximum = max(categories.values())
            names = ', '.join(category_label(c, lang) for c, v in sorted(categories.items()) if v == maximum)
            amount = format_amount(maximum, currency)
            result[currency + ':top_category'] = (
                f'Largest expense category in the displayed list ({currency}): {names} ({amount}).' if en else
                f'Kategori pengeluaran terbesar dalam daftar yang ditampilkan ({currency}): {names} ({amount}).')
        expense, income = group['expense'], group['income']
        expense_text, income_text = format_amount(expense, currency), format_amount(income, currency)
        result[currency + ':totals'] = (
            f'Displayed list ({currency}): expenses {expense_text}, income {income_text}.' if en else
            f'Daftar yang ditampilkan ({currency}): pengeluaran {expense_text}, pemasukan {income_text}.')
    return result
