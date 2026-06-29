"""
Database layer for OMC Portal.

Uses PostgreSQL when DATABASE_URL is set (e.g. a free Neon database, which
persists across deploys/restarts), otherwise falls back to a local SQLite file
for development. A thin connection wrapper exposes a sqlite3-style
`.execute(sql, params)` returning an object with `.fetchone()/.fetchall()` and
`.lastrowid`, so the rest of the app is dialect-agnostic. Placeholders are
written as `?` everywhere and translated to `%s` for Postgres automatically.
"""
import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "omc.db")
IS_PG = bool(DATABASE_URL)


class Result:
    def __init__(self, rows, lastrowid):
        self._rows = rows
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class SQLiteConn:
    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_PATH)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        rows = cur.fetchall() if cur.description else []
        return Result(rows, cur.lastrowid)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


class PGConn:
    def __init__(self):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        self._dict_cursor = RealDictCursor
        self.conn = psycopg2.connect(DATABASE_URL)

    def execute(self, sql, params=()):
        cur = self.conn.cursor(cursor_factory=self._dict_cursor)
        cur.execute(sql.replace("?", "%s"), params)
        rows = cur.fetchall() if cur.description else []
        lastrowid = rows[0]["id"] if (rows and "id" in rows[0]) else None
        cur.close()
        return Result(rows, lastrowid)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def connect():
    return PGConn() if IS_PG else SQLiteConn()


def init(schema):
    """Create tables. Translates the SQLite schema for Postgres."""
    conn = connect()
    if IS_PG:
        schema = schema.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
        cur = conn.conn.cursor()
        cur.execute(schema)
        conn.conn.commit()
        cur.close()
    else:
        conn.conn.executescript(schema)
        conn.conn.commit()
    conn.close()
