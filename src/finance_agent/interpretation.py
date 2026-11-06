"""Validate untrusted model proposals before financial writes."""
from .parser import parse_message

CATEGORIES = {'food', 'transport', 'shopping', 'bills', 'entertainment', 'health', 'income', 'other'}
FIELDS = {'kind', 'amount', 'currency', 'category', 'note'}


def validate_proposal(proposal: dict, text: str, currency: str) -> dict:
    if not isinstance(proposal, dict) or set(proposal) != FIELDS:
        raise ValueError('Invalid proposal fields')
    # The parser is an amount safety check, never the category authority.
    parsed = parse_message(text, user_currency=currency)
    amount = proposal['amount']
    if parsed is None or type(amount) is not int or amount <= 0 or amount != parsed.amount:
        raise ValueError('Ambiguous or unsupported amount')
    if proposal['kind'] != parsed.kind:
        raise ValueError('Transaction direction contradicts source text')
    if proposal['currency'] != currency or proposal['kind'] not in {'expense', 'income'}:
        raise ValueError('Invalid currency or kind')
    if proposal['category'] not in CATEGORIES:
        raise ValueError('Invalid category')
    if not isinstance(proposal['note'], str) or len(proposal['note']) > 1000:
        raise ValueError('Invalid note')
    return dict(proposal)


def interpret(agent, text: str, currency: str, session_id: str) -> dict:
    import json
    answer = agent.answer(
        'Interpret this transaction. Return ONLY a JSON object with exactly kind '
        '(expense or income), amount (positive integer in currency minor units), '
        'currency, category (food, transport, shopping, bills, entertainment, health, '
        'income, other), note. If unclear return null. Do not execute any tools. '
        'Pentol is food, not transport. User text: ' + text,
        context=f'Transaction interpretation only. Currency={currency}. IDR minor unit=rupiah; USD minor unit=cent.',
        session_id='interpret:' + session_id,
    )
    answer = answer.strip()
    if answer.startswith('openminion:'):
        answer = answer[len('openminion:'):].strip()
    if answer.startswith('```json') and answer.endswith('```'):
        answer = answer[7:-3].strip()
    return validate_proposal(json.loads(answer), text, currency)
