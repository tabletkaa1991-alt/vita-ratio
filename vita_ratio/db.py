"""SQLite: подключение и инициализация схемы (с миграциями старых баз)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import ROOT

SCHEMA_PATH = ROOT / "schema.sql"

# Колонки, добавленные после первой версии: старые базы дополняются ALTER TABLE.
MIGRATIONS: dict[str, dict[str, str]] = {
    "profiles": {
        "goal_weight_kg": "REAL",
        "goal_date": "TEXT",
        "ai_enabled": "INTEGER NOT NULL DEFAULT 0",
        "sub_until": "TEXT",
        "ai_until": "TEXT",
        "theme_accent": "TEXT NOT NULL DEFAULT '#B7F75C'",
        "theme_bg": "TEXT NOT NULL DEFAULT '#0E1116'",
        "theme_card": "TEXT NOT NULL DEFAULT '#151A21'",
    },
    "meals": {
        "grams": "REAL NOT NULL DEFAULT 0",
        "food_key": "TEXT NOT NULL DEFAULT ''",
        "items_json": "TEXT NOT NULL DEFAULT '[]'",
    },
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Открывает БД, создаёт папку, включает FK и WAL. Row доступен по имени."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row[1]) for row in rows}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Добавляет недостающие колонки в существующую базу. Возвращает список изменений."""
    applied: list[str] = []
    for table, columns in MIGRATIONS.items():
        existing = _table_columns(conn, table)
        if not existing:
            continue
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                applied.append(f"{table}.{name}")
    return applied


#: DDL таблиц платежей с расширенным CHECK kind (base/ai/pro). SQLite не умеет
#: менять CHECK-ограничение через ALTER TABLE, поэтому таблицы пересоздаются.
_PAYMENTS_DDL = """
CREATE TABLE payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('base', 'ai', 'pro')),
    charge_id  TEXT    NOT NULL UNIQUE,
    amount     INTEGER NOT NULL,
    currency   TEXT    NOT NULL DEFAULT 'XTR',
    payload    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

_INVOICES_DDL = """
CREATE TABLE invoices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('base', 'ai', 'pro')),
    provider    TEXT    NOT NULL DEFAULT 'yookassa',
    external_id TEXT    NOT NULL UNIQUE,
    amount_rub  REAL    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'canceled')),
    payload     TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

_PAYMENTS_COLS = "id, user_id, kind, charge_id, amount, currency, payload, created_at"
_INVOICES_COLS = "id, user_id, kind, provider, external_id, amount_rub, status, payload, created_at"


def _table_has_pro_kind(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
    except sqlite3.DatabaseError:
        return True
    return bool(row and "kind IN ('base', 'ai', 'pro')" in str(row["sql"] or ""))


def _migrate_payment_kinds(conn: sqlite3.Connection) -> list[str]:
    """Расширяет CHECK kind у payments/invoices до base/ai/pro (идемпотентно).

    Существующие строки переносятся в пересозданные таблицы без потерь.
    Возвращает имена пересозданных таблиц.
    """
    applied: list[str] = []
    for table, ddl, cols in (
        ("payments", _PAYMENTS_DDL, _PAYMENTS_COLS),
        ("invoices", _INVOICES_DDL, _INVOICES_COLS),
    ):
        if _table_has_pro_kind(conn, table):
            continue
        tmp = f"{table}_new"
        conn.execute(ddl.replace(f"CREATE TABLE {table}", f"CREATE TABLE {tmp}"))
        conn.execute(f"INSERT INTO {tmp} ({cols}) SELECT {cols} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
        applied.append(table)
    if "invoices" in applied:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices(user_id)"
        )
    return applied


def init_db(conn: sqlite3.Connection) -> None:
    """Создаёт таблицы из schema.sql и догоняет схему миграциями (идемпотентно)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    migrate(conn)
    _migrate_payment_kinds(conn)
    conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
