"""SQLite 存档层：单存档槽（id=1），所有状态与记忆持久化在 save.db。"""

import os
import sqlite3
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "save.db")

_lock = threading.RLock()

LEGACY_TS_FLOOR = 10_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS save (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    girl TEXT NOT NULL,
    persona TEXT NOT NULL,
    likes TEXT NOT NULL,
    dislikes TEXT NOT NULL,
    affinity INTEGER NOT NULL,
    mood INTEGER NOT NULL,
    stamina INTEGER NOT NULL,
    coins INTEGER NOT NULL,
    exp INTEGER NOT NULL,
    game_time INTEGER NOT NULL DEFAULT 0,
    tick_mark INTEGER NOT NULL DEFAULT 0,
    last_tick INTEGER NOT NULL,
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cooldowns (
    key TEXT PRIMARY KEY,
    ready_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS gift_counts (
    item_id TEXT PRIMARY KEY,
    n INTEGER NOT NULL
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, connect() as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(save)")}
        if "game_time" not in columns:
            conn.execute("ALTER TABLE save ADD COLUMN game_time INTEGER NOT NULL DEFAULT 0")
        if "tick_mark" not in columns:
            conn.execute("ALTER TABLE save ADD COLUMN tick_mark INTEGER NOT NULL DEFAULT 0")


def get_save():
    with _lock, connect() as conn:
        row = conn.execute("SELECT * FROM save WHERE id = 1").fetchone()
        return dict(row) if row else None


def put_save(data):
    cols = [
        "girl", "persona", "likes", "dislikes", "affinity", "mood",
        "stamina", "coins", "exp", "game_time", "tick_mark",
        "last_tick", "created_ts", "updated_ts",
    ]
    values = [data[c] for c in cols]
    with _lock, connect() as conn:
        placeholders = ",".join("?" * len(cols))
        conn.execute(
            "INSERT INTO save (id, {}) VALUES (1, {}) "
            "ON CONFLICT(id) DO UPDATE SET {}".format(
                ",".join(cols),
                placeholders,
                ",".join("{}=excluded.{}".format(c, c) for c in cols),
            ),
            values,
        )


def wipe():
    with _lock, connect() as conn:
        for table in ("save", "messages", "memories", "events", "cooldowns", "gift_counts"):
            conn.execute("DELETE FROM {}".format(table))


def rebase_timestamps(value):
    """旧存档的 ts 存的是现实时间戳，换游戏时钟后统一归到开局时刻（内容不动）。"""
    with _lock, connect() as conn:
        for table in ("messages", "memories", "events"):
            conn.execute(
                "UPDATE {} SET ts = ? WHERE ts > ?".format(table),
                (value, LEGACY_TS_FLOOR),
            )


def clear_cooldowns():
    """冷却原先按现实秒记，改成游戏分钟后旧值一律作废。"""
    with _lock, connect() as conn:
        conn.execute("DELETE FROM cooldowns")


def add_message(role, content, ts):
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO messages (role, content, ts) VALUES (?,?,?)",
            (role, content, ts),
        )


def recent_messages(limit):
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def message_count():
    with _lock, connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]


def add_memory(kind, content, ts):
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO memories (kind, content, ts) VALUES (?,?,?)",
            (kind, content, ts),
        )


def recent_memories(limit):
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT kind, content FROM memories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def add_event(kind, text, ts):
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO events (kind, text, ts) VALUES (?,?,?)", (kind, text, ts)
        )


def recent_events(limit):
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT kind, text, ts FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_cooldown(key):
    with _lock, connect() as conn:
        row = conn.execute(
            "SELECT ready_ts FROM cooldowns WHERE key = ?", (key,)
        ).fetchone()
        return row["ready_ts"] if row else 0


def set_cooldown(key, ready_ts):
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO cooldowns (key, ready_ts) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET ready_ts=excluded.ready_ts",
            (key, ready_ts),
        )


def gift_count(item_id):
    with _lock, connect() as conn:
        row = conn.execute(
            "SELECT n FROM gift_counts WHERE item_id = ?", (item_id,)
        ).fetchone()
        return row["n"] if row else 0


def bump_gift_count(item_id):
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO gift_counts (item_id, n) VALUES (?,1) "
            "ON CONFLICT(item_id) DO UPDATE SET n = n + 1",
            (item_id,),
        )
