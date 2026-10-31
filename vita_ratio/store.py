"""Репозитории поверх sqlite3 для Vita Ratio.

Все функции синхронные, принимают открытое соединение ``sqlite3.Connection``
(см. :mod:`vita_ratio.db`) и возвращают обычные ``dict`` / ``list[dict]``,
готовые к JSON-сериализации. Доменная математика (цели, планы, инсайты) живёт
в :mod:`vita_ratio.calc` — здесь только SQL и нормализация типов.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date as date_cls
from datetime import datetime, timedelta

from . import calc

log = logging.getLogger("vita_ratio.store")

#: Поля профиля, которые приходят из API (порядок важен для INSERT).
PROFILE_FIELDS = (
    "sex",
    "age",
    "height_cm",
    "weight_kg",
    "activity",
    "goal_rate",
    "protein_per_kg",
    "sleep_bed",
    "sleep_wake",
    "reminders",
    "ai_enabled",
    "timezone",
    "goal_weight_kg",
    "goal_date",
    "theme_accent",
    "theme_bg",
    "theme_card",
)

#: Поля профиля, которые можно осознанно сбросить в NULL (пустая цель/дата).
PROFILE_NULLABLE = frozenset({"goal_weight_kg", "goal_date"})

#: Редактируемые поля занятия.
CLASS_FIELDS = ("title", "kind", "weekday", "start_time", "duration_min", "place", "note", "active")

#: Редактируемые поля блока плана дня.
DAY_PLAN_FIELDS = ("date", "time", "title", "kind", "duration_min", "note", "done")

#: Дефолтная палитра (совпадает с DEFAULTS в schema.sql и calc/UI).
THEME_DEFAULTS = {
    "theme_accent": "#B7F75C",
    "theme_bg": "#0E1116",
    "theme_card": "#151A21",
}

_PROFILE_DEFAULTS = {
    "sex": "male",
    "age": 25,
    "height_cm": 175.0,
    "weight_kg": 70.0,
    "activity": "moderate",
    "goal_rate": 0.35,
    "protein_per_kg": 2.0,
    "sleep_bed": "23:00",
    "sleep_wake": "07:00",
    "reminders": 1,
    "ai_enabled": 0,
    "timezone": "Europe/Moscow",
    "goal_weight_kg": None,
    "goal_date": None,
    **THEME_DEFAULTS,
}


# --- служебные -----------------------------------------------------------------

def _now_iso() -> str:
    """Локальное время сервера без микросекунд: 2026-10-27T13:00:00."""
    return datetime.now().replace(microsecond=0).isoformat()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _rows(rows) -> list[dict]:
    return [dict(item) for item in rows]


def _as_flag(value) -> int:
    if isinstance(value, str):
        return 0 if value.strip().lower() in {"", "0", "false", "no", "off"} else 1
    return 1 if value else 0


def _default_date_to(date_to: str | None) -> str:
    return str(date_to) if date_to else calc.local_today()


# --- пользователи ---------------------------------------------------------------

def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    return _row(conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone())


def upsert_user(
    conn: sqlite3.Connection,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> dict:
    """Создаёт пользователя или обновляет известные имена (None не затирает старое)."""
    uid = int(user_id)
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO users (id, username, first_name, last_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            username   = COALESCE(excluded.username, users.username),
            first_name = COALESCE(excluded.first_name, users.first_name),
            last_name  = COALESCE(excluded.last_name, users.last_name),
            updated_at = excluded.updated_at
        """,
        (uid, username, first_name, last_name, now, now),
    )
    conn.commit()
    return get_user(conn, uid) or {"id": uid}


# --- профиль -------------------------------------------------------------------

def get_profile(conn: sqlite3.Connection, user_id: int) -> dict | None:
    return _row(
        conn.execute("SELECT * FROM profiles WHERE user_id = ?", (int(user_id),)).fetchone()
    )


def upsert_profile(conn: sqlite3.Connection, user_id: int, data: dict) -> dict:
    """Создаёт/обновляет профиль, недостающие поля берёт из текущей записи.

    ``None`` в ``goal_weight_kg``/``goal_date`` — осознанный сброс цели,
    для остальных полей ``None`` означает «не менять».
    """
    uid = int(user_id)
    current = get_profile(conn, uid) or {}
    values: dict = {}
    for field in PROFILE_FIELDS:
        if field in data:
            if data[field] is None and field not in PROFILE_NULLABLE:
                values[field] = current.get(field, _PROFILE_DEFAULTS.get(field))
            else:
                values[field] = data[field]
        elif field in current:
            values[field] = current[field]
    for field, default in _PROFILE_DEFAULTS.items():
        values.setdefault(field, default)
    values["reminders"] = _as_flag(values["reminders"])
    values["ai_enabled"] = _as_flag(values["ai_enabled"])

    columns = ["user_id", *PROFILE_FIELDS, "updated_at"]
    params = [uid, *[values[field] for field in PROFILE_FIELDS], _now_iso()]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{field} = excluded.{field}" for field in PROFILE_FIELDS)
    updates += ", updated_at = excluded.updated_at"
    conn.execute(
        f"INSERT INTO profiles ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(user_id) DO UPDATE SET {updates}",
        params,
    )
    conn.commit()
    return get_profile(conn, uid) or {}


# --- приёмы пищи ----------------------------------------------------------------

def parse_items(value) -> list[dict]:
    """JSON-массив ингредиентов из ``meals.items_json`` -> list[dict] (мусор -> [])."""
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)]


def _meal_row(row: sqlite3.Row | None) -> dict | None:
    """Строка meals -> dict, где ``items`` уже распарсен (старые записи -> [])."""
    data = _row(row)
    if data is None:
        return None
    data["items"] = parse_items(data.get("items_json"))
    return data


def get_meal(conn: sqlite3.Connection, user_id: int, meal_id: int) -> dict | None:
    return _meal_row(
        conn.execute(
            "SELECT * FROM meals WHERE id = ? AND user_id = ?",
            (int(meal_id), int(user_id)),
        ).fetchone()
    )


def add_meal(
    conn: sqlite3.Connection,
    user_id: int,
    date: str,
    time: str,
    title: str,
    kcal: float = 0,
    protein: float = 0,
    fat: float = 0,
    carbs: float = 0,
    note: str = "",
    grams: float = 0,
    food_key: str = "",
    items: list[dict] | None = None,
) -> dict:
    """Добавляет приём пищи; ``items`` — ингредиенты, сохраняются в JSON."""
    cursor = conn.execute(
        """
        INSERT INTO meals (user_id, date, time, title, kcal, protein, fat, carbs,
                           grams, food_key, items_json, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            str(date),
            str(time),
            str(title),
            float(kcal),
            float(protein),
            float(fat),
            float(carbs),
            float(grams or 0),
            str(food_key or ""),
            json.dumps(items or [], ensure_ascii=False),
            str(note or ""),
        ),
    )
    conn.commit()
    return get_meal(conn, user_id, int(cursor.lastrowid)) or {}


def list_meals(conn: sqlite3.Connection, user_id: int, date: str) -> list[dict]:
    return [
        meal
        for meal in (
            _meal_row(row)
            for row in conn.execute(
                "SELECT * FROM meals WHERE user_id = ? AND date = ? ORDER BY time, id",
                (int(user_id), str(date)),
            )
        )
        if meal is not None
    ]


def delete_meal(conn: sqlite3.Connection, user_id: int, meal_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM meals WHERE id = ? AND user_id = ?", (int(meal_id), int(user_id))
    )
    conn.commit()
    return cursor.rowcount > 0


def meal_totals(conn: sqlite3.Connection, user_id: int, date: str) -> dict:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(kcal), 0.0)    AS kcal,
               COALESCE(SUM(protein), 0.0) AS protein,
               COALESCE(SUM(fat), 0.0)     AS fat,
               COALESCE(SUM(carbs), 0.0)   AS carbs
        FROM meals
        WHERE user_id = ? AND date = ?
        """,
        (int(user_id), str(date)),
    ).fetchone()
    return {
        "kcal": float(row["kcal"]),
        "protein": float(row["protein"]),
        "fat": float(row["fat"]),
        "carbs": float(row["carbs"]),
    }


# --- сон -----------------------------------------------------------------------

def get_sleep(conn: sqlite3.Connection, user_id: int, date: str) -> dict | None:
    return _row(
        conn.execute(
            "SELECT * FROM sleep_logs WHERE user_id = ? AND date = ?",
            (int(user_id), str(date)),
        ).fetchone()
    )


def upsert_sleep(
    conn: sqlite3.Connection,
    user_id: int,
    date: str,
    bed_time: str,
    wake_time: str,
    duration_h: float | None = None,
    quality: int = 3,
    note: str = "",
) -> dict:
    """Запись сна по дате пробуждения; повторный POST обновляет её."""
    uid = int(user_id)
    day = str(date)
    if duration_h is None:
        duration_h = calc.duration_between(bed_time, wake_time)
    conn.execute(
        """
        INSERT INTO sleep_logs (user_id, date, bed_time, wake_time, duration_h, quality, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            bed_time   = excluded.bed_time,
            wake_time  = excluded.wake_time,
            duration_h = excluded.duration_h,
            quality    = excluded.quality,
            note       = excluded.note
        """,
        (uid, day, str(bed_time), str(wake_time), float(duration_h), int(quality), str(note or "")),
    )
    conn.commit()
    return get_sleep(conn, uid, day) or {}


def sleep_week(conn: sqlite3.Connection, user_id: int, date_to: str, days: int = 7) -> list[dict]:
    """Записи сна за ``days`` дней по дату ``date_to`` включительно (по возрастанию даты)."""
    end = date_cls.fromisoformat(str(date_to))
    start = end - timedelta(days=max(int(days), 1) - 1)
    return _rows(
        conn.execute(
            """
            SELECT * FROM sleep_logs
            WHERE user_id = ? AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (int(user_id), start.isoformat(), end.isoformat()),
        )
    )


# --- вес -----------------------------------------------------------------------

def get_weight(conn: sqlite3.Connection, user_id: int, date: str) -> dict | None:
    return _row(
        conn.execute(
            "SELECT * FROM weights WHERE user_id = ? AND date = ?",
            (int(user_id), str(date)),
        ).fetchone()
    )


def add_weight(conn: sqlite3.Connection, user_id: int, date: str, kg: float, note: str = "") -> dict:
    uid = int(user_id)
    day = str(date)
    conn.execute(
        """
        INSERT INTO weights (user_id, date, kg, note)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            kg   = excluded.kg,
            note = excluded.note
        """,
        (uid, day, float(kg), str(note or "")),
    )
    conn.commit()
    return get_weight(conn, uid, day) or {}


def list_weights(
    conn: sqlite3.Connection,
    user_id: int,
    days: int = 60,
    date_to: str | None = None,
) -> list[dict]:
    """Взвешивания за последние ``days`` дней (по возрастанию даты)."""
    end = date_cls.fromisoformat(_default_date_to(date_to))
    start = end - timedelta(days=max(int(days), 1) - 1)
    return _rows(
        conn.execute(
            """
            SELECT * FROM weights
            WHERE user_id = ? AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (int(user_id), start.isoformat(), end.isoformat()),
        )
    )


def weight_trend(conn: sqlite3.Connection, user_id: int, days: int = 21, date_to: str | None = None) -> float:
    """Тренд веса, кг/неделю: наклон линейной регрессии по датам."""
    rows = list_weights(conn, user_id, days=days, date_to=date_to)
    if len(rows) < 2:
        return 0.0
    base = date_cls.fromisoformat(rows[0]["date"])
    xs = [float((date_cls.fromisoformat(row["date"]) - base).days) for row in rows]
    ys = [float(row["kg"]) for row in rows]
    if xs[-1] == xs[0]:
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    return round(slope * 7.0, 2)


def goal_weights(
    conn: sqlite3.Connection,
    user_id: int,
    profile: dict | None = None,
    days: int = 60,
    date_to: str | None = None,
) -> dict:
    """Стартовый и текущий вес для цели по весу.

    Стартовый = самое старое взвешивание за ``days`` дней, текущий = последнее;
    если взвешиваний нет — оба берутся из ``profiles.weight_kg``.
    """
    rows = list_weights(conn, user_id, days=days, date_to=date_to)
    fallback = (profile or {}).get("weight_kg")
    fallback = float(fallback) if fallback else None
    start = float(rows[0]["kg"]) if rows else fallback
    latest = conn.execute(
        "SELECT kg FROM weights WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 1",
        (int(user_id),),
    ).fetchone()
    current = float(latest["kg"]) if latest is not None else fallback
    return {
        "start_weight_kg": round(start, 1) if start else None,
        "current_weight_kg": round(current, 1) if current else None,
    }


#: Допустимые значения самочувствия в недельном чек-ине (CONTRACT §14).
WEEKLY_FEELINGS = ("good", "ok", "bad")


# --- недельный чек-ин -----------------------------------------------------------

def get_weekly_checkin(conn: sqlite3.Connection, user_id: int, week_start: str) -> dict | None:
    """Чек-ин пользователя за конкретную ISO-неделю (по понедельнику)."""
    return _row(
        conn.execute(
            "SELECT * FROM weekly_checkins WHERE user_id = ? AND week_start = ?",
            (int(user_id), str(week_start)),
        ).fetchone()
    )


def upsert_weekly_checkin(
    conn: sqlite3.Connection,
    user_id: int,
    week_start: str,
    weight_kg: float,
    feeling: str = "ok",
    note: str = "",
) -> dict:
    """Создаёт/обновляет чек-ин за неделю (UNIQUE user_id + week_start)."""
    uid = int(user_id)
    start = str(week_start)
    conn.execute(
        """
        INSERT INTO weekly_checkins (user_id, week_start, weight_kg, feeling, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, week_start) DO UPDATE SET
            weight_kg = excluded.weight_kg,
            feeling   = excluded.feeling,
            note      = excluded.note
        """,
        (uid, start, float(weight_kg), str(feeling or "ok"), str(note or "")),
    )
    conn.commit()
    return get_weekly_checkin(conn, uid, start) or {}


def last_weekly_checkin(conn: sqlite3.Connection, user_id: int) -> dict | None:
    """Последний чек-ин пользователя по убыванию недели (или None)."""
    return _row(
        conn.execute(
            "SELECT * FROM weekly_checkins WHERE user_id = ? ORDER BY week_start DESC LIMIT 1",
            (int(user_id),),
        ).fetchone()
    )


def list_weekly_checkins(conn: sqlite3.Connection, user_id: int, limit: int = 12) -> list[dict]:
    """История чек-инов по убыванию недели."""
    return _rows(
        conn.execute(
            "SELECT * FROM weekly_checkins WHERE user_id = ? ORDER BY week_start DESC LIMIT ?",
            (int(user_id), max(int(limit), 1)),
        )
    )


# --- заметки -------------------------------------------------------------------

def list_notes(conn: sqlite3.Connection, user_id: int, limit: int = 30) -> list[dict]:
    """Заметки пользователя по убыванию id (новые сверху), до ``limit`` штук.

    Каждая запись: ``{"id", "date", "text", "ai_text", "created_at"}``;
    ``ai_text`` пустая строка, если ИИ-разбора не было (флаг ai_enabled выключен).
    """
    return _rows(
        conn.execute(
            """
            SELECT id, date, text, ai_text, created_at
            FROM notes
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(user_id), max(int(limit), 1)),
        )
    )


# --- свободный ИИ-чат ----------------------------------------------------------

#: Роли сообщений в ``ai_chat`` (CHECK в schema.sql).
CHAT_ROLES = ("user", "assistant")


def add_chat_message(
    conn: sqlite3.Connection, user_id: int, role: str, text: str
) -> dict:
    """Добавляет сообщение в ``ai_chat`` и возвращает ``{id, role, text, created_at}``.

    ``role`` — только ``user``/``assistant``; пустой текст/роль — ``ValueError``
    (валидация длины и текста остаётся на вызывающем слое: API/бот).
    """
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in CHAT_ROLES:
        raise ValueError("role должен быть user или assistant")
    content = str(text or "").strip()
    if not content:
        raise ValueError("text не может быть пустым")
    cursor = conn.execute(
        "INSERT INTO ai_chat (user_id, role, text) VALUES (?, ?, ?)",
        (int(user_id), normalized_role, content),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, role, text, created_at FROM ai_chat WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _row(row) or {
        "id": int(cursor.lastrowid or 0),
        "role": normalized_role,
        "text": content,
        "created_at": "",
    }


def list_chat_messages(
    conn: sqlite3.Connection, user_id: int, limit: int = 30
) -> list[dict]:
    """Последние ``limit`` сообщений чата в **хронологическом** порядке.

    Из БД берём новые сверху (``ORDER BY id DESC LIMIT``), затем разворачиваем
    список — для ленты чата и контекста модели нужен порядок «сверху вниз».
    """
    try:
        cap = max(int(limit), 1)
    except (TypeError, ValueError):
        cap = 30
    rows = conn.execute(
        """
        SELECT id, role, text, created_at
        FROM ai_chat
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(user_id), cap),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def clear_chat(conn: sqlite3.Connection, user_id: int) -> int:
    """Удаляет всю историю чата пользователя. Возвращает число удалённых строк."""
    cursor = conn.execute("DELETE FROM ai_chat WHERE user_id = ?", (int(user_id),))
    conn.commit()
    return int(cursor.rowcount or 0)


# --- занятия -------------------------------------------------------------------

def get_class(conn: sqlite3.Connection, user_id: int, class_id: int) -> dict | None:
    return _row(
        conn.execute(
            "SELECT * FROM classes WHERE id = ? AND user_id = ?",
            (int(class_id), int(user_id)),
        ).fetchone()
    )


def list_classes(conn: sqlite3.Connection, user_id: int, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM classes WHERE user_id = ?"
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY weekday, start_time, id"
    return _rows(conn.execute(sql, (int(user_id),)))


def create_class(
    conn: sqlite3.Connection,
    user_id: int,
    title: str,
    kind: str,
    weekday: int,
    start_time: str,
    duration_min: int,
    place: str = "",
    note: str = "",
    active: int | bool = 1,
) -> dict:
    cursor = conn.execute(
        """
        INSERT INTO classes (user_id, title, kind, weekday, start_time, duration_min, place, note, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            str(title),
            str(kind),
            int(weekday),
            str(start_time),
            int(duration_min),
            str(place or ""),
            str(note or ""),
            _as_flag(active),
        ),
    )
    conn.commit()
    return get_class(conn, user_id, int(cursor.lastrowid)) or {}


def update_class(
    conn: sqlite3.Connection,
    user_id: int,
    class_id: int,
    data: dict,
) -> dict | None:
    """Частичное обновление занятия; None — занятие не найдено или чужое."""
    current = get_class(conn, user_id, class_id)
    if current is None:
        return None
    values = dict(current)
    for field in CLASS_FIELDS:
        if field in data and data[field] is not None:
            values[field] = _as_flag(data[field]) if field == "active" else data[field]
    conn.execute(
        """
        UPDATE classes
        SET title = ?, kind = ?, weekday = ?, start_time = ?,
            duration_min = ?, place = ?, note = ?, active = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            str(values["title"]),
            str(values["kind"]),
            int(values["weekday"]),
            str(values["start_time"]),
            int(values["duration_min"]),
            str(values["place"] or ""),
            str(values["note"] or ""),
            _as_flag(values["active"]),
            int(class_id),
            int(user_id),
        ),
    )
    conn.commit()
    return get_class(conn, user_id, class_id)


def delete_class(conn: sqlite3.Connection, user_id: int, class_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM classes WHERE id = ? AND user_id = ?", (int(class_id), int(user_id))
    )
    conn.commit()
    return cursor.rowcount > 0


def week_load_min(conn: sqlite3.Connection, user_id: int) -> int:
    """Суммарная длительность активных занятий за неделю (каждый слот повторяется)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(duration_min), 0) AS minutes FROM classes WHERE user_id = ? AND active = 1",
        (int(user_id),),
    ).fetchone()
    return int(row["minutes"])


# --- посещаемость ---------------------------------------------------------------

def get_class_done(conn: sqlite3.Connection, user_id: int, class_id: int, date: str) -> dict | None:
    return _row(
        conn.execute(
            """
            SELECT * FROM class_done
            WHERE user_id = ? AND class_id = ? AND date = ?
            """,
            (int(user_id), int(class_id), str(date)),
        ).fetchone()
    )


def done_map(
    conn: sqlite3.Connection,
    user_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[tuple[int, str], str]:
    """{(class_id, date): status} для быстрой подстановки статусов в расписание."""
    sql = "SELECT class_id, date, status FROM class_done WHERE user_id = ?"
    params: list = [int(user_id)]
    if date_from:
        sql += " AND date >= ?"
        params.append(str(date_from))
    if date_to:
        sql += " AND date <= ?"
        params.append(str(date_to))
    return {
        (int(row["class_id"]), str(row["date"])): str(row["status"])
        for row in conn.execute(sql, params)
    }


def mark_class_done(
    conn: sqlite3.Connection,
    user_id: int,
    class_id: int,
    date: str,
    status: str = "present",
    note: str = "",
) -> dict | None:
    """Отмечает посещение; None — занятие не найдено или чужое."""
    uid = int(user_id)
    cid = int(class_id)
    if get_class(conn, uid, cid) is None:
        return None
    day = str(date)
    conn.execute(
        """
        INSERT INTO class_done (user_id, class_id, date, status, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, class_id, date) DO UPDATE SET
            status = excluded.status,
            note   = excluded.note
        """,
        (uid, cid, day, str(status), str(note or "")),
    )
    conn.commit()
    return get_class_done(conn, uid, cid, day)


# --- напоминания ----------------------------------------------------------------

def reminder_exists(conn: sqlite3.Connection, user_id: int, date: str, kind: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM reminder_log WHERE user_id = ? AND date = ? AND kind = ?",
            (int(user_id), str(date), str(kind)),
        ).fetchone()
        is not None
    )


def mark_reminder(conn: sqlite3.Connection, user_id: int, date: str, kind: str) -> bool:
    """Помечает напоминание отправленным; True — если оно новое (можно отправлять)."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO reminder_log (user_id, date, kind) VALUES (?, ?, ?)",
        (int(user_id), str(date), str(kind)),
    )
    conn.commit()
    return cursor.rowcount > 0


# --- статистика по дням ---------------------------------------------------------

def stats_days(conn: sqlite3.Connection, user_id: int, date_from: str, date_to: str) -> list[dict]:
    """Сводка по дням: калории/БЖУ из meals и длительность/качество из sleep_logs.

    Возвращает по элементу на каждый день диапазона включительно:
    {"date", "kcal", "protein", "fat", "carbs", "meals_count", "sleep_h", "quality"}.
    Дни без данных приходят с нулями и sleep_h=None.
    """
    uid = int(user_id)
    start = date_cls.fromisoformat(str(date_from))
    end = date_cls.fromisoformat(str(date_to))
    if end < start:
        start, end = end, start

    meals = {
        str(row["date"]): row
        for row in conn.execute(
            """
            SELECT date,
                   COALESCE(SUM(kcal), 0.0)    AS kcal,
                   COALESCE(SUM(protein), 0.0) AS protein,
                   COALESCE(SUM(fat), 0.0)     AS fat,
                   COALESCE(SUM(carbs), 0.0)   AS carbs,
                   COUNT(*)                    AS meals_count
            FROM meals
            WHERE user_id = ? AND date BETWEEN ? AND ?
            GROUP BY date
            """,
            (uid, start.isoformat(), end.isoformat()),
        )
    }
    sleep = {
        str(row["date"]): row
        for row in conn.execute(
            """
            SELECT date, duration_h, quality
            FROM sleep_logs
            WHERE user_id = ? AND date BETWEEN ? AND ?
            """,
            (uid, start.isoformat(), end.isoformat()),
        )
    }

    result: list[dict] = []
    cursor = start
    while cursor <= end:
        day = cursor.isoformat()
        meal_row = meals.get(day)
        sleep_row = sleep.get(day)
        result.append(
            {
                "date": day,
                "kcal": float(meal_row["kcal"]) if meal_row else 0.0,
                "protein": float(meal_row["protein"]) if meal_row else 0.0,
                "fat": float(meal_row["fat"]) if meal_row else 0.0,
                "carbs": float(meal_row["carbs"]) if meal_row else 0.0,
                "meals_count": int(meal_row["meals_count"]) if meal_row else 0,
                "sleep_h": round(float(sleep_row["duration_h"]), 1) if sleep_row else None,
                "quality": int(sleep_row["quality"]) if sleep_row else None,
            }
        )
        cursor += timedelta(days=1)
    return result


# --- подписка и платежи (Telegram Stars, CONTRACT §22) -------------------------
#: Допустимые виды платежа: base = подписка на бота, ai = аддон ИИ-разбора.
PAYMENT_KINDS = ("base", "ai")


def get_subscription(conn: sqlite3.Connection, user_id: int) -> dict:
    """Даты подписки пользователя: ``{"sub_until": ISO|None, "ai_until": ISO|None}``.

    Даты — включительные (подписка действует и в день ``until``). Без профиля
    обе даты ``None``. Если старая база ещё без колонок — тоже ``None``.
    """
    try:
        row = conn.execute(
            "SELECT sub_until, ai_until FROM profiles WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
    except sqlite3.Error:
        return {"sub_until": None, "ai_until": None}
    if row is None:
        return {"sub_until": None, "ai_until": None}
    return {
        "sub_until": row["sub_until"] or None,
        "ai_until": row["ai_until"] or None,
    }


def set_subscription(
    conn: sqlite3.Connection,
    user_id: int,
    sub_until: str | None = None,
    ai_until: str | None = None,
) -> dict:
    """Продлевает подписку: меняются только переданные (не ``None``) даты.

    ``sub_until``/``ai_until`` живут в ``profiles`` отдельно от ``PROFILE_FIELDS``,
    поэтому профиль-формат API не расширяется. Профиля нет — запись не создаётся
    (подписка привязана к профилю), возвращаются текущие даты.
    """
    updates: list[str] = []
    params: list = []
    if sub_until is not None:
        updates.append("sub_until = ?")
        params.append(str(sub_until))
    if ai_until is not None:
        updates.append("ai_until = ?")
        params.append(str(ai_until))
    if updates:
        updates.append("updated_at = ?")
        params.extend([_now_iso(), int(user_id)])
        try:
            conn.execute(
                f"UPDATE profiles SET {', '.join(updates)} WHERE user_id = ?", params
            )
            conn.commit()
        except sqlite3.Error:
            log.exception("Не удалось сохранить подписку user_id=%s", user_id)
    return get_subscription(conn, user_id)


def ensure_trial(
    conn: sqlite3.Connection,
    user_id: int,
    days: int,
    today: str | None = None,
) -> dict:
    """Триал новому профилю: если ``sub_until`` пуст, ставит ``today + days``.

    Уже существующая/оплаченная подписка не трогается. Профиля нет — ничего не
    делает (триал создаётся вместе с профилем, CONTRACT §22).
    """
    uid = int(user_id)
    try:
        row = conn.execute(
            "SELECT sub_until FROM profiles WHERE user_id = ?", (uid,)
        ).fetchone()
    except sqlite3.Error:
        return {"sub_until": None, "ai_until": None}
    if row is None or row["sub_until"]:
        return get_subscription(conn, uid)
    try:
        base = date_cls.fromisoformat(str(today) if today else calc.local_today())
    except ValueError:
        base = date_cls.fromisoformat(calc.local_today())
    until = (base + timedelta(days=max(int(days), 0))).isoformat()
    return set_subscription(conn, uid, sub_until=until)


def add_payment(
    conn: sqlite3.Connection,
    user_id: int,
    kind: str,
    charge_id: str,
    amount: int,
    currency: str = "XTR",
    payload: str = "",
) -> bool:
    """Пишет платёж Telegram Stars; ``False`` — ``charge_id`` уже был (идемпотентность).

    ``UNIQUE(charge_id)`` + ``INSERT OR IGNORE`` гарантируют, что повторная
    доставка ``successful_payment`` не продлит подписку второй раз.
    """
    normalized = str(kind or "").strip().lower()
    if normalized not in PAYMENT_KINDS:
        raise ValueError("kind платежа должен быть base или ai")
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO payments (user_id, kind, charge_id, amount, currency, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            normalized,
            str(charge_id),
            int(amount or 0),
            str(currency or "XTR"),
            str(payload or ""),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


# --- рублёвые счета эквайринга (invoices, v6) -----------------------------------

#: Допустимые статусы счёта.
INVOICE_STATUSES = ("pending", "succeeded", "canceled")


def create_invoice(
    conn: sqlite3.Connection,
    user_id: int,
    kind: str,
    provider: str,
    external_id: str,
    amount_rub: float,
    payload: str = "",
) -> int:
    """Создаёт рублёвый счёт и возвращает его ``id``.

    ``external_id`` — id платежа у провайдера (YooKassa payment id / Robokassa
    InvId), уникален (``UNIQUE(external_id)``): повторная вставка — ``IntegrityError``.
    """
    normalized = str(kind or "").strip().lower()
    if normalized not in PAYMENT_KINDS:
        raise ValueError("kind счёта должен быть base или ai")
    external = str(external_id or "").strip()
    if not external:
        raise ValueError("external_id счёта не может быть пустым")
    cursor = conn.execute(
        """
        INSERT INTO invoices (user_id, kind, provider, external_id, amount_rub, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            normalized,
            str(provider or "yookassa").strip().lower() or "yookassa",
            external,
            float(amount_rub or 0),
            str(payload or ""),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_invoice_by_external(conn: sqlite3.Connection, external_id: str) -> dict | None:
    """Счёт по ``external_id`` провайдера (или ``None``)."""
    external = str(external_id or "").strip()
    if not external:
        return None
    return _row(
        conn.execute("SELECT * FROM invoices WHERE external_id = ?", (external,)).fetchone()
    )


def update_invoice_external(conn: sqlite3.Connection, row_id: int, external_id: str) -> None:
    """Меняет ``external_id`` счёта (Robokassa: tmp-uuid → InvId = id строки)."""
    conn.execute(
        "UPDATE invoices SET external_id = ? WHERE id = ?",
        (str(external_id), int(row_id)),
    )
    conn.commit()


def mark_invoice(conn: sqlite3.Connection, external_id: str, status: str) -> None:
    """Ставит статус счёта: pending / succeeded / canceled (чужой не трогает)."""
    normalized = str(status or "").strip().lower()
    if normalized not in INVOICE_STATUSES:
        raise ValueError("status счёта должен быть pending, succeeded или canceled")
    conn.execute(
        "UPDATE invoices SET status = ? WHERE external_id = ?",
        (normalized, str(external_id or "").strip()),
    )
    conn.commit()


def find_pending_invoice(
    conn: sqlite3.Connection, user_id: int, kind: str
) -> dict | None:
    """Последний неоплаченный счёт пользователя по виду (любой провайдер)."""
    return _row(
        conn.execute(
            """
            SELECT * FROM invoices
            WHERE user_id = ? AND kind = ? AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(user_id), str(kind or "").strip().lower()),
        ).fetchone()
    )


# --- план дня (day_plans) -------------------------------------------------------

def get_day_plan(conn: sqlite3.Connection, user_id: int, item_id: int) -> dict | None:
    """Блок плана дня по id с проверкой владельца."""
    return _row(
        conn.execute(
            "SELECT * FROM day_plans WHERE id = ? AND user_id = ?",
            (int(item_id), int(user_id)),
        ).fetchone()
    )


def list_day_plans(conn: sqlite3.Connection, user_id: int, date: str) -> list[dict]:
    """Блоки плана на дату по возрастанию времени."""
    return _rows(
        conn.execute(
            "SELECT * FROM day_plans WHERE user_id = ? AND date = ? ORDER BY time, id",
            (int(user_id), str(date)),
        )
    )


def day_plans_map(conn: sqlite3.Connection, user_id: int, date: str) -> dict[int, dict]:
    """{id: блок} для быстрых проверок внутри одного запроса."""
    return {int(row["id"]): row for row in list_day_plans(conn, user_id, date)}


def add_day_plan(
    conn: sqlite3.Connection,
    user_id: int,
    date: str,
    time: str,
    title: str,
    kind: str = "other",
    duration_min: int = 60,
    note: str = "",
    done: int | bool = 0,
) -> dict:
    cursor = conn.execute(
        """
        INSERT INTO day_plans (user_id, date, time, title, kind, duration_min, note, done)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            str(date),
            str(time),
            str(title),
            str(kind),
            int(duration_min),
            str(note or ""),
            _as_flag(done),
        ),
    )
    conn.commit()
    return get_day_plan(conn, user_id, int(cursor.lastrowid)) or {}


def update_day_plan(
    conn: sqlite3.Connection,
    user_id: int,
    item_id: int,
    data: dict,
) -> dict | None:
    """Частичное обновление блока; None — блок не найден или чужой."""
    current = get_day_plan(conn, user_id, item_id)
    if current is None:
        return None
    values = dict(current)
    for field in DAY_PLAN_FIELDS:
        if field in data and data[field] is not None:
            values[field] = _as_flag(data[field]) if field == "done" else data[field]
    conn.execute(
        """
        UPDATE day_plans
        SET date = ?, time = ?, title = ?, kind = ?,
            duration_min = ?, note = ?, done = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            str(values["date"]),
            str(values["time"]),
            str(values["title"]),
            str(values["kind"]),
            int(values["duration_min"]),
            str(values["note"] or ""),
            _as_flag(values["done"]),
            int(item_id),
            int(user_id),
        ),
    )
    conn.commit()
    return get_day_plan(conn, user_id, item_id)


def set_day_done(
    conn: sqlite3.Connection,
    user_id: int,
    item_id: int,
    done: int | bool = 1,
) -> dict | None:
    """Отмечает блок выполненным/невыполненным; None — не найден или чужой."""
    if get_day_plan(conn, user_id, item_id) is None:
        return None
    conn.execute(
        "UPDATE day_plans SET done = ? WHERE id = ? AND user_id = ?",
        (_as_flag(done), int(item_id), int(user_id)),
    )
    conn.commit()
    return get_day_plan(conn, user_id, item_id)


def delete_day_plan(conn: sqlite3.Connection, user_id: int, item_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM day_plans WHERE id = ? AND user_id = ?",
        (int(item_id), int(user_id)),
    )
    conn.commit()
    return cursor.rowcount > 0
