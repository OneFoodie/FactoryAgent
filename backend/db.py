# -*- coding: utf-8 -*-
"""SQLite 数据层：连接管理 + 建表 + 通用查询助手。

真实数据库文件：backend/factory.db（首次运行自动创建并可由 seed.py 灌入测试数据源）。
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "factory.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    device_total INTEGER NOT NULL DEFAULT 0,
    device_online INTEGER NOT NULL DEFAULT 0,
    shift_output INTEGER NOT NULL DEFAULT 0,
    takt        REAL,
    takt_target REAL,
    oee         REAL,
    fpy         REAL
);

CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    line_code   TEXT NOT NULL,
    state       TEXT NOT NULL,
    load_pct    REAL,
    metrics_json TEXT,
    note        TEXT,
    foot        TEXT,
    ref         TEXT,
    since       TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    level       TEXT NOT NULL,
    title       TEXT NOT NULL,
    device_code TEXT,
    line_code   TEXT,
    occurred_at TEXT,
    detail      TEXT,
    sop_ref     TEXT,
    status      TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS work_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL,
    priority    TEXT NOT NULL,
    device_code TEXT,
    line_code   TEXT,
    assignee    TEXT,
    remaining   TEXT,
    sop_ref     TEXT,
    confidence  INTEGER,
    hint_cnt    INTEGER,
    hit_cnt     INTEGER,
    done_at     TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL,
    key         TEXT NOT NULL,
    label       TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    prev_value  REAL,
    delta       REAL,
    target      REAL,
    attainment  REAL,
    trend       TEXT,
    extra_json  TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stat_date   TEXT NOT NULL,
    line_code   TEXT NOT NULL,
    output      INTEGER,
    fpy         REAL,
    oee         REAL,
    downtime_h  REAL,
    energy_int  REAL,
    UNIQUE(stat_date, line_code)
);

CREATE TABLE IF NOT EXISTS sop_docs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    category    TEXT,
    device_code TEXT,
    content     TEXT NOT NULL,
    source      TEXT
);
"""

# 知识库全文检索：FTS5 三元组分词（适配中文），外部内容模式与 sop_docs 联动
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS sop_fts USING fts5(
    code, title, content,
    content='sop_docs', content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS sop_ai AFTER INSERT ON sop_docs BEGIN
    INSERT INTO sop_fts(rowid, code, title, content)
    VALUES (new.id, new.code, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS sop_ad AFTER DELETE ON sop_docs BEGIN
    INSERT INTO sop_fts(sop_fts, rowid, code, title, content)
    VALUES ('delete', old.id, old.code, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS sop_au AFTER UPDATE ON sop_docs BEGIN
    INSERT INTO sop_fts(sop_fts, rowid, code, title, content)
    VALUES ('delete', old.id, old.code, old.title, old.content);
    INSERT INTO sop_fts(rowid, code, title, content)
    VALUES (new.id, new.code, new.title, new.content);
END;
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(FTS_SCHEMA)


def rebuild_fts() -> None:
    """重建知识库全文索引（外部内容模式下插入触发器不覆盖存量，需手动 rebuild）。"""
    with get_conn() as conn:
        conn.execute("INSERT INTO sop_fts(sop_fts) VALUES('rebuild')")


def query(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> None:
    with get_conn() as conn:
        conn.execute(sql, params)


if __name__ == "__main__":
    init_db()
    print(f"database ready at {DB_PATH}")
