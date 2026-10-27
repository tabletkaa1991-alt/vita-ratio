"""Telegram-бот Vita Ratio (aiogram 3.x): команды и фоновые напоминания.

Запуск: ``python -m vita_ratio.bot`` (см. ``scripts/start-bot.ps1``).
В режиме ``all`` бот стартует из ``vita_ratio.main``: ``run_bot(settings, conn)``.

Бот работает напрямую с SQLite (``db.connect``) и ``calc.py``; он не зависит от
REST-слоя (``api``/``store``/``webapp``) и может запускаться отдельно.

Тексты — HTML (parse_mode), данные из БД экранируются.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from . import calc, db
from .config import Settings
from .config import settings as load_settings

log = logging.getLogger("vita_ratio.bot")

DEFAULT_TIMEZONE = "Europe/Moscow"

# --- напоминания --------------------------------------------------------------
REMINDER_TICK_SECONDS = 30.0     # период фонового цикла напоминаний
MEAL_REMIND_BEFORE_MIN = 10      # приём пищи: за 10 минут до слота
SLEEP_REMIND_BEFORE_MIN = 30     # сон: за 30 минут до отбоя
MORNING_WINDOW_MIN = 60          # утренняя сводка: в течение часа после подъёма

KIND_MORNING = "morning"
KIND_SLEEP = "sleep"
MEAL_KIND_PREFIX = "meal_"

MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

NO_PROFILE_TEXT = (
    "🌱 <b>Профиль ещё не заполнен.</b>\n\n"
    "Открой мини-приложение Vita Ratio и пройди онбординг: пол, возраст, рост, "
    "вес и активность. После этого я посчитаю цели по калориям, белку, жирам, "
    "углеводам и воде, план приёмов пищи и подсказки по сну.\n\n"
    "Кнопка приложения — в команде /app."
)

HELP_TITLE = "🤖 <b>Vita Ratio — что я умею</b>"
HELP_BODY = """<b>Команды</b>
/start — приветствие и кнопка приложения
/app — открыть мини-приложение
/today — сводка за сегодня: калории, белок, сон, ближайшее занятие
/plan — план приёмов пищи на сегодня
/classes — ближайшие 5 занятий из расписания
/sleep — последняя запись сна и окно питания
/targets — цели по КБЖУ и воде
/help — эта справка

Напоминания (приёмы пищи, сон, утренняя сводка) приходят, пока в профиле включён тумблер «Напоминания». Включить и выключить можно в мини-приложении."""


def _token_file() -> Path:
    """Путь к файлу с токеном, который читает scripts/sync-token.ps1."""
    return Path.home() / "secrets" / "vita ratio.txt"


# --- мелкие чистые помощники ---------------------------------------------------

def _esc(value: Any) -> str:
    """Экранирует текст для HTML-разметки Telegram."""
    return html.escape("" if value is None else str(value), quote=False)


_MISSING = object()


def _dget(row: Any, key: str, default: Any = None) -> Any:
    """Достаёт поле из dict / sqlite3.Row / dataclass-объекта; None -> default."""
    if row is None:
        return default
    if isinstance(row, dict):
        value = row.get(key, default)
    elif isinstance(row, sqlite3.Row):
        try:
            value = row[key]
        except (IndexError, KeyError):
            return default
    else:
        value = getattr(row, key, default)
    return default if value is None else value


def _tval(targets: Any, key: str, default: int = 0) -> int:
    """Целое значение цели из calc.Targets / dict; мусор -> default."""
    value = _dget(targets, key, default)
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _kind_label(kind: Any) -> str:
    text = str(kind or "other")
    return calc.KIND_LABELS.get(text, text)


def _parse_short_date(value: Any):
    try:
        return calc.parse_date(value)
    except (TypeError, ValueError):
        return None


def _short_date(value: Any) -> str:
    """'2026-10-26' -> 'Пн 26.10' (пустая строка на мусоре)."""
    parsed = _parse_short_date(value)
    if parsed is None:
        return ""
    return f"{calc.WEEKDAYS_SHORT_RU[parsed.weekday()]} {parsed.day:02d}.{parsed.month:02d}"


def _ru_date(value: Any) -> str:
    """'2026-10-26' -> 'Понедельник, 26 октября'."""
    parsed = _parse_short_date(value)
    if parsed is None:
        return _esc(value)
    return f"{calc.WEEKDAYS_RU[parsed.weekday()]}, {parsed.day} {MONTHS_GEN[parsed.month - 1]}"


def _human_delta(minutes: int) -> str:
    """Сколько осталось до события по-русски."""
    if minutes <= 0:
        return "уже идёт"
    if minutes < 60:
        return f"через {minutes} мин"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"через {hours} ч {rest:02d} мин" if rest else f"через {hours} ч"
    days, rest_hours = divmod(hours, 24)
    return f"через {days} дн {rest_hours} ч" if rest_hours else f"через {days} дн"


def _profile_tz(profile: Any, default: str = DEFAULT_TIMEZONE) -> str:
    tz = str(_dget(profile, "timezone", "") or "").strip()
    if tz:
        return tz
    return (default or "").strip() or DEFAULT_TIMEZONE


def targets_for_profile(profile: Any) -> calc.Targets | None:
    """Пересчитывает цели из строки профиля; None, если профиля нет."""
    if not profile:
        return None
    try:
        return calc.targets(
            _dget(profile, "sex", "male"),
            _dget(profile, "age", 25),
            _dget(profile, "height_cm", 175),
            _dget(profile, "weight_kg", 70),
            _dget(profile, "activity", "moderate"),
            _dget(profile, "goal_rate", 0.35),
            _dget(profile, "protein_per_kg", 2.0),
        )
    except (TypeError, ValueError, ZeroDivisionError):
        log.warning("Не удалось пересчитать цели из профиля: %r", profile)
        return None


def _logged_kinds(last_log: Any) -> set[str]:
    """Нормализует список уже отправленных kind (строки, пары, dict, Row)."""
    kinds: set[str] = set()
    if not last_log:
        return kinds
    for item in last_log:
        kind: Any = ""
        if isinstance(item, str):
            kind = item
        elif isinstance(item, (tuple, list)):
            kind = item[-1] if item else ""
        elif isinstance(item, dict):
            kind = item.get("kind", "")
        elif isinstance(item, sqlite3.Row):
            try:
                kind = item["kind"]
            except (IndexError, KeyError):
                kind = ""
        else:
            kind = getattr(item, "kind", "")
        if isinstance(kind, str) and kind:
            kinds.add(kind)
    return kinds


# --- клавиатура ----------------------------------------------------------------

def open_app_keyboard(app_url: str) -> InlineKeyboardMarkup:
    """Кнопка «Открыть Vita Ratio».

    Telegram открывает Mini App только по HTTPS-адресу. Пока APP_URL не публичный
    HTTPS (локальная разработка), показываем обычную ссылку — иначе Telegram
    отклонит сообщение с web_app-кнопкой.
    """
    url = (str(app_url or "").strip() or "http://127.0.0.1:8080").rstrip("/")
    if url.lower().startswith("https://"):
        button = InlineKeyboardButton(text="Открыть Vita Ratio", web_app=WebAppInfo(url=url))
    else:
        log.debug("APP_URL=%s не HTTPS: используем обычную ссылку вместо web_app", url)
        button = InlineKeyboardButton(text="Открыть Vita Ratio", url=url)
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


# --- форматирование (чистые функции, используются тестами) ---------------------

def _sleep_line(sleep_row: Any) -> str:
    if sleep_row is None:
        return "😴 Сон: пока не записан — отметь его в приложении."
    bed = _esc(_dget(sleep_row, "bed_time", ""))
    wake = _esc(_dget(sleep_row, "wake_time", ""))
    duration = _dget(sleep_row, "duration_h", None)
    quality = _dget(sleep_row, "quality", None)
    if duration is None:
        return f"😴 Сон: {bed}–{wake}"
    try:
        line = f"😴 Сон: <b>{float(duration):.1f} ч</b>"
    except (TypeError, ValueError):
        return f"😴 Сон: {bed}–{wake}"
    if quality:
        try:
            line += f" · качество {int(quality)}/5"
        except (TypeError, ValueError):
            pass
    return line


def format_today(profile_row: Any, targets: Any, totals: Any, sleep_row: Any, next_class: Any) -> str:
    """Сводка /today: калории/БЖУ vs цель, сон, ближайшее занятие."""
    if profile_row is None:
        return NO_PROFILE_TEXT

    kcal = _tval(totals, "kcal")
    protein = _tval(totals, "protein")
    fat = _tval(totals, "fat")
    carbs = _tval(totals, "carbs")

    lines = ["🍽 <b>Сводка за сегодня</b>", ""]
    if targets is not None:
        goal_kcal = _tval(targets, "kcal")
        left = max(goal_kcal - kcal, 0)
        lines.append(f"🔥 Калории: <b>{kcal} / {goal_kcal} ккал</b> · осталось {left}")
        lines.append(f"🥩 Белок: {protein} / {_tval(targets, 'protein')} г")
        lines.append(f"🥑 Жиры: {fat} / {_tval(targets, 'fat')} г")
        lines.append(f"🍚 Углеводы: {carbs} / {_tval(targets, 'carbs')} г")
    else:
        lines.append(f"🔥 Калории: <b>{kcal} ккал</b>")
        lines.append(f"🥩 Белок: {protein} г · 🥑 Жиры: {fat} г · 🍚 Углеводы: {carbs} г")
    meals_count = _tval(totals, "meals_count")
    if meals_count:
        lines.append(f"🍴 Приёмов пищи: {meals_count}")

    lines.extend(["", _sleep_line(sleep_row), ""])
    if next_class is None:
        lines.append("📅 Занятий в расписании нет — добавь их в разделе «Расписание».")
    else:
        title = _esc(_dget(next_class, "title", "Занятие"))
        kind = _esc(_kind_label(_dget(next_class, "kind", "other")))
        start = _esc(_dget(next_class, "start_time", ""))
        when = _short_date(_dget(next_class, "date", ""))
        where = f"{when} в {start}".strip() if start else when
        starts_in = _dget(next_class, "starts_in_min", _MISSING)
        suffix = ""
        if starts_in is not _MISSING and starts_in is not None:
            try:
                suffix = f" · {_human_delta(int(starts_in))}"
            except (TypeError, ValueError):
                suffix = ""
        lines.append(f"📅 Ближайшее: <b>{title}</b> — {where} ({kind}){suffix}")
    return "\n".join(lines)


def format_plan(slots: Any, targets: Any) -> str:
    """План приёмов пищи: время, название, калории."""
    if not slots:
        return (
            "🍽 План питания пока пуст.\n"
            "Заполни профиль в мини-приложении — и я рассчитаю приёмы пищи под окно сна и тренировки."
        )
    lines = ["🍽 <b>План питания на сегодня</b>", ""]
    for slot in slots:
        time_text = _esc(_dget(slot, "time", ""))
        title = _esc(_dget(slot, "title", "Приём пищи"))
        kcal = _dget(slot, "kcal", None)
        kcal_text = ""
        try:
            if kcal:
                kcal_text = f" · {int(round(float(kcal)))} ккал"
        except (TypeError, ValueError):
            kcal_text = ""
        lines.append(f"<b>{time_text}</b> — {title}{kcal_text}")
    goal_kcal = _tval(targets, "kcal")
    if goal_kcal:
        lines.extend(["", f"Итого на день: <b>{goal_kcal} ккал</b>"])
    lines.extend(["", "Отмечай съеденное в приложении — сводка /today обновится."])
    return "\n".join(lines)


def format_classes(occurrences: Any) -> str:
    """Ближайшие занятия из calc.next_occurrences."""
    if not occurrences:
        return "📅 Занятий пока нет — добавь их в разделе «Расписание» мини-приложения."
    lines = ["📅 <b>Ближайшие занятия</b>", ""]
    for index, item in enumerate(occurrences, start=1):
        when = _short_date(_dget(item, "date", ""))
        start = _esc(_dget(item, "start_time", ""))
        title = _esc(_dget(item, "title", "Занятие"))
        meta = [_esc(_kind_label(_dget(item, "kind", "other")))]
        duration = _tval(item, "duration_min")
        if duration:
            meta.append(f"{duration} мин")
        place = _esc(_dget(item, "place", ""))
        if place:
            meta.append(f"📍 {place}")
        lines.append(f"<b>{index}.</b> {when} в {start} — <b>{title}</b>")
        lines.append("    " + " · ".join(meta))
    lines.extend(["", "Отметить «Пришёл/Пропустил» можно в мини-приложении."])
    return "\n".join(lines)


def format_targets(targets: Any) -> str:
    """Цели по КБЖУ и воде."""
    if targets is None:
        return NO_PROFILE_TEXT
    water = _tval(targets, "water_ml")
    lines = [
        "🎯 <b>Цели на день</b>",
        "",
        f"🔥 Калории: <b>{_tval(targets, 'kcal')} ккал</b>",
        f"🥩 Белок: <b>{_tval(targets, 'protein')} г</b>",
        f"🥑 Жиры: {_tval(targets, 'fat')} г",
        f"🍚 Углеводы: {_tval(targets, 'carbs')} г",
        f"💧 Вода: {water} мл" + (f" (≈{water / 1000:.1f} л)" if water else ""),
    ]
    bmr = _tval(targets, "bmr")
    tdee = _tval(targets, "tdee")
    surplus = _tval(targets, "surplus_kcal")
    if bmr or tdee:
        lines.extend(["", f"База (BMR): {bmr} ккал · Расход (TDEE): {tdee} ккал"])
        if surplus:
            lines.append(f"Профицит на набор: +{surplus} ккал")
    lines.extend(["", "Пересчитать цели можно в профиле мини-приложения."])
    return "\n".join(lines)


def format_sleep(profile_row: Any, sleep_row: Any) -> str:
    """Последняя запись сна + окно сна и питания."""
    if profile_row is None:
        return NO_PROFILE_TEXT
    bed = str(_dget(profile_row, "sleep_bed", "23:00") or "23:00")
    wake = str(_dget(profile_row, "sleep_wake", "07:00") or "07:00")
    try:
        window = calc.sleep_window(bed, wake)
        duration_note = f"{window['duration_h']} ч"
        eat_start = window["eating_window"]["start"]
        eat_end = window["eating_window"]["end"]
    except (TypeError, ValueError):
        duration_note = "—"
        eat_start = eat_end = "—"

    lines = ["😴 <b>Сон и окно питания</b>", ""]
    if sleep_row is None:
        lines.append("Записей сна пока нет — отметь сон в приложении.")
    else:
        lines.append(f"Последняя запись: <b>{_ru_date(_dget(sleep_row, 'date', ''))}</b>")
        bed_time = _esc(_dget(sleep_row, "bed_time", ""))
        wake_time = _esc(_dget(sleep_row, "wake_time", ""))
        duration = _dget(sleep_row, "duration_h", None)
        try:
            duration_text = f"<b>{float(duration):.1f} ч</b>"
        except (TypeError, ValueError):
            duration_text = "—"
        lines.append(f"Отбой {bed_time} → подъём {wake_time}: {duration_text}")
        quality = _dget(sleep_row, "quality", None)
        if quality:
            try:
                lines.append(f"Качество: {int(quality)}/5")
            except (TypeError, ValueError):
                pass
    lines.extend([
        "",
        f"🌙 Окно сна: <b>{_esc(bed)}–{_esc(wake)}</b> ({duration_note})",
        f"🍽 Окно питания: <b>{_esc(eat_start)}–{_esc(eat_end)}</b>",
        "Последний приём — минимум за 2 часа до отбоя.",
    ])
    return "\n".join(lines)


# --- напоминания: чистый выбор на тик -----------------------------------------

def due_reminders(now: datetime, profile: Any, plan_slots: Any, last_log: Any) -> list[tuple[str, str]]:
    """Возвращает [(kind, text)] напоминаний, которые пора отправить в этот тик.

    :param now: локальное время пользователя (``calc.local_now``)
    :param profile: строка/словарь профиля (нужны ``reminders``, ``sleep_bed``,
        ``sleep_wake`` и параметры для расчёта целей)
    :param plan_slots: результат ``calc.meal_plan`` на сегодня
    :param last_log: уже отправленные сегодня kind (set/list из ``reminder_log``)
    """
    result: list[tuple[str, str]] = []
    if not profile:
        return result
    try:
        reminders_on = int(_dget(profile, "reminders", 0) or 0)
    except (TypeError, ValueError):
        reminders_on = 0
    if reminders_on != 1 and reminders_on is not True:
        return result

    logged = _logged_kinds(last_log)
    now_min = now.hour * 60 + now.minute
    targets = targets_for_profile(profile)

    def add(kind: str, text: str) -> None:
        if kind in logged:
            return
        logged.add(kind)
        result.append((kind, text))

    # 1. Приёмы пищи: за 10 минут до слота.
    for slot in plan_slots or []:
        time_text = str(_dget(slot, "time", "") or "").strip()
        try:
            slot_min = calc.time_to_minutes(time_text)
        except (TypeError, ValueError):
            continue
        delta = (slot_min - now_min) % (24 * 60)
        if not (0 < delta <= MEAL_REMIND_BEFORE_MIN):
            continue
        tag = str(_dget(slot, "tag", "") or "").strip() or "meal"
        kind = f"{MEAL_KIND_PREFIX}{tag}"
        title = _esc(_dget(slot, "title", "Приём пищи"))
        kcal = _dget(slot, "kcal", None)
        kcal_text = ""
        try:
            if kcal:
                kcal_text = f" (~{int(round(float(kcal)))} ккал)"
        except (TypeError, ValueError):
            kcal_text = ""
        add(
            kind,
            f"🍽 Через {MEAL_REMIND_BEFORE_MIN} мин — <b>{title}</b>{kcal_text}. "
            "Пора поесть, не пропускай приём пищи.",
        )

    # 2. Сон: за 30 минут до отбоя.
    try:
        bed_min = calc.time_to_minutes(str(_dget(profile, "sleep_bed", "") or ""))
    except (TypeError, ValueError):
        bed_min = None
    if bed_min is not None:
        delta = (bed_min - now_min) % (24 * 60)
        if 0 < delta <= SLEEP_REMIND_BEFORE_MIN:
            bed_text = _esc(_dget(profile, "sleep_bed", ""))
            add(
                KIND_SLEEP,
                f"🌙 Через {SLEEP_REMIND_BEFORE_MIN} мин — отбой в <b>{bed_text}</b>. "
                "Экраны в сторону, последний приём пищи уже позади.",
            )

    # 3. Утренняя сводка: в течение часа после подъёма.
    try:
        wake_min = calc.time_to_minutes(str(_dget(profile, "sleep_wake", "") or ""))
    except (TypeError, ValueError):
        wake_min = None
    if wake_min is not None:
        since_wake = (now_min - wake_min) % (24 * 60)
        if 0 <= since_wake <= MORNING_WINDOW_MIN:
            goal_kcal = _tval(targets, "kcal")
            goal_protein = _tval(targets, "protein")
            water = _tval(targets, "water_ml")
            if goal_kcal:
                add(
                    KIND_MORNING,
                    f"☀️ Доброе утро! План на день: <b>{goal_kcal} ккал</b>, "
                    f"белок {goal_protein} г, вода {water} мл. Не забудь завтрак и запись веса.",
                )
            else:
                add(KIND_MORNING, "☀️ Доброе утро! Заполни профиль в приложении, и я посчитаю цели на день.")
    return result


# --- SQL-хелперы (бот читает БД напрямую) --------------------------------------

def get_profile(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (int(user_id),)).fetchone()
    return db.row_to_dict(row)


def meal_totals(conn: sqlite3.Connection, user_id: int, day: str) -> dict:
    row = conn.execute(
        "SELECT COALESCE(SUM(kcal), 0) AS kcal, COALESCE(SUM(protein), 0) AS protein, "
        "COALESCE(SUM(fat), 0) AS fat, COALESCE(SUM(carbs), 0) AS carbs, "
        "COUNT(*) AS meals_count "
        "FROM meals WHERE user_id = ? AND date = ?",
        (int(user_id), day),
    ).fetchone()
    return db.row_to_dict(row) or {"kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "meals_count": 0}


def sleep_for_date(conn: sqlite3.Connection, user_id: int, day: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM sleep_logs WHERE user_id = ? AND date = ?", (int(user_id), day)
    ).fetchone()
    return db.row_to_dict(row)


def sleep_latest(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM sleep_logs WHERE user_id = ? ORDER BY date DESC LIMIT 1", (int(user_id),)
    ).fetchone()
    return db.row_to_dict(row)


def classes_for_date(conn: sqlite3.Connection, user_id: int, day: str) -> list[dict]:
    """Активные занятия пользователя на дату (по weekday)."""
    try:
        weekday = calc.parse_date(day).weekday()
    except (TypeError, ValueError):
        return []
    rows = conn.execute(
        "SELECT * FROM classes WHERE user_id = ? AND active = 1 AND weekday = ?",
        (int(user_id), weekday),
    ).fetchall()
    return db.rows_to_dicts(rows)


def next_class_for(conn: sqlite3.Connection, user_id: int, now: datetime) -> dict | None:
    rows = conn.execute(
        "SELECT * FROM classes WHERE user_id = ? AND active = 1", (int(user_id),)
    ).fetchall()
    upcoming = calc.next_occurrences(db.rows_to_dicts(rows), now, limit=1)
    return upcoming[0] if upcoming else None


def plan_slots_for_day(
    conn: sqlite3.Connection,
    user_id: int,
    profile: dict,
    targets: calc.Targets | None,
    day: str,
) -> list[dict]:
    bed = str(_dget(profile, "sleep_bed", "23:00") or "23:00")
    wake = str(_dget(profile, "sleep_wake", "07:00") or "07:00")
    goal_kcal = targets.kcal if targets is not None else None
    try:
        return calc.meal_plan(bed, wake, classes_for_date(conn, user_id, day), goal_kcal)
    except (TypeError, ValueError):
        log.warning("Не удалось построить план питания для %s (bed=%r, wake=%r)", user_id, bed, wake)
        return []


def sent_reminders(conn: sqlite3.Connection, user_id: int, day: str) -> set[str]:
    rows = conn.execute(
        "SELECT kind FROM reminder_log WHERE user_id = ? AND date = ?", (int(user_id), day)
    ).fetchall()
    return {str(row["kind"]) for row in rows}


def mark_reminder_sent(conn: sqlite3.Connection, user_id: int, day: str, kind: str) -> None:
    try:
        conn.execute(
            "INSERT OR IGNORE INTO reminder_log (user_id, date, kind) VALUES (?, ?, ?)",
            (int(user_id), day, kind),
        )
        conn.commit()
    except sqlite3.Error:
        log.exception("Не удалось записать reminder_log для user_id=%s kind=%s", user_id, kind)


# --- сборка текстов команд -----------------------------------------------------

def build_today(conn: sqlite3.Connection, user_id: int, default_tz: str = DEFAULT_TIMEZONE) -> str:
    profile = get_profile(conn, user_id)
    if profile is None:
        return format_today(None, None, None, None, None)
    now = calc.local_now(_profile_tz(profile, default_tz))
    day = now.date().isoformat()
    targets = targets_for_profile(profile)
    totals = meal_totals(conn, user_id, day)
    sleep_row = sleep_for_date(conn, user_id, day)
    next_class = next_class_for(conn, user_id, now)
    return format_today(profile, targets, totals, sleep_row, next_class)


def build_plan(conn: sqlite3.Connection, user_id: int, default_tz: str = DEFAULT_TIMEZONE) -> str:
    profile = get_profile(conn, user_id)
    if profile is None:
        return format_plan(None, None)
    now = calc.local_now(_profile_tz(profile, default_tz))
    targets = targets_for_profile(profile)
    slots = plan_slots_for_day(conn, user_id, profile, targets, now.date().isoformat())
    return format_plan(slots, targets)


def build_classes(conn: sqlite3.Connection, user_id: int, default_tz: str = DEFAULT_TIMEZONE) -> str:
    profile = get_profile(conn, user_id)
    if profile is None:
        return "📅 Занятий пока нет. Сначала заполни профиль в мини-приложении — команда /app."
    now = calc.local_now(_profile_tz(profile, default_tz))
    rows = conn.execute(
        "SELECT * FROM classes WHERE user_id = ? AND active = 1", (int(user_id),)
    ).fetchall()
    occurrences = calc.next_occurrences(db.rows_to_dicts(rows), now, limit=5)
    return format_classes(occurrences)


def build_sleep(conn: sqlite3.Connection, user_id: int) -> str:
    profile = get_profile(conn, user_id)
    if profile is None:
        return format_sleep(None, None)
    return format_sleep(profile, sleep_latest(conn, user_id))


def build_targets(conn: sqlite3.Connection, user_id: int) -> str:
    profile = get_profile(conn, user_id)
    return format_targets(targets_for_profile(profile))


# --- хендлеры ------------------------------------------------------------------

def build_router(settings_obj: Settings, conn: sqlite3.Connection) -> Router:
    """Router со всеми командами бота (данные читаются из переданного conn)."""
    router = Router(name="vita-ratio")
    default_tz = settings_obj.timezone or DEFAULT_TIMEZONE

    def user_id_of(message: Message) -> int:
        if message.from_user is not None:
            return int(message.from_user.id)
        return int(message.chat.id)

    async def answer(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        first_name = "друг"
        if message.from_user is not None and message.from_user.first_name:
            first_name = _esc(message.from_user.first_name)
        lines = [
            f"👋 <b>Привет, {first_name}!</b>",
            "",
            "Vita Ratio — мини-приложение для набора массы: дневник еды по КБЖУ, сон, "
            "расписание зала и учёбы, цели и прогресс.",
            "Открывай приложение кнопкой ниже — я буду напоминать про приёмы пищи, сон и присылать утреннюю сводку.",
        ]
        profile = None
        try:
            profile = get_profile(conn, user_id_of(message))
        except sqlite3.Error:
            log.exception("Не удалось прочитать профиль для /start (user_id=%s)", user_id_of(message))
        if profile is None:
            lines.extend([
                "",
                "🌱 Профиля пока нет: открой приложение и пройди онбординг (пол, возраст, рост, вес, "
                "активность, сон). После этого /today покажет твои цифры.",
            ])
        else:
            lines.extend(["", "Что дальше: /today · /plan · /classes · /sleep · /targets. Полный список — /help."])
        await answer(message, "\n".join(lines), open_app_keyboard(settings_obj.app_url))

    @router.message(Command("app"))
    async def cmd_app(message: Message) -> None:
        await answer(
            message,
            "📲 <b>Vita Ratio</b> — открой мини-приложение кнопкой ниже.\n"
            "Внутри: дневник еды, сон, расписание и прогресс.",
            open_app_keyboard(settings_obj.app_url),
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await answer(message, HELP_TITLE + "\n\n" + HELP_BODY)

    @router.message(Command("today"))
    async def cmd_today(message: Message) -> None:
        try:
            text = build_today(conn, user_id_of(message), default_tz)
        except sqlite3.Error:
            log.exception("Ошибка /today для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить данные. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("plan"))
    async def cmd_plan(message: Message) -> None:
        try:
            text = build_plan(conn, user_id_of(message), default_tz)
        except sqlite3.Error:
            log.exception("Ошибка /plan для user_id=%s", user_id_of(message))
            text = "😔 Не получилось построить план. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("classes"))
    async def cmd_classes(message: Message) -> None:
        try:
            text = build_classes(conn, user_id_of(message), default_tz)
        except sqlite3.Error:
            log.exception("Ошибка /classes для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить расписание. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("sleep"))
    async def cmd_sleep(message: Message) -> None:
        try:
            text = build_sleep(conn, user_id_of(message))
        except sqlite3.Error:
            log.exception("Ошибка /sleep для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить запись сна. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("targets"))
    async def cmd_targets(message: Message) -> None:
        try:
            text = build_targets(conn, user_id_of(message))
        except sqlite3.Error:
            log.exception("Ошибка /targets для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить цели. Попробуй ещё раз чуть позже."
        await answer(message, text)

    return router


# --- фоновые напоминания -------------------------------------------------------

async def _reminder_tick(
    conn: sqlite3.Connection,
    bot: Bot,
    settings_obj: Settings,
    blocked: set[int],
) -> None:
    """Один проход по профилям с включёнными напоминаниями."""
    rows = conn.execute("SELECT * FROM profiles WHERE reminders = 1 ORDER BY user_id").fetchall()
    for row in rows:
        profile = dict(row)
        user_id = int(profile.get("user_id") or 0)
        if not user_id or user_id in blocked:
            continue
        now = calc.local_now(_profile_tz(profile, settings_obj.timezone))
        day = now.date().isoformat()
        targets = targets_for_profile(profile)
        slots = plan_slots_for_day(conn, user_id, profile, targets, day)
        due = due_reminders(now, profile, slots, sent_reminders(conn, user_id, day))
        for kind, text in due:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except TelegramForbiddenError:
                blocked.add(user_id)
                log.warning(
                    "Пользователь %s заблокировал бота — напоминания приостановлены до перезапуска",
                    user_id,
                )
                break
            except TelegramRetryAfter as exc:
                log.warning(
                    "Telegram просит подождать %s с — напоминания для %s отложены",
                    getattr(exc, "retry_after", "?"),
                    user_id,
                )
                break
            except TelegramAPIError as exc:
                log.warning("Не удалось отправить напоминание %s пользователю %s: %s", kind, user_id, exc)
                break
            except Exception:  # noqa: BLE001 — напоминания не должны ронять бота
                log.exception("Неожиданная ошибка при отправке напоминания %s для %s", kind, user_id)
                break
            mark_reminder_sent(conn, user_id, day, kind)


async def _reminder_loop(settings_obj: Settings, bot: Bot) -> None:
    """Фоновый цикл напоминаний: своё соединение с БД, тик 30 секунд."""
    conn = db.connect(settings_obj.db_path)
    blocked: set[int] = set()
    try:
        db.init_db(conn)
        log.info("Напоминания запущены: тик %.0f с", REMINDER_TICK_SECONDS)
        while True:
            try:
                await _reminder_tick(conn, bot, settings_obj, blocked)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — цикл должен переживать сбои одного тика
                log.exception("Ошибка в цикле напоминаний")
            await asyncio.sleep(REMINDER_TICK_SECONDS)
    finally:
        conn.close()
        log.info("Цикл напоминаний остановлен")


async def _set_commands(bot: Bot) -> None:
    """Меню команд в Telegram (не критично: ошибки только логируем)."""
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Приветствие и кнопка приложения"),
            BotCommand(command="app", description="Открыть мини-приложение"),
            BotCommand(command="today", description="Сводка за сегодня"),
            BotCommand(command="plan", description="План питания на сегодня"),
            BotCommand(command="classes", description="Ближайшие занятия"),
            BotCommand(command="sleep", description="Сон и окно питания"),
            BotCommand(command="targets", description="Цели по КБЖУ и воде"),
            BotCommand(command="help", description="Список команд"),
        ])
    except TelegramAPIError as exc:
        log.warning("Не удалось обновить меню команд: %s", exc)


# --- точка входа ---------------------------------------------------------------

async def run_bot(settings_obj: Settings, conn: sqlite3.Connection | None = None) -> None:
    """Запускает бота: polling + фоновая задача напоминаний.

    Без ``BOT_TOKEN`` пишет понятную ошибку в лог и возвращается (не бросает).
    ``conn`` — общее соединение из ``main.py``; если не передано, бот откроет своё.
    """
    bot_token = (settings_obj.bot_token or "").strip()
    if not bot_token:
        log.error(
            "BOT_TOKEN не задан — бот не запущен. Положи токен в %s и выполни "
            "scripts/sync-token.ps1 (или впиши BOT_TOKEN в .env).",
            _token_file(),
        )
        return

    if not str(settings_obj.app_url).lower().startswith("https://"):
        log.warning(
            "APP_URL=%s не HTTPS: Telegram открывает Mini App только по HTTPS, "
            "поэтому кнопка будет обычной ссылкой. Для телефона нужен https-туннель (см. README).",
            settings_obj.app_url,
        )

    session: AiohttpSession | None = None
    if settings_obj.proxy_url:
        try:
            session = AiohttpSession(proxy=settings_obj.proxy_url)
        except (ImportError, RuntimeError) as exc:
            log.error(
                "PROXY_URL задан (%s), но aiogram не может включить прокси: %s. "
                "Нужен пакет aiohttp-socks (pip install aiohttp-socks); пока работаем без прокси.",
                settings_obj.proxy_url,
                exc,
            )
            session = None
        else:
            log.info("Запросы к api.telegram.org идут через прокси %s", settings_obj.proxy_url)

    bot = Bot(
        token=bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    own_conn = conn
    if own_conn is None:
        own_conn = db.connect(settings_obj.db_path)
        db.init_db(own_conn)

    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings_obj, own_conn))

    reminder_task = asyncio.create_task(
        _reminder_loop(settings_obj, bot), name="vita-ratio-reminders"
    )
    log.info("Бот Vita Ratio запущен (polling)")
    try:
        await _set_commands(bot)
        await dispatcher.start_polling(bot)
    except asyncio.CancelledError:
        log.info("Polling бота остановлен")
        raise
    finally:
        reminder_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminder_task
        with contextlib.suppress(Exception):
            await bot.session.close()
        if conn is None:
            with contextlib.suppress(Exception):
                own_conn.close()
        log.info("Бот Vita Ratio остановлен")


def main(argv: list[str] | None = None) -> int:
    """``python -m vita_ratio.bot`` — только бот."""
    del argv  # аргументов нет, оставлено для единообразия с main.py
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings_obj = load_settings()
    if not (settings_obj.bot_token or "").strip():
        log.error(
            "BOT_TOKEN не задан — бот не запущен. Файл: %s; затем scripts/sync-token.ps1 "
            "или BOT_TOKEN= в .env.",
            _token_file(),
        )
        return 2
    conn = db.connect(settings_obj.db_path)
    try:
        db.init_db(conn)
        asyncio.run(run_bot(settings_obj, conn))
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
