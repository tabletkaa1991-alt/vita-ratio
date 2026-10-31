"""Бесплатный доступ к боту/подписке для отдельных людей (CONTRACT §29).

Whitelist хранится в двух местах:

* Render-переменные ``FREE_ACCESS_IDS`` / ``FREE_ACCESS_USERNAMES`` — статический
  список из окружения (изменение требует рестарта);
* таблица ``free_access`` в SQLite — управляется прямо из бота командами
  ``/grant`` и ``/revoke`` (без пересборки и рестарта).

Значение whitelist нормализуется: ``strip()``, без ведущего ``@``, нижний
регистр. Числовой Telegram ID хранится строкой как есть (``"123456789"``),
поэтому в ``free_access.value`` может лежать либо ID, либо username без ``@``.

Ошибки SQLite (например, таблицы ещё нет в старой базе) не роняют гейт:
такие проверки считаются «нет совпадений».
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .config import Settings


def normalize(value: Any) -> str:
    """Нормализованное значение whitelist: ``strip``, без ``@``, lower.

    Цифры возвращаются как есть (Telegram ID). ``None``/мусор -> ``""``.
    """
    if value is None:
        return ""
    try:
        text = str(value)
    except Exception:  # noqa: BLE001 — экзотический объект не должен ронять гейт
        return ""
    return text.strip().lstrip("@").strip().lower()


def _ids(value: str) -> set[int]:
    result: set[int] = set()
    for chunk in (value or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            result.add(int(chunk))
    return result


def _usernames(value: str) -> set[str]:
    result: set[str] = set()
    for chunk in (value or "").replace(";", ",").split(","):
        name = normalize(chunk)
        if name:
            result.add(name)
    return result


def _row_get(row: Any, key: str, index: int) -> Any:
    """Поле строки БД по имени (sqlite3.Row/dict) или по индексу (tuple)."""
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        try:
            return row[index]
        except (TypeError, IndexError, KeyError):
            return None


def _has_value(conn: Any, value: str) -> bool:
    """Есть ли значение в ``free_access``; ошибки SQLite -> False."""
    if not value or conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM free_access WHERE value = ? LIMIT 1", (value,)
        ).fetchone()
    except (sqlite3.Error, AttributeError, TypeError):
        return False
    return row is not None


def is_free(
    settings: Settings,
    user_id: int | None = None,
    username: str | None = None,
    conn: Any = None,
) -> bool:
    """True, если пользователь в whitelist бесплатного доступа (мусор -> False).

    Сначала проверяются списки из env, затем — если передан ``conn`` — таблица
    ``free_access`` (доступ, выданный из бота).
    """
    uid: int | None = None
    if user_id is not None:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            uid = None
        if uid is not None and uid in _ids(settings.free_access_ids):
            return True
    name = normalize(username)
    if name and name in _usernames(settings.free_access_usernames):
        return True
    if conn is None:
        return False
    if uid is not None and _has_value(conn, str(uid)):
        return True
    return bool(name) and _has_value(conn, name)


def list_free(conn: Any) -> list[dict]:
    """Строки ``free_access``: ``[{id, value, created_at}]`` (новые снизу).

    Нет таблицы/ошибка SQLite -> пустой список.
    """
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, value, created_at FROM free_access ORDER BY id"
        ).fetchall()
    except (sqlite3.Error, AttributeError, TypeError):
        return []
    result: list[dict] = []
    for row in rows:
        value = _row_get(row, "value", 1)
        if value is None:
            continue
        result.append(
            {
                "id": _row_get(row, "id", 0),
                "value": str(value),
                "created_at": _row_get(row, "created_at", 2),
            }
        )
    return result


def add_free(conn: Any, value: str) -> bool:
    """Добавляет значение в ``free_access``. False — уже был/ошибка/пусто.

    Значение нормализуется (:func:`normalize`), вставка идемпотентна
    (``INSERT OR IGNORE`` по UNIQUE-колонке ``value``).
    """
    normalized = normalize(value)
    if not normalized or conn is None:
        return False
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO free_access (value) VALUES (?)", (normalized,)
        )
        conn.commit()
    except (sqlite3.Error, AttributeError, TypeError):
        return False
    return cursor.rowcount > 0


def remove_free(conn: Any, value: str) -> bool:
    """Удаляет значение из ``free_access``. False — не найден/ошибка/пусто."""
    normalized = normalize(value)
    if not normalized or conn is None:
        return False
    try:
        cursor = conn.execute("DELETE FROM free_access WHERE value = ?", (normalized,))
        conn.commit()
    except (sqlite3.Error, AttributeError, TypeError):
        return False
    return cursor.rowcount > 0


def free_usernames(settings: Settings) -> list[str]:
    """Список ников из env для отладки/логов/``/free_list`` (без секретов)."""
    return sorted(_usernames(settings.free_access_usernames))


def free_ids(settings: Settings) -> list[int]:
    """Список ID из env для отладки/логов/``/free_list``."""
    return sorted(_ids(settings.free_access_ids))
