"""Transactional schema upgrades. Caller owns BEGIN/COMMIT and rollback."""
import sqlite3


def statements(conn: sqlite3.Connection, schema: str) -> None:
    statement = ''
    for line in schema.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ''
    if statement.strip():
        conn.execute(statement)


def migrate(conn: sqlite3.Connection, schema: str) -> None:
    if conn.execute('PRAGMA user_version').fetchone()[0] > 1:
        raise ValueError('Database schema newer than this application')
    statements(conn, schema)
    user_columns = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
    if 'currency' not in user_columns:
        conn.execute('ALTER TABLE users ADD COLUMN currency TEXT')
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(transactions)')}
    if 'currency' not in columns:
        conn.execute("ALTER TABLE transactions ADD COLUMN currency TEXT NOT NULL DEFAULT 'IDR'")
    if 'seq' not in columns:
        conn.execute('ALTER TABLE transactions RENAME TO transactions_old')
        conn.execute('DROP INDEX IF EXISTS idx_tx_user_time')
        statements(conn, schema)
        conn.execute('''INSERT INTO transactions(user_id,seq,kind,amount,currency,category,note,occurred_at,created_at)
            SELECT user_id,ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY occurred_at,id),
            kind,amount,currency,category,note,occurred_at,created_at FROM transactions_old''')
        conn.execute('DROP TABLE transactions_old')
    conn.execute('CREATE TABLE IF NOT EXISTS user_sequences(user_id INTEGER PRIMARY KEY, last_seq INTEGER NOT NULL)')
    conn.execute('''INSERT INTO user_sequences(user_id,last_seq)
        SELECT user_id,MAX(seq) FROM transactions GROUP BY user_id
        ON CONFLICT(user_id) DO UPDATE SET last_seq=MAX(last_seq,excluded.last_seq)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS deletion_confirmations(
        token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,snapshot TEXT NOT NULL,expires_at REAL NOT NULL,
        message_id INTEGER,state TEXT NOT NULL DEFAULT 'pending')''')
    conn.execute('PRAGMA user_version=1')
