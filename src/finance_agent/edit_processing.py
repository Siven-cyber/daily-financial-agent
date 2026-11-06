"""Conservative AI edits: trusted target resolution, untrusted value proposal."""
import json
import re
from dataclasses import asdict

from .currency import format_amount
from .i18n import category_label, t
from .interpretation import CATEGORIES
from .parser import parse_amount
from .processing import DeferredQuestion, ReplyCollector


class DeferredEdit(DeferredQuestion):
    """Carry an authenticated, immutable snapshot out of the SQL boundary."""


def is_edit(text):
    return bool(re.search(r'\b(edit|change|update|correct|ubah|ganti|koreksi|ralat|delete|hapus|remove|set|recategorize|recategorise|kategori|category|nominal|amount)\b', text, re.I))


def prepare(bot, chat_id, user_id, lang, text):
    match = re.fullmatch(r'(?:change|edit|update|ubah|ganti)\s+(.+?)\s+(to|ke|jadi|menjadi|category|kategori)\s+(.+?)\??', text, re.I)
    if not match:
        bot._tg.send_message(chat_id, t(lang, 'edit_clarify'))
        return
    reference, operation, value = match.groups()
    if re.fullmatch(r'#[1-9][0-9]*', reference):
        tx = bot._service.get_transaction(user_id, int(reference[1:]))
    elif reference.lower() in {'last', 'terakhir'}:
        recent = bot._service.recent(user_id, 1)
        tx = recent[0] if recent else None
    else:
        # Exact note references only, over the complete owned ledger, never fuzzy.
        with bot._db.atomic():
            rows = bot._db._conn.execute('SELECT seq FROM transactions WHERE user_id=? AND lower(note)=lower(?)',
                                        (user_id, reference)).fetchall()
        tx = bot._service.get_transaction(user_id, rows[0][0]) if len(rows) == 1 else None
    if tx is None:
        bot._tg.send_message(chat_id, t(lang, 'edit_clarify'))
        return
    mode = 'category' if operation.lower() in {'category', 'kategori'} else 'amount'
    raise DeferredEdit((chat_id, user_id, lang, text, tx, (mode, value, reference)), {})


def validate(proposal, value, currency):
    if not isinstance(proposal, dict) or set(proposal) != {'amount', 'category'}:
        raise ValueError('Invalid edit fields')
    mode, source, _reference = value
    amount, category = proposal['amount'], proposal['category']
    if mode == 'category':
        if amount is not None or not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError('Invalid category')
        if not re.fullmatch(r'[A-Za-z]{1,40}', source):
            raise ValueError('Ambiguous category')
        return dict(proposal)
    if category is not None:
        raise ValueError('Unexpected category')
    if type(amount) is not int or not 0 < amount <= 9223372036854775807:
        raise ValueError('Invalid amount')
    if parse_amount(source, currency) != amount:
        raise ValueError('Amount contradicts source')
    return proposal


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate proposal field')
        result[key] = value
    return result


def submit(processor, update, edit):
    chat_id, user_id, lang, text, snapshot, value = edit.args_to_call
    def compute():
        if processor.stopping.is_set():
            raise RuntimeError('Processor stopping')
        agent = processor.bot._get_agent()
        if agent is None or processor.stopping.is_set():
            raise RuntimeError('Model unavailable')
        proposal = None
        try:
            answer = agent.answer(
                'Interpret an amount/category edit, not a recording or deletion. Return ONLY JSON '
                'with exactly amount (positive integer minor units or null) and category '
                '(food, transport, shopping, bills, entertainment, health, income, other or null). '
                'Never return identity or target fields. Unclear requests: null. No tools. User text: ' + text,
                context=json.dumps({'currency': snapshot.currency, 'minor_units': 'USD cents; IDR rupiah',
                                    'target': {k: v for k, v in asdict(snapshot).items() if k != 'user_id'}}),
                session_id=f'edit:update-{update["update_id"]}')
            answer = answer.strip()
            if answer.startswith('openminion:'):
                answer = answer[len('openminion:'):].strip()
            if answer.startswith('```json') and answer.endswith('```'):
                answer = answer[7:-3].strip()
            proposal = validate(json.loads(answer, object_pairs_hook=strict_object), value, snapshot.currency)
        except ValueError:
            pass
        return chat_id, user_id, lang, {'_edit': True, 'proposal': proposal, 'snapshot': snapshot, 'reference': value[2]}
    if processor.questions is None:
        complete(processor, update['update_id'], *compute())
    elif processor.questions.submit(update['update_id'], compute):
        with processor.bot._db.atomic():
            processor.store.enqueue(update['update_id'], 0, 'sendMessage',
                                    {'chat_id': chat_id, 'text': t(lang, 'processing')}, user_id)


def complete(processor, update_id, chat_id, user_id, lang, answer):
    db = processor.bot._db
    collector = ReplyCollector()
    with db.atomic():
        row = db._conn.execute('SELECT status FROM inbox_updates WHERE update_id=?', (update_id,)).fetchone()
        if row is None or row[0] != 'pending':
            return
        snapshot, proposal = answer['snapshot'], answer['proposal']
        current = db.get_transaction(user_id, snapshot.seq)
        reference = answer['reference']
        resolved = True
        if reference.lower() in {'last', 'terakhir'}:
            latest = db.recent_transactions(user_id, 1)
            resolved = bool(latest and latest[0] == snapshot)
        elif not reference.startswith('#'):
            matches = db._conn.execute('SELECT seq FROM transactions WHERE user_id=? AND lower(note)=lower(?)',
                                       (user_id, reference)).fetchall()
            resolved = len(matches) == 1 and matches[0][0] == snapshot.seq
        if not resolved or current != snapshot or snapshot.user_id != user_id or proposal is None:
            collector.send_message(chat_id, t(lang, 'edit_clarify'))
        else:
            if proposal['amount'] is not None:
                tx = db.update_transaction_amount(user_id, snapshot.seq, proposal['amount'])
            else:
                db._conn.execute('UPDATE transactions SET category=? WHERE user_id=? AND seq=?',
                                 (proposal['category'], user_id, snapshot.seq))
                tx = db.get_transaction(user_id, snapshot.seq)
            collector.send_message(chat_id, t(lang, 'edited', id=tx.seq,
                amount=format_amount(tx.amount, tx.currency), category=category_label(tx.category, lang)))
        for ordinal, (method, payload) in enumerate(collector.calls, 1):
            processor.store.enqueue(update_id, ordinal, method, payload, user_id)
        processor.store.complete(update_id)
