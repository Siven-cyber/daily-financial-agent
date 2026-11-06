"""Bounded edit paraphrases; target identity remains application-owned."""
import re


def parse_edit(text):
    text = text.strip()
    # Never transform a question, negation or conditional into an edit.
    if re.search(r'\?|\b(jangan|bukan|tidak|jika|kalau|apakah|bagaimana|don\x27t|not|if|whether|how)\b', text, re.I):
        return None
    text = re.sub(r'^please\s+(?=(?:change|edit|update)\b)', '', text, flags=re.I)
    match = re.fullmatch(r'the\s+last\s+amount\s+was\s+wrong,?\s*it\s+should\s+be\s+(.+)', text, re.I)
    if match:
        return 'last', 'amount', match[1]
    match = re.fullmatch(r'(?:change|edit|update)\s+(.+?)\s+category\s+to\s+(.+)', text, re.I)
    if match:
        return match[1], 'category', match[2]
    patterns = [
        (r'(?:kategori|category)\s+(.+?)\s+(?:ganti|ubah|jadi|ke|change\s+to|to)\s+(.+)', 'category'),
        (r'(?:yang\s+barusan|yang\s+terakhir|transaksi\s+terakhir)\s+nominalnya\s+salah,?\s*(?:harusnya|seharusnya)\s+(.+)', 'last_amount'),
        (r'(?:nominal|amount)\s+(.+?)\s+(?:ganti|ubah|jadi|ke|to)\s+(.+)', 'amount'),
    ]
    for pattern, mode in patterns:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            if mode == 'last_amount':
                return 'last', 'amount', match[1]
            reference, value = match.groups()
            reference = re.sub(r'\s+tadi$', '', reference, flags=re.I)
            return reference, mode, value
    match = re.fullmatch(r'(?:change|edit|update|ubah|ganti)\s+(.+?)\s+(to|ke|jadi|menjadi|category|kategori)\s+(.+)', text, re.I)
    if match:
        reference, operation, value = match.groups()
        mode = 'category' if operation.lower() in {'category', 'kategori'} else 'amount'
        return reference, mode, value
    return None
