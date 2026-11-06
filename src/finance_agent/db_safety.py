"""Single-use deletion capabilities bound to an owner, chat, message and snapshot."""
import json
import secrets
import time
from typing import Any


def snapshot(conn: Any, user_id: int, seq: int) -> str | None:
    row = conn.execute('SELECT * FROM transactions WHERE user_id=? AND seq=?', (user_id, seq)).fetchone()
    return json.dumps(dict(row), sort_keys=True) if row else None


class ConfirmationMixin:
    def create_delete_confirmation(self: Any, user_id: int, chat_id: int, seq: int, ttl_seconds: int = 300) -> str | None:
        with self.atomic():
            value = snapshot(self._conn, user_id, seq)
            if value is None:
                return None
            token = secrets.token_urlsafe(24)
            self._conn.execute('INSERT INTO deletion_confirmations(token,user_id,chat_id,seq,snapshot,expires_at) VALUES (?,?,?,?,?,?)', (token, user_id, chat_id, seq, value, time.time() + ttl_seconds))
            return token

    def bind_delete_confirmation(self: Any, token: str, user_id: int, chat_id: int, message_id: int) -> bool:
        if type(message_id) is not int:
            return False
        with self.atomic():
            cur = self._conn.execute("UPDATE deletion_confirmations SET message_id=? WHERE token=? AND user_id=? AND chat_id=? AND message_id IS NULL AND state='pending' AND expires_at>?", (message_id, token, user_id, chat_id, time.time()))
            return cur.rowcount == 1

    def resolve_delete_confirmation(self: Any, token: str, user_id: int, chat_id: int, message_id: int, confirm: bool) -> bool:
        with self.atomic():
            row = self._conn.execute("SELECT * FROM deletion_confirmations WHERE token=? AND user_id=? AND chat_id=? AND message_id=? AND state='pending'", (token, user_id, chat_id, message_id)).fetchone()
            if row is None:
                return False
            valid = row['expires_at'] > time.time() and snapshot(self._conn, user_id, row['seq']) == row['snapshot']
            self._conn.execute("UPDATE deletion_confirmations SET state=? WHERE token=?", ('consumed' if valid else 'invalid', token))
            if not valid:
                return False
            if confirm:
                self._conn.execute('DELETE FROM transactions WHERE user_id=? AND seq=?', (user_id, row['seq']))
            return True
