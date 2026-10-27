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
        "theme_accent": "TEXT NOT NULL DEFAULT '#B7F75C'",
        "theme_bg": "TEXT NOT NULL DEFAULT '#0E1116'",
        "theme_card": "TEXT NOT NULL DEFAULT '#151A21'",
    },
    "meals": {
        "grams": "REAL NOT NULL DEFAULT 0",
        "food_key": "TEXT NOT NULL DEFAULT ''",
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


def init_db(conn: sqlite3.Connection) -> None:
    """Создаёт таблицы из schema.sql и догоняет схему миграциями (идемпотентно)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    migrate(conn)
    conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
