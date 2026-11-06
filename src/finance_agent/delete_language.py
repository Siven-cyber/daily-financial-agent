"""Bounded affirmative deletion paraphrases, never a financial write."""
import re


def normalize(text):
    text = text.strip()
    if re.fullmatch(r'the\s+last\s+transaction\s+was\s+wrong,?\s*delete\s+it', text, re.I):
        return 'delete last'
    text = re.sub(r'^please\s+(?=(?:delete|remove)\b)', '', text, flags=re.I)
    match = re.fullmatch(r'(?:delete|remove)\s+transaction\s+number\s+([1-9][0-9]*)', text, re.I)
    if match:
        return 'delete #' + match[1]
    if re.fullmatch(r'yang\s+barusan\s+salah,?\s*hapus\s+saja', text, re.I):
        return 'hapus terakhir'
    text = re.sub(r'^tolong\s+(?=hapus\b)', '', text, flags=re.I)
    match = re.fullmatch(r'hapus\s+transaksi\s+nomor\s+([1-9][0-9]*)', text, re.I)
    if match:
        return 'hapus #' + match[1]
    match = re.fullmatch(r'hapus\s+pembelian\s+(.+?)\s+yang\s+terakhir', text, re.I)
    if match:
        return 'hapus ' + match[1] + ' terakhir'
    return text
