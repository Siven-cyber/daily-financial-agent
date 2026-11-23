"""Read-only summary insights; durable snapshots and delivery stay on the main thread."""
import json

from .processing import DeferredQuestion, ReplyCollector
from .currency import format_amount
from .i18n import category_label


class DeferredSummary(DeferredQuestion):
    """Request a snapshot outside the command transaction."""


def prepare(chat_id, user_id, lang):
    raise DeferredSummary((chat_id, user_id, lang), {})


def facts(snapshot, lang):
    """Only backend-computed statements can become visible commentary."""
    expense, income = snapshot['expense'], snapshot['income']
    en = lang == 'en'
    result = {}
    if expense == 0 and income == 0:
        result['empty'] = ('No income or expenses recorded this month.' if en else
                           'Belum ada pemasukan atau pengeluaran tercatat bulan ini.')
    else:
        if income > expense:
            result['income_above_expense'] = ('Recorded income exceeds expenses.' if en else
                                             'Pemasukan tercatat melebihi pengeluaran.')
        elif expense > income:
            result['expense_above_income'] = ('Recorded expenses exceed income.' if en else
                                             'Pengeluaran tercatat melebihi pemasukan.')
        else:
            result['balanced'] = ('Recorded income equals expenses.' if en else
                                  'Pemasukan tercatat sama dengan pengeluaran.')
        categories = snapshot['by_category']
        if categories:
            maximum = max(v for _, v in categories)
            names = ', '.join(category_label(c, lang) for c, v in categories if v == maximum)
            amount = format_amount(maximum, snapshot['currency'])
            result['top_category'] = (f'Largest recorded expense category: {names} ({amount}).' if en else
                                      f'Kategori pengeluaran tercatat terbesar: {names} ({amount}).')
    return result


def select(agent, snapshot, lang, update_id):
    from .interpretation import CATEGORIES
    # Unknown historical labels may contain personal text. Never disclose them.
    safe = dict(snapshot)
    if snapshot.get('window') == 'displayed_recent':
        from .recent_processing import facts as recent_facts
        available = recent_facts(safe, lang)
        period = 'displayed recent list only; not monthly or all history'
    else:
        grouped = {}
        for category, amount in snapshot['by_category']:
            code = category if category in CATEGORIES else 'other'
            grouped[code] = grouped.get(code, 0) + amount
        safe['by_category'] = sorted(grouped.items())
        available = facts(safe, lang)
        period = 'current month, timezone=' + snapshot['timezone'] + ' (user-selected)'
    context = (f'language={lang}\nperiod={period}\n' +
               json.dumps(safe, ensure_ascii=True) + '\navailable_insight_codes=' +
               json.dumps(list(available)))
    answer = agent.answer(
        'Choose one or two useful explanatory insights from available_insight_codes. '
        'Return ONLY {"insights":["code"]}. No additional fields, tools, prose or numbers.',
        context=context, session_id=f'summary:{update_id}')
    try:
        return render_selection(answer, available, lang)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidSelection() from exc


class InvalidSelection(ValueError):
    """Model output is unusable, unlike a provider/runtime failure."""


def render_selection(answer, available, lang):
    answer = answer.strip()
    if answer.startswith('openminion:'):
        answer = answer[len('openminion:'):].strip()
    if answer.startswith('```json') and answer.endswith('```'):
        answer = answer[7:-3].strip()
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('Duplicate field')
            obj[key] = value
        return obj
    obj = json.loads(answer, object_pairs_hook=unique)
    if not isinstance(obj, dict) or set(obj) != {'insights'}:
        raise ValueError('Invalid insight fields')
    codes = obj['insights']
    if (not isinstance(codes, list) or not 1 <= len(codes) <= 2 or
            any(not isinstance(c, str) or c not in available for c in codes) or
            len(set(codes)) != len(codes)):
        raise ValueError('Invalid insight selection')
    heading = 'AI insight' if lang == 'en' else 'Wawasan AI'
    return heading + '\n' + '\n'.join(available[c] for c in codes)


def submit(processor, update, request):
    bot, store = processor.bot, processor.store
    chat_id, user_id, lang = request.args_to_call
    update_id = update['update_id']
    with bot._db.atomic():
        from .commentary_store import migrate
        migrate(bot._db)
        row = bot._db._conn.execute('SELECT * FROM summary_snapshots WHERE update_id=?', (update_id,)).fetchone()
        if row is None:
            recent = getattr(request, 'recent', False)
            rows = bot._service.recent(user_id, 10) if recent else None
            if recent:
                from .recent_processing import snapshot as recent_snapshot
                snapshot = recent_snapshot(rows)
            else:
                snapshot = bot._service.month_summary(user_id)
            collector = ReplyCollector()
            transport = bot._tg
            bot._tg = collector
            try:
                if recent:
                    bot._send_recent(chat_id, user_id, lang, rows=rows)
                else:
                    bot._send_summary(chat_id, user_id, lang, snapshot=snapshot)
            finally:
                bot._tg = transport
            for ordinal, (method, payload) in enumerate(collector.calls):
                store.enqueue(update_id, ordinal, method, payload, user_id)
            ordinal = len(collector.calls)
            from .commentary_store import routing
            origin = routing(update)
            if origin is None or origin[:2] != (user_id, chat_id):
                raise ValueError('MissingRouting')
            bot._db._conn.execute(
                'INSERT INTO summary_snapshots(update_id,snapshot,lang,ordinal,user_id,chat_id,reply_parameters,kind) VALUES (?,?,?,?,?,?,?,?)',
                (update_id, json.dumps(snapshot), lang, ordinal, user_id, chat_id,
                 origin[2], 'recent' if recent else 'summary'))
        store.complete(update_id)


def schedule(processor):
    """Admit optional work only after foreground processing, without ledger reads."""
    conn = processor.bot._db._conn
    columns = {r[1] for r in conn.execute('PRAGMA table_info(summary_snapshots)')}
    if not columns:
        return
    if 'status' not in columns:
        from .commentary_store import migrate
        migrate(processor.bot._db)
    import time
    rows = conn.execute("SELECT * FROM summary_snapshots WHERE status='pending' AND next_attempt_at<=? ORDER BY update_id", (time.time(),)).fetchall()
    for row in rows:
        update_id = row['update_id']
        if update_id in getattr(processor, '_summary_results', {}):
            continue
        if processor.questions is not None:
            if update_id in processor.questions.jobs:
                continue
            if len(processor.questions.jobs) >= processor.questions.capacity:
                break
        snapshot, lang = json.loads(row['snapshot']), row['lang']
        chat_id, user_id = row['chat_id'], row['user_id']
        def compute(snapshot=snapshot, lang=lang, chat_id=chat_id, user_id=user_id, update_id=update_id):
            text, error = None, None
            try:
                if processor.stopping.is_set():
                    raise RuntimeError('Stopping')
                agent = processor.bot._get_agent()
                if processor.stopping.is_set() or agent is None:
                    raise RuntimeError('Unavailable')
                text = select(agent, snapshot, lang, update_id)
            except InvalidSelection:
                pass  # Invalid selections are terminal official-only outcomes.
            except Exception as exc:
                error = type(exc).__name__
            return chat_id, user_id, lang, {'_summary': True, 'text': text, 'error': error}
        if processor.questions is None:
            if not hasattr(processor, '_summary_results'):
                processor._summary_results = {}
            processor._summary_results[update_id] = compute()
            processor._collect_summary_results()
        else:
            processor.questions.submit(update_id, compute)
        break  # At most one optional admission per foreground pass.


def complete(processor, update_id, chat_id, user_id, lang, answer):
    with processor.bot._db.atomic():
        conn = processor.bot._db._conn
        row = conn.execute('SELECT * FROM summary_snapshots WHERE update_id=?', (update_id,)).fetchone()
        if row is None or row['status'] != 'pending':
            return
        if answer.get('error'):
            import time
            attempts = row['attempts'] + 1
            conn.execute('UPDATE summary_snapshots SET attempts=?,next_attempt_at=?,last_error=?,status=? WHERE update_id=?',
                         (attempts, time.time() + min(300, 2 ** min(attempts, 8)), answer['error'],
                          'failed' if attempts >= 8 else 'pending', update_id))
            return
        if answer['text']:
            payload = {'chat_id': row['chat_id'], 'text': answer['text']}
            reply = json.loads(row['reply_parameters'])
            if reply:
                payload['reply_parameters'] = reply
            processor.store.enqueue(update_id, row['ordinal'], 'sendMessage', payload, row['user_id'])
        conn.execute("UPDATE summary_snapshots SET status='done',snapshot='{}',reply_parameters=NULL,chat_id=NULL,last_error=NULL WHERE update_id=?", (update_id,))
