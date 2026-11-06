"""Durable Telegram receipt and delivery. Network I/O never holds a DB transaction."""
from __future__ import annotations

import json
import time
from typing import Any

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS inbox_updates (update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0, last_error TEXT, created_at REAL NOT NULL)",
    "CREATE TABLE IF NOT EXISTS reply_outbox (id INTEGER PRIMARY KEY, update_id INTEGER NOT NULL, ordinal INTEGER NOT NULL, method TEXT NOT NULL, payload TEXT NOT NULL, user_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0, last_error TEXT, UNIQUE(update_id, ordinal))",
    "CREATE TABLE IF NOT EXISTS delivery_state (name TEXT PRIMARY KEY, value INTEGER NOT NULL)",
)


def minimize_update(update: dict) -> dict:
    """Keep only routing, content and callback fields needed for processing."""
    def message(value: dict) -> dict:
        chat = value.get('chat', {})
        return {k: v for k, v in {
            'message_id': value.get('message_id'),
            'text': value.get('text'),
            'chat': {k: chat[k] for k in ('id', 'type') if k in chat},
            'from': {'id': value.get('from', {}).get('id')},
        }.items() if v is not None}
    result: dict = {'update_id': update['update_id']}
    source = update.get('message') or update.get('callback_query', {}).get('message', {})
    if source.get('chat', {}).get('type') != 'private':
        return result
    if 'message' in update:
        result['message'] = message(update['message'])
    elif 'callback_query' in update:
        cb = update['callback_query']
        result['callback_query'] = {
            'id': cb.get('id'), 'data': cb.get('data'),
            'from': {'id': cb.get('from', {}).get('id')},
            'message': message(cb.get('message', {})),
        }
    return result


class DeliveryStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        with db.atomic():
            for statement in _SCHEMA:
                db._conn.execute(statement)
            columns = {r[1] for r in db._conn.execute('PRAGMA table_info(inbox_updates)')}
            if 'user_id' not in columns:
                db._conn.execute('ALTER TABLE inbox_updates ADD COLUMN user_id INTEGER')
                for row in db._conn.execute("SELECT update_id,payload FROM inbox_updates WHERE status IN ('pending','failed')").fetchall():
                    payload = json.loads(row['payload'])
                    subject = payload.get('message') or payload.get('callback_query') or {}
                    db._conn.execute('UPDATE inbox_updates SET user_id=? WHERE update_id=?', (subject.get('from', {}).get('id'), row['update_id']))
            db._conn.execute('CREATE INDEX IF NOT EXISTS inbox_owner_order ON inbox_updates(user_id,update_id,status)')
            db._conn.execute('CREATE INDEX IF NOT EXISTS inbox_ready ON inbox_updates(status,next_attempt_at,update_id)')
            db._conn.execute('CREATE INDEX IF NOT EXISTS outbox_ready ON reply_outbox(status,next_attempt_at,id)')

    def receive(self, updates: list[dict]) -> None:
        with self.db.atomic():
            offset = self._offset()
            for update in updates:
                uid = update.get('update_id')
                if type(uid) is not int or uid < 0:
                    raise ValueError('Invalid Telegram update ID')
                payload = minimize_update(update)
                subject = payload.get('message') or payload.get('callback_query') or {}
                self.db._conn.execute(
                    'INSERT OR IGNORE INTO inbox_updates(update_id,payload,created_at,user_id) VALUES (?,?,?,?)',
                    (uid, json.dumps(payload), time.time(), subject.get('from', {}).get('id')),
                )
                offset = max(offset or 0, uid + 1)
            if offset is not None:
                self.db._conn.execute("INSERT INTO delivery_state VALUES ('offset',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (offset,))

    def _offset(self) -> int | None:
        row = self.db._conn.execute("SELECT value FROM delivery_state WHERE name='offset'").fetchone()
        return int(row[0]) if row else None

    def offset(self) -> int | None:
        with self.db.atomic():
            return self._offset()

    def pending_updates(self, limit: int = 100) -> list[dict]:
        with self.db.atomic():
            rows = self.db._conn.execute("SELECT i.payload FROM inbox_updates i WHERE i.status='pending' AND i.next_attempt_at<=? AND NOT EXISTS (SELECT 1 FROM inbox_updates older WHERE older.user_id=i.user_id AND older.update_id<i.update_id AND older.status IN ('pending','failed')) ORDER BY i.update_id LIMIT ?", (time.time(), limit)).fetchall()
            return [json.loads(r[0]) for r in rows]

    def complete(self, update_id: int) -> None:
        """Caller must hold the same transaction as the financial mutation."""
        self.db._conn.execute("UPDATE inbox_updates SET status='done',payload='{}',last_error=NULL WHERE update_id=?", (update_id,))

    def enqueue(self, update_id: int, ordinal: int, method: str, payload: dict, user_id: int) -> None:
        """Caller must hold the same transaction as the financial mutation."""
        self.db._conn.execute('INSERT OR IGNORE INTO reply_outbox(update_id,ordinal,method,payload,user_id) VALUES (?,?,?,?,?)', (update_id, ordinal, method, json.dumps(payload), user_id))

    def pending_replies(self, limit: int = 100) -> list[dict]:
        with self.db.atomic():
            rows = self.db._conn.execute("SELECT * FROM reply_outbox WHERE status='pending' AND next_attempt_at<=? ORDER BY id LIMIT ?", (time.time(), limit)).fetchall()
            return [dict(r) | {'payload': json.loads(r['payload'])} for r in rows]

    def sent(self, reply_id: int) -> None:
        with self.db.atomic():
            self.db._conn.execute("UPDATE reply_outbox SET status='sent',payload='{}',last_error=NULL WHERE id=?", (reply_id,))

    def _fail(self, table: str, key: str, row_id: int, error: BaseException) -> None:
        # table/key are constants chosen by our own methods, never user input.
        with self.db.atomic():
            row = self.db._conn.execute(f'SELECT attempts FROM {table} WHERE {key}=?', (row_id,)).fetchone()
            if row is None:
                return
            attempts = row[0] + 1
            self.db._conn.execute(f'UPDATE {table} SET attempts=?,next_attempt_at=?,last_error=?,status=? WHERE {key}=?', (attempts, time.time() + min(300, 2 ** min(attempts, 8)), type(error).__name__, 'failed' if attempts >= 8 else 'pending', row_id))

    def fail_update(self, update_id: int, error: BaseException) -> None:
        self._fail('inbox_updates', 'update_id', update_id, error)

    def fail_reply(self, reply_id: int, error: BaseException) -> None:
        self._fail('reply_outbox', 'id', reply_id, error)
