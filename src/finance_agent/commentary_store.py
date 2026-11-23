"""Snapshot job schema. No import-time or monitoring-time migration."""
import json

_COLUMNS = {
    'user_id': 'INTEGER', 'chat_id': 'INTEGER', 'reply_parameters': 'TEXT',
    'kind': 'TEXT', 'status': "TEXT NOT NULL DEFAULT 'pending'",
    'attempts': 'INTEGER NOT NULL DEFAULT 0',
    'next_attempt_at': 'REAL NOT NULL DEFAULT 0', 'last_error': 'TEXT',
}


def routing(update):
    """Only retained authenticated private user-message routing is authoritative."""
    message = update.get('message', {})
    owner = message.get('from', {}).get('id')
    chat = message.get('chat', {})
    mid = message.get('message_id')
    if (type(owner) is not int or owner <= 0 or chat.get('type') != 'private'
            or type(chat.get('id')) is not int or chat['id'] != owner):
        return None
    reply = ({'message_id': mid, 'allow_sending_without_reply': True}
             if type(mid) is int and mid > 0 else None)
    return owner, chat['id'], json.dumps(reply)


def migrate(db):
    """Transactional/idempotent extension; call only on the bot activation path."""
    with db.atomic():
        conn = db._conn
        conn.execute('CREATE TABLE IF NOT EXISTS summary_snapshots (update_id INTEGER PRIMARY KEY, snapshot TEXT NOT NULL, lang TEXT NOT NULL, ordinal INTEGER NOT NULL)')
        columns = {r[1] for r in conn.execute('PRAGMA table_info(summary_snapshots)')}
        legacy = 'user_id' not in columns
        for name, declaration in _COLUMNS.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE summary_snapshots ADD COLUMN {name} {declaration}')
        if not legacy:
            return
        for row in conn.execute('SELECT * FROM summary_snapshots').fetchall():
            inbox = conn.execute('SELECT payload,status FROM inbox_updates WHERE update_id=?', (row['update_id'],)).fetchone()
            try:
                origin = routing(json.loads(inbox['payload'])) if inbox else None
                snapshot = json.loads(row['snapshot'])
                kind = 'recent' if snapshot.get('window') == 'displayed_recent' else 'summary'
            except (ValueError, TypeError, AttributeError):
                origin = None
                kind = 'summary'
            status = ('failed' if inbox and inbox['status'] == 'failed' else
                      'pending' if origin else 'failed')
            if inbox and inbox['status'] in ('done', 'discarded'):
                status = 'failed'
            conn.execute('UPDATE summary_snapshots SET user_id=?,chat_id=?,reply_parameters=?,kind=?,status=?,last_error=? WHERE update_id=?',
                         (*(origin or (None, None, None)), kind, status,
                          None if origin else 'MissingRouting', row['update_id']))
            if origin and inbox and inbox['status'] == 'pending':
                conn.execute("UPDATE inbox_updates SET status='done',payload='{}',last_error=NULL WHERE update_id=?", (row['update_id'],))
