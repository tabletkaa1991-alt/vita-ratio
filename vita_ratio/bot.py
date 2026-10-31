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
from datetime import date as date_cls
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)

from . import access, ai, calc, db, reports, store
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
KIND_TRIAL_END = "trial_end"     # D-1: напоминание за день до конца бесплатного периода
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
/menu — меню: срок доступа, таймер периода и команды
/app — открыть мини-приложение
/today — сводка за сегодня: калории, белок, сон, ближайшее занятие
/plan — план приёмов пищи на сегодня
/classes — ближайшие 5 занятий из расписания
/sleep — последняя запись сна и окно питания
/targets — цели по КБЖУ и воде
/export — отчёт за день, неделю или месяц: PNG, DOCX или XLSX
/note — заметка с разбором ИИ (например: /note сегодня тяжело, мало спал)
/notes — последние заметки и ответы ИИ
/ask — спросить ИИ о чём угодно (учёба, код, тренировки; алиас /ai)
/subscription — подписка и оплата (250 ₽/мес, ИИ +100 ₽/мес)
/whoami — твой Telegram ID и username (нужно для бесплатного доступа)
/help — эта справка

<b>Владельцу бота</b>
/grant 123456789 — выдать бесплатный доступ по ID или /grant @username
/revoke 123456789 — снять бесплатный доступ
/free_list — кто в бесплатном доступе (БД и env)

Напоминания (приёмы пищи, сон, утренняя сводка) приходят, пока в профиле включён тумблер «Напоминания». Включить и выключить можно в мини-приложении."""

# --- подписка (CONTRACT §22–24) ------------------------------------------------
#: Текст гейта: команда недоступна без активной base-подписки.
PAYWALL_TEXT = (
    "🔒 <b>Подписка 250 ₽/мес нужна для доступа</b>\n\n"
    "Оформить или продлить можно командой /subscription — оплата в Telegram Stars."
)
#: Команды, которые работают всегда (вне платного гейта).
FREE_COMMANDS = frozenset({
    "/start", "/menu", "/app", "/help", "/subscription", "/whoami",
    "/grant", "/revoke", "/free_list", "/ask",
})
#: Команды, которым нужна активная base-подписка.
GATED_COMMANDS = frozenset({
    "/today", "/plan", "/classes", "/sleep", "/targets", "/note", "/notes", "/export",
})
#: Краткий список команд для /menu (полная справка — /help).
MENU_COMMANDS = (
    "/today — сводка за сегодня",
    "/plan — план питания",
    "/classes — ближайшие занятия",
    "/sleep — сон и окно питания",
    "/targets — цели по КБЖУ и воде",
    "/export — отчёт (PNG, DOCX, XLSX)",
    "/ask — спросить ИИ о чём угодно",
    "/subscription — подписка и оплата",
    "/whoami — мой Telegram ID",
    "/help — полная справка",
)


def _date_active(value: Any, today: str) -> bool:
    """Дата подписки действует по ``today`` включительно; мусор -> False."""
    if not value:
        return False
    try:
        return date_cls.fromisoformat(str(value)[:10]) >= date_cls.fromisoformat(str(today)[:10])
    except (TypeError, ValueError):
        return False


def subscription_active(profile: Any, today: str) -> bool:
    """Активна ли base-подписка профиля (``sub_until`` включительно)."""
    return _date_active(_dget(profile, "sub_until", None), today)


def effective_ai(profile: Any, today: str) -> bool:
    """Эффективный ИИ: флаг ai_enabled И оплаченный ai_until >= today."""
    if not profile:
        return False
    try:
        flag = int(_dget(profile, "ai_enabled", 0) or 0)
    except (TypeError, ValueError):
        flag = 0
    return flag == 1 and _date_active(_dget(profile, "ai_until", None), today)


def _is_free_message(
    settings_obj: Settings, message: Message, conn: sqlite3.Connection | None = None
) -> bool:
    """True, если отправителю включён бесплатный доступ (CONTRACT §29).

    ``conn`` передаётся, чтобы учитывать доступ, выданный из бота (/grant):
    он хранится в таблице ``free_access``.
    """
    from_user = getattr(message, "from_user", None)
    if from_user is None:
        return False
    return access.is_free(
        settings_obj,
        getattr(from_user, "id", None),
        getattr(from_user, "username", None),
        conn,
    )


# --- таймер бесплатного периода (v5) -------------------------------------------

def _day(value: Any) -> date_cls | None:
    """ISO-дата/date -> date; мусор -> None."""
    if isinstance(value, date_cls):
        return value
    if not value:
        return None
    try:
        return date_cls.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _dotted(value: Any, with_year: bool = False) -> str:
    """Дата для текста: ``2026-11-07`` -> ``07.11`` или ``07.11.2026``."""
    parsed = _day(value)
    if parsed is None:
        return ""
    if with_year:
        return f"{parsed.day:02d}.{parsed.month:02d}.{parsed.year}"
    return f"{parsed.day:02d}.{parsed.month:02d}"


def _username_for(conn: sqlite3.Connection | None, user_id: Any) -> str | None:
    """Username из ``users`` — чтобы бесплатный доступ по нику тоже учитывался."""
    if conn is None or user_id is None:
        return None
    try:
        row = conn.execute(
            "SELECT username FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
    except (sqlite3.Error, AttributeError, TypeError, ValueError):
        return None
    return str(row["username"]) if row is not None and row["username"] else None


def format_trial_timer(
    profile: Any,
    settings_obj: Settings,
    today: str | None = None,
    conn: sqlite3.Connection | None = None,
    username: str | None = None,
) -> str | None:
    """Живая строка таймера бесплатного периода; ``None`` — показывать нечего.

    * бесплатный доступ (``access.is_free`` по env/БД) -> ``None``: /menu
      покажет отдельный текст «бесплатно», таймер не нужен;
    * ``sub_until`` в будущем: 0 дней — «последний день», 1 день — «продлить»,
      2+ — «осталось N дн. (до DD.MM)»;
    * даты нет или она истекла -> ``None``.

    ``today`` — для детерминированных тестов; ``conn``/``username`` — чтобы
    учесть бесплатный доступ, выданный через /grant (таблица ``free_access``).
    """
    if not profile:
        return None
    user_id = _dget(profile, "user_id", None)
    if user_id is not None:
        if username is None:
            username = _username_for(conn, user_id)
        if access.is_free(settings_obj, user_id=user_id, username=username, conn=conn):
            return None
    until = _day(_dget(profile, "sub_until", None))
    if until is None:
        return None
    current = _day(today)
    if current is None:
        current = _day(
            calc.local_today(getattr(settings_obj, "timezone", None) or DEFAULT_TIMEZONE)
        )
    if current is None:
        return None
    delta = (until - current).days
    if delta < 0:
        return None
    short = _dotted(until)
    if delta == 0:
        return f"⏳ Бесплатный период: последний день (до {short})"
    if delta == 1:
        return "⏳ Бесплатный период: остался 1 день — продлить: /subscription"
    return f"⏳ Бесплатный период: осталось {delta} дн. (до {short})"


def trial_end_text(until: Any, settings_obj: Settings | None = None) -> str:
    """Текст напоминания D-1: бесплатный период заканчивается завтра."""
    try:
        base_price = int(getattr(settings_obj, "base_price_rub", 250) or 250)
    except (TypeError, ValueError):
        base_price = 250
    try:
        ai_price = int(getattr(settings_obj, "ai_price_rub", 100) or 100)
    except (TypeError, ValueError):
        ai_price = 100
    return (
        f"⏳ Бесплатный период Vita Ratio заканчивается завтра "
        f"(до {_dotted(until, with_year=True)}).\n"
        f"Остался 1 день. Продлить: /subscription — {base_price} ₽/мес, ИИ +{ai_price} ₽/мес."
    )


def trial_end_due(
    settings_obj: Settings,
    conn: sqlite3.Connection,
    profile: Any,
    today: str,
    free: bool = False,
) -> str | None:
    """Текст D-1-напоминания или ``None`` (free / не завтра / уже отправлено)."""
    if not profile or free:
        return None
    try:
        user_id = int(_dget(profile, "user_id", 0) or 0)
    except (TypeError, ValueError):
        return None
    if user_id <= 0:
        return None
    until = _day(_dget(profile, "sub_until", None))
    current = _day(today)
    if until is None or current is None:
        return None
    if (until - current).days != 1:
        return None
    try:
        if store.reminder_exists(conn, user_id, current.isoformat(), KIND_TRIAL_END):
            return None
    except sqlite3.Error:
        return None
    return trial_end_text(until, settings_obj)


# --- бесплатный доступ: команды владельца (/whoami, /grant, /revoke, /free_list) ---

#: Ответ на админ-команду от любого, кроме владельца.
ADMIN_ONLY_TEXT = "Команда доступна только владельцу бота."
#: Сколько строк максимум показывает /free_list.
FREE_LIST_LIMIT = 50


def _sender(message: Any) -> Any:
    """Отправитель сообщения (``message.from_user``) или ``None``."""
    return getattr(message, "from_user", None)


def _sender_id(message: Any) -> Any:
    """ID отправителя; для сообщений без from_user — id чата."""
    sender = _sender(message)
    if sender is not None:
        return getattr(sender, "id", None)
    return getattr(getattr(message, "chat", None), "id", None)


def _command_args(message: Any) -> str:
    """Аргумент команды: ``/grant 123`` -> ``"123"`` (пусто, если его нет)."""
    parts = str(getattr(message, "text", "") or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def is_admin(settings_obj: Settings, message: Any) -> bool:
    """True, если команду отправил владелец бота (``settings.admin_id``)."""
    admin_id = getattr(settings_obj, "admin_id", None)
    sender = _sender(message)
    if not admin_id or sender is None:
        return False
    try:
        return int(admin_id) == int(getattr(sender, "id", 0) or 0)
    except (TypeError, ValueError):
        return False


def format_whoami(message: Any) -> str:
    """Текст /whoami: Telegram ID и username отправителя (для whitelist)."""
    sender = _sender(message)
    user_id = _sender_id(message)
    username = str(getattr(sender, "username", "") or "").strip().lstrip("@")
    shown = f"@{_esc(username)}" if username else "— (не задан)"
    id_text = _esc(user_id) if user_id is not None else "—"
    return f"Твой Telegram ID: {id_text}, username: {shown}"


def command_grant(settings_obj: Settings, conn: sqlite3.Connection, message: Any) -> str:
    """Текст ответа на /grant <id|@username>; проверка владельца внутри."""
    if not is_admin(settings_obj, message):
        return ADMIN_ONLY_TEXT
    value = access.normalize(_command_args(message))
    if not value:
        return "Использование: /grant 123456789 или /grant @username"
    if access.add_free(conn, value):
        return f"✅ Бесплатный доступ выдан: {_esc(value)}"
    is_numeric = value.isdigit()
    already = access.is_free(
        settings_obj,
        int(value) if is_numeric else None,
        None if is_numeric else value,
        conn,
    )
    if already:
        return f"ℹ️ Бесплатный доступ уже есть: {_esc(value)}"
    return "😔 Не удалось сохранить бесплатный доступ. Попробуй позже."


def command_revoke(settings_obj: Settings, conn: sqlite3.Connection, message: Any) -> str:
    """Текст ответа на /revoke <id|@username>; проверка владельца внутри."""
    if not is_admin(settings_obj, message):
        return ADMIN_ONLY_TEXT
    value = access.normalize(_command_args(message))
    if not value:
        return "Использование: /revoke 123456789 или /revoke @username"
    if access.remove_free(conn, value):
        return f"🚫 Бесплатный доступ снят: {_esc(value)}"
    return f"🚫 Бесплатный доступ не найден: {_esc(value)}"


def format_free_list(settings_obj: Settings, rows: list[dict]) -> str:
    """Текст /free_list: значения из БД и env, до ``FREE_LIST_LIMIT`` строк.

    Всё, что пришло из БД/env, экранируется для HTML-разметки Telegram.
    """
    env_ids = access.free_ids(settings_obj)
    env_names = access.free_usernames(settings_obj)
    total = len(rows) + len(env_ids) + len(env_names)
    shown = 0
    lines = ["📋 <b>Бесплатный доступ</b>", "", "<b>Из бота (БД):</b>"]
    if rows:
        for row in rows:
            if shown >= FREE_LIST_LIMIT:
                break
            value = _esc(row.get("value", ""))
            created = str(row.get("created_at") or "")[:19]
            lines.append(
                f"• <code>{value}</code>" + (f" — {_esc(created)}" if created else "")
            )
            shown += 1
    else:
        lines.append("• пока никого")
    lines.extend(["", "<b>Из env (Render):</b>"])
    env_shown = 0
    for uid in env_ids:
        if shown >= FREE_LIST_LIMIT:
            break
        lines.append(f"• ID <code>{uid}</code>")
        shown += 1
        env_shown += 1
    for name in env_names:
        if shown >= FREE_LIST_LIMIT:
            break
        lines.append(f"• <code>@{_esc(name)}</code>")
        shown += 1
        env_shown += 1
    if not env_shown:
        lines.append("• пусто")
    if total > shown:
        lines.append("")
        lines.append(f"…и ещё {total - shown} (показаны первые {FREE_LIST_LIMIT})")
    return "\n".join(lines)


def command_free_list(settings_obj: Settings, conn: sqlite3.Connection, message: Any) -> str:
    """Текст ответа на /free_list; проверка владельца внутри."""
    if not is_admin(settings_obj, message):
        return ADMIN_ONLY_TEXT
    return format_free_list(settings_obj, access.list_free(conn))


def format_subscription(
    profile: Any,
    settings_obj: Settings,
    today: str,
    free: bool = False,
    timer: str | None = None,
) -> str:
    """Текст /subscription: статус base/ai, даты и цены (или «бесплатно»).

    ``timer`` — строка :func:`format_trial_timer` (живой таймер триала), если есть.
    """
    if free:
        return "\n".join([
            "🎁 Бесплатный доступ включён (бессрочно)",
            "",
            "Бот и мини-приложение Vita Ratio доступны без подписки.",
            "ИИ-разбор заметок и отчётов включён.",
        ])
    profile = profile or {}
    sub_until = _dget(profile, "sub_until", None)
    ai_until = _dget(profile, "ai_until", None)
    base_on = _date_active(sub_until, today)
    ai_on = _date_active(ai_until, today)

    def _fmt(value: Any) -> str:
        return str(value)[:10] if value else "—"

    base_line = (
        f"✅ активна до <b>{_fmt(sub_until)}</b>" if base_on
        else "❌ не активна"
    )
    ai_line = (
        f"✅ активен до <b>{_fmt(ai_until)}</b>" if ai_on
        else "❌ не подключён"
    )
    lines = [
        "💳 <b>Подписка Vita Ratio</b>",
        "",
        f"Бот и приложение: {base_line}",
        f"ИИ-разбор: {ai_line}",
        "",
        (
            f"Подписка — <b>{settings_obj.base_price_rub} ₽/мес</b> "
            f"({settings_obj.base_price_stars} Stars), "
            f"ИИ — <b>+{settings_obj.ai_price_rub} ₽/мес</b> "
            f"({settings_obj.ai_price_stars} Stars)."
        ),
        f"Оплата в Telegram Stars, период {settings_obj.sub_period_days} дней.",
        "Новым пользователям — пробный период "
        f"{settings_obj.trial_days} дней.",
    ]
    if not base_on:
        lines.append("")
        lines.append("ИИ-аддон доступен после оформления подписки.")
    if timer:
        lines.extend(["", timer])
    return "\n".join(lines)


def format_menu(
    profile: Any,
    settings_obj: Settings,
    today: str,
    timer: str | None = None,
    free: bool = False,
) -> str:
    """Текст /menu: срок доступа, живой таймер периода и краткий список команд.

    ``timer`` — результат :func:`format_trial_timer` (пересчитывается на каждый
    вызов /menu, поэтому счётчик в сообщении всегда актуальный).
    """
    lines = ["☰ <b>Меню Vita Ratio</b>", ""]
    if free:
        lines.append("🎁 Бесплатный доступ: бессрочно (подписка не нужна)")
    else:
        until = _dget(profile, "sub_until", None) if profile else None
        if _date_active(until, today):
            lines.append(
                f"💳 Подписка: активна до <b>{_dotted(until, with_year=True)}</b>"
            )
        else:
            lines.append("❌ Подписка не активна — оформить: /subscription")
    if timer:
        lines.append(timer)
    lines.extend(["", "<b>Команды</b>", *MENU_COMMANDS])
    if not profile:
        lines.extend([
            "",
            "🌱 Профиль ещё не заполнен — пройди онбординг в приложении: /app",
        ])
    return "\n".join(lines)



def _payment_until(payment: Any, current: Any, today: str, settings_obj: Settings) -> str:
    """Дата окончания после оплаты: ``subscription_expiration_date`` либо +период.

    Без даты от Telegram продлеваем от максимума из «today» и текущей даты —
    так оплата не «съедает» остаток и не продлевает уже истёкшую подписку назад.
    """
    expiration = getattr(payment, "subscription_expiration_date", None)
    try:
        if expiration:
            return date_cls.fromtimestamp(int(expiration)).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        log.warning("Некорректный subscription_expiration_date=%r — считаю по периоду", expiration)
    base = date_cls.fromisoformat(str(today)[:10])
    current_day = _parse_short_date(current)
    if current_day is not None and current_day > base:
        base = current_day
    period = max(int(getattr(settings_obj, "sub_period_days", 30) or 30), 1)
    return (base + timedelta(days=period)).isoformat()


def _payment_text(kind: str, until: str, duplicate: bool = False) -> str:
    """Текст подтверждения оплаты в чат (CONTRACT §24)."""
    if duplicate:
        return "✅ Платёж уже учтён — подписка не продлевается повторно."
    if kind == "ai":
        return f"✅ ИИ-разбор подключён до {until}"
    return f"✅ Подписка на Vita Ratio активна до {until}"


def apply_payment(
    settings_obj: Settings,
    conn: sqlite3.Connection,
    payment: Any,
    user_id: int | None = None,
) -> dict:
    """Обрабатывает ``successful_payment``: запись платежа + продление подписки.

    Идемпотентно по ``telegram_payment_charge_id``: повторная доставка того же
    платежа не продлевает подписку второй раз. Возвращает dict со статусом для
    ответа в чат: ``{"ok", "kind", "until", "duplicate", "user_id", "error", "text"}``.
    """
    charge_id = str(getattr(payment, "telegram_payment_charge_id", "") or "").strip()
    raw_payload = str(getattr(payment, "invoice_payload", "") or "").strip()
    kind, _, uid_text = raw_payload.partition(":")
    kind = kind.strip().lower()
    try:
        payload_uid = int(uid_text) if uid_text else 0
    except (TypeError, ValueError):
        payload_uid = 0
    uid = int(user_id or payload_uid or 0)
    error = ""
    if kind not in store.PAYMENT_KINDS or uid <= 0 or not charge_id:
        error = "bad_payload"
    profile = None
    if not error:
        store.upsert_user(conn, uid)
        profile = get_profile(conn, uid)
        if profile is None:
            error = "no_profile"
    if error:
        log.warning(
            "successful_payment: не обработан (%s): payload=%r charge=%r uid=%s",
            error, raw_payload, charge_id, uid,
        )
        return {
            "ok": False,
            "kind": kind,
            "until": None,
            "duplicate": False,
            "user_id": uid,
            "error": error,
            "text": "",
        }

    amount = int(getattr(payment, "total_amount", 0) or 0)
    currency = str(getattr(payment, "currency", "XTR") or "XTR")
    field = "ai_until" if kind == "ai" else "sub_until"
    current = _dget(profile, field, None)
    inserted = store.add_payment(conn, uid, kind, charge_id, amount, currency, raw_payload)
    if not inserted:
        log.info(
            "successful_payment: платёж %s уже был (user_id=%s kind=%s) — подписка не продлена",
            charge_id, uid, kind,
        )
        return {
            "ok": True,
            "kind": kind,
            "until": current,
            "duplicate": True,
            "user_id": uid,
            "error": "",
            "text": _payment_text(kind, str(current or ""), duplicate=True),
        }

    today = calc.local_today(settings_obj.timezone)
    until = _payment_until(payment, current, today, settings_obj)
    store.set_subscription(conn, uid, **{field: until})
    if kind == "ai":
        # Аддон оплачен -> включаем ИИ в профиле (CONTRACT §22).
        store.upsert_profile(conn, uid, {"ai_enabled": 1})
    text = _payment_text(kind, until)
    log.info(
        "successful_payment: user_id=%s kind=%s until=%s charge=%s amount=%s %s",
        uid, kind, until, charge_id, amount, currency,
    )
    return {
        "ok": True,
        "kind": kind,
        "until": until,
        "duplicate": False,
        "user_id": uid,
        "error": "",
        "text": text,
    }


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


def format_today(
    profile_row: Any,
    targets: Any,
    totals: Any,
    sleep_row: Any,
    next_class: Any,
    timer: str | None = None,
) -> str:
    """Сводка /today: калории/БЖУ vs цель, сон, ближайшее занятие (+ таймер)."""
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
    if timer:
        lines.extend(["", timer])
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

def build_today(
    conn: sqlite3.Connection,
    user_id: int,
    default_tz: str = DEFAULT_TIMEZONE,
    settings_obj: Settings | None = None,
    today: str | None = None,
    username: str | None = None,
) -> str:
    """Текст /today; с ``settings_obj`` добавляет живой таймер периода."""
    profile = get_profile(conn, user_id)
    if profile is None:
        return format_today(None, None, None, None, None)
    now = calc.local_now(_profile_tz(profile, default_tz))
    day = today or now.date().isoformat()
    targets = targets_for_profile(profile)
    totals = meal_totals(conn, user_id, day)
    sleep_row = sleep_for_date(conn, user_id, day)
    next_class = next_class_for(conn, user_id, now)
    timer = None
    if settings_obj is not None:
        timer = format_trial_timer(
            profile, settings_obj, day, conn=conn, username=username
        )
    return format_today(profile, targets, totals, sleep_row, next_class, timer)


def build_menu(
    conn: sqlite3.Connection,
    user_id: int,
    settings_obj: Settings,
    default_tz: str = DEFAULT_TIMEZONE,
    today: str | None = None,
    username: str | None = None,
) -> str:
    """Текст /menu: статус доступа + таймер, пересчитанный на этот вызов."""
    profile = get_profile(conn, user_id)
    day = today or calc.local_today(_profile_tz(profile, default_tz))
    if username is None:
        username = _username_for(conn, user_id)
    free = access.is_free(settings_obj, user_id=user_id, username=username, conn=conn)
    timer = None
    if not free:
        timer = format_trial_timer(
            profile, settings_obj, day, conn=conn, username=username
        )
    return format_menu(profile, settings_obj, day, timer=timer, free=free)


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


# --- оплата: ссылки и клавиатура ------------------------------------------------

async def invoice_urls(settings_obj: Settings, user_id: int, base_active: bool) -> dict[str, str]:
    """Создаёт ссылки на оплату (base всегда, ai — только при активной base).

    Использует ту же функцию Bot API, что и ``POST /api/pay/invoice``; ошибки
    только логируются, чтобы статус /subscription не падал без сети.
    """
    from .api import create_invoice_link  # локальный импорт: без цикла api <-> bot

    urls: dict[str, str] = {}
    kinds = ["base", "ai"] if base_active else ["base"]
    for kind in kinds:
        try:
            data = await create_invoice_link(settings_obj, int(user_id), kind)
            urls[kind] = str(data["invoice_url"])
        except Exception as exc:  # noqa: BLE001 — сеть/Bot API: кнопка просто не появится
            log.warning("invoice: не удалось создать ссылку %s для %s: %s", kind, user_id, exc)
    return urls


def subscription_markup(
    settings_obj: Settings, urls: dict[str, str]
) -> InlineKeyboardMarkup | None:
    """Inline-кнопки «Оплатить N ₽» / «Подключить ИИ +N ₽» со ссылками на invoice."""
    rows: list[list[InlineKeyboardButton]] = []
    if urls.get("base"):
        rows.append([
            InlineKeyboardButton(
                text=f"Оплатить {settings_obj.base_price_rub} ₽", url=urls["base"]
            )
        ])
    if urls.get("ai"):
        rows.append([
            InlineKeyboardButton(
                text=f"Подключить ИИ +{settings_obj.ai_price_rub} ₽", url=urls["ai"]
            )
        ])
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


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

    async def require_base(message: Message) -> bool:
        """Гейт команд: True — можно выполнять; иначе отправлен paywall."""
        if not (settings_obj.subscription_enforced and not settings_obj.is_dev):
            return True
        if _is_free_message(settings_obj, message, conn):
            return True
        user_id = user_id_of(message)
        try:
            profile = get_profile(conn, user_id)
        except sqlite3.Error:
            log.exception("Не удалось прочитать профиль для гейта (user_id=%s)", user_id)
            profile = None
        today = calc.local_today(default_tz)
        if subscription_active(profile, today):
            return True
        urls = await invoice_urls(settings_obj, user_id, base_active=False)
        await answer(message, PAYWALL_TEXT, subscription_markup(settings_obj, urls))
        return False

    async def send_subscription(message: Message) -> None:
        """Статус подписки + inline-кнопки оплаты base/ai (CONTRACT §24)."""
        user_id = user_id_of(message)
        free = _is_free_message(settings_obj, message, conn)
        try:
            profile = get_profile(conn, user_id)
        except sqlite3.Error:
            log.exception("Не удалось прочитать профиль для /subscription (user_id=%s)", user_id)
            profile = None
        today = calc.local_today(default_tz)
        timer = None
        if not free:
            sender = _sender(message)
            timer = format_trial_timer(
                profile,
                settings_obj,
                today,
                conn=conn,
                username=getattr(sender, "username", None) if sender else None,
            )
        text = format_subscription(profile, settings_obj, today, free, timer=timer)
        if free:
            # Бесплатный доступ: без цен и без кнопок оплаты.
            await answer(message, text, open_app_keyboard(settings_obj.app_url))
            return
        urls = await invoice_urls(
            settings_obj, user_id, base_active=subscription_active(profile, today)
        )
        if not urls:
            text += "\n\n⚠️ Не удалось создать ссылку на оплату — попробуй позже."
        await answer(message, text, subscription_markup(settings_obj, urls))

    @router.pre_checkout_query()
    async def on_pre_checkout(query: PreCheckoutQuery) -> None:
        """Telegram требует подтвердить pre_checkout_query (CONTRACT §24)."""
        await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def on_successful_payment(message: Message) -> None:
        """Оплата Stars: продлевает подписку и подтверждает в чате."""
        payment = message.successful_payment
        try:
            result = apply_payment(settings_obj, conn, payment, user_id_of(message))
        except Exception:  # noqa: BLE001 — платёж не должен ронять polling
            log.exception("Ошибка обработки successful_payment (user_id=%s)", user_id_of(message))
            await message.answer("😔 Оплата получена, но не удалось обновить подписку. Напиши в поддержку.")
            return
        if not result["ok"]:
            return
        markup = open_app_keyboard(settings_obj.app_url) if result["kind"] == "base" else None
        await answer(message, result["text"], markup)

    @router.message(Command("subscription"))
    async def cmd_subscription(message: Message) -> None:
        await send_subscription(message)

    @router.message(Command("menu"))
    async def cmd_menu(message: Message) -> None:
        """Меню: срок доступа, живой таймер периода и краткий список команд."""
        sender = _sender(message)
        try:
            text = build_menu(
                conn,
                user_id_of(message),
                settings_obj,
                default_tz,
                username=getattr(sender, "username", None) if sender else None,
            )
        except sqlite3.Error:
            log.exception("Ошибка /menu для user_id=%s", user_id_of(message))
            text = "😔 Не получилось показать меню. Попробуй ещё раз чуть позже."
        await answer(message, text, open_app_keyboard(settings_obj.app_url))

    @router.message(Command("whoami"))
    async def cmd_whoami(message: Message) -> None:
        """ID и username отправителя — чтобы владелец узнал свой Telegram ID."""
        await answer(message, format_whoami(message))

    @router.message(Command("grant"))
    async def cmd_grant(message: Message) -> None:
        """Владелец: выдать бесплатный доступ по ID или @username."""
        await answer(message, command_grant(settings_obj, conn, message))

    @router.message(Command("revoke"))
    async def cmd_revoke(message: Message) -> None:
        """Владелец: снять бесплатный доступ."""
        await answer(message, command_revoke(settings_obj, conn, message))

    @router.message(Command("free_list"))
    async def cmd_free_list(message: Message) -> None:
        """Владелец: список бесплатного доступа из БД и env."""
        await answer(message, command_free_list(settings_obj, conn, message))

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
        if not await require_base(message):
            return
        sender = _sender(message)
        try:
            text = build_today(
                conn,
                user_id_of(message),
                default_tz,
                settings_obj=settings_obj,
                username=getattr(sender, "username", None) if sender else None,
            )
        except sqlite3.Error:
            log.exception("Ошибка /today для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить данные. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("plan"))
    async def cmd_plan(message: Message) -> None:
        if not await require_base(message):
            return
        try:
            text = build_plan(conn, user_id_of(message), default_tz)
        except sqlite3.Error:
            log.exception("Ошибка /plan для user_id=%s", user_id_of(message))
            text = "😔 Не получилось построить план. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("classes"))
    async def cmd_classes(message: Message) -> None:
        if not await require_base(message):
            return
        try:
            text = build_classes(conn, user_id_of(message), default_tz)
        except sqlite3.Error:
            log.exception("Ошибка /classes для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить расписание. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("sleep"))
    async def cmd_sleep(message: Message) -> None:
        if not await require_base(message):
            return
        try:
            text = build_sleep(conn, user_id_of(message))
        except sqlite3.Error:
            log.exception("Ошибка /sleep для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить запись сна. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("targets"))
    async def cmd_targets(message: Message) -> None:
        if not await require_base(message):
            return
        try:
            text = build_targets(conn, user_id_of(message))
        except sqlite3.Error:
            log.exception("Ошибка /targets для user_id=%s", user_id_of(message))
            text = "😔 Не получилось получить цели. Попробуй ещё раз чуть позже."
        await answer(message, text)

    @router.message(Command("export"))
    async def cmd_export(message: Message) -> None:
        if not await require_base(message):
            return
        parts = (message.text or "").split()[1:]
        period = next((p.lower() for p in parts if p.lower() in reports.PERIODS), "day")
        fmt = next((p.lower() for p in parts if p.lower() in ("png", "docx", "xlsx")), "png")
        user_id = user_id_of(message)
        await message.answer("⏳ Собираю отчёт…")
        try:
            profile = get_profile(conn, user_id)
            today = calc.local_today(default_tz)
            use_llm = _is_free_message(settings_obj, message, conn) or effective_ai(profile, today)
            filename, payload = await asyncio.to_thread(
                reports.build, conn, user_id, period, fmt, use_llm=use_llm)
        except Exception:
            log.exception("Ошибка /export для user_id=%s", user_id)
            await message.answer("😔 Не получилось собрать отчёт. Попробуй ещё раз чуть позже.")
            return
        await message.answer_document(
            BufferedInputFile(payload, filename=filename),
            caption=f"📄 {reports.PERIODS[period]} · {fmt.upper()}",
        )

    @router.message(Command("note"))
    async def cmd_note(message: Message) -> None:
        if not await require_base(message):
            return
        text = (message.text or "").partition(" ")[2].strip()
        if not text:
            await message.answer("✍️ Напиши так: <code>/note сегодня тяжело, мало спал</code>")
            return
        user_id = user_id_of(message)
        free = _is_free_message(settings_obj, message, conn)
        try:
            profile = get_profile(conn, user_id)
            today = calc.local_today(
                _profile_tz(profile, default_tz) if profile else default_tz
            )
            # v5: ИИ работает при оплаченном ai_until (CONTRACT §22–24) или бесплатно.
            ai_enabled = free or effective_ai(profile, today)
            reply = await asyncio.to_thread(
                reports.save_note, conn, user_id, text, None, ai_enabled
            )
        except Exception:
            log.exception("Ошибка /note для user_id=%s", user_id)
            await message.answer("😔 Не получилось сохранить заметку. Попробуй ещё раз чуть позже.")
            return
        if not ai_enabled:
            # ИИ-разбор выключен/не оплачен: заметка сохранена, модель не вызывалась.
            await answer(
                message,
                "📝 Заметка сохранена. ИИ-разбор не подключён — "
                "ИИ +100 ₽/мес: /subscription",
            )
            return
        await answer(message, "📝 <b>Заметка сохранена.</b>\n\n🤖 <b>ИИ-разбор:</b>\n" + _esc(reply))

    @router.message(Command("notes"))
    async def cmd_notes(message: Message) -> None:
        if not await require_base(message):
            return
        try:
            rows = await asyncio.to_thread(reports.last_notes, conn, user_id_of(message))
        except Exception:
            log.exception("Ошибка /notes для user_id=%s", user_id_of(message))
            rows = []
        if not rows:
            await message.answer("Заметок пока нет — добавь первую: <code>/note что-нибудь о дне</code>")
            return
        lines = ["📝 <b>Последние заметки</b>"]
        for row in rows:
            lines.append(f"\n<b>{_esc(row['date'])}</b>: {_esc(row['text'][:200])}")
            if row.get("ai_text"):
                lines.append(f"🤖 {_esc(row['ai_text'][:300])}")
        await answer(message, "\n".join(lines))

    @router.message(Command("ask", "ai"))
    async def cmd_ask(message: Message) -> None:
        """Свободный вопрос ИИ (алиас /ai): контекст из ai_chat, ответ до 4000.

        Base-гейт здесь не нужен (``/ask`` в :data:`FREE_COMMANDS`): доступ
        проверяется только по ИИ-тарифу, а при его отсутствии — подсказка
        «ИИ +100 ₽/мес — /subscription».
        """
        question = _command_args(message)
        if not question:
            await message.answer("Напиши: /ask любой вопрос")
            return
        if len(question) > 2000:
            await message.answer("Вопрос слишком длинный — до 2000 символов.")
            return
        user_id = user_id_of(message)
        sender = _sender(message)
        username = getattr(sender, "username", None) if sender else None
        try:
            profile = get_profile(conn, user_id)
            today = calc.local_today(
                _profile_tz(profile, default_tz) if profile else default_tz
            )
            # Гейт ИИ: free/промо или оплаченный ai_until (CONTRACT §22, §29).
            if not ai.is_ai_available(
                settings_obj,
                user_id=user_id,
                username=username,
                conn=conn,
                profile=profile,
                today=today,
            ):
                await answer(message, "🔒 ИИ +100 ₽/мес — /subscription")
                return
            # История — до нового сообщения; в модель уходят последние 12.
            history = store.list_chat_messages(conn, user_id, ai.HISTORY_LIMIT)
            store.add_chat_message(conn, user_id, "user", question)
            reply = await asyncio.to_thread(ai.chat_reply, history, question)
            if not reply:
                reply = ai.local_chat_fallback(question)
            store.add_chat_message(conn, user_id, "assistant", reply)
        except Exception:
            log.exception("Ошибка /ask для user_id=%s", user_id)
            await message.answer("😔 Не получилось ответить. Попробуй ещё раз чуть позже.")
            return
        await answer(message, _esc(reply[:4000]))

    return router


# --- фоновые напоминания -------------------------------------------------------

async def _trial_end_tick(
    conn: sqlite3.Connection,
    bot: Bot,
    settings_obj: Settings,
    blocked: set[int],
) -> None:
    """D-1: за день до конца бесплатного периода — одно сообщение с кнопкой.

    Обходит профили с заполненным ``sub_until`` (независимо от тумблера
    обычных напоминаний: это сообщение про оплату, а не про режим дня).
    Дедуп — ``reminder_log(user_id, date, kind='trial_end')``; бесплатный
    доступ (whitelist) пропускается. Ошибки ловятся, цикл не роняем.
    """
    try:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE sub_until IS NOT NULL ORDER BY user_id"
        ).fetchall()
    except sqlite3.Error:
        log.exception("Не удалось прочитать профили для D-1 напоминания")
        return
    for row in rows:
        profile = dict(row)
        user_id = int(profile.get("user_id") or 0)
        if not user_id or user_id in blocked:
            continue
        now = calc.local_now(_profile_tz(profile, settings_obj.timezone))
        today = now.date().isoformat()
        try:
            free = access.is_free(
                settings_obj,
                user_id=user_id,
                username=_username_for(conn, user_id),
                conn=conn,
            )
        except Exception:  # noqa: BLE001 — гейт free не должен ронять тик
            log.exception("Не удалось проверить бесплатный доступ для %s", user_id)
            continue
        text = trial_end_due(settings_obj, conn, profile, today, free)
        if text is None:
            continue
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=open_app_keyboard(settings_obj.app_url),
            )
        except TelegramForbiddenError:
            blocked.add(user_id)
            log.warning(
                "Пользователь %s заблокировал бота — D-1 напоминания приостановлены",
                user_id,
            )
            continue
        except TelegramRetryAfter as exc:
            log.warning(
                "Telegram просит подождать %s с — D-1 напоминание для %s отложено",
                getattr(exc, "retry_after", "?"),
                user_id,
            )
            continue
        except TelegramAPIError as exc:
            log.warning("Не удалось отправить D-1 напоминание %s: %s", user_id, exc)
            continue
        except Exception:  # noqa: BLE001 — напоминания не должны ронять бота
            log.exception("Неожиданная ошибка D-1 напоминания для %s", user_id)
            continue
        try:
            store.mark_reminder(conn, user_id, today, KIND_TRIAL_END)
        except sqlite3.Error:
            log.exception("Не удалось записать reminder_log D-1 для %s", user_id)


async def _reminder_tick(
    conn: sqlite3.Connection,
    bot: Bot,
    settings_obj: Settings,
    blocked: set[int],
) -> None:
    """Один проход: D-1 про конец периода + напоминания по режиму дня."""
    await _trial_end_tick(conn, bot, settings_obj, blocked)
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
            BotCommand(command="menu", description="Меню: доступ, таймер периода, команды"),
            BotCommand(command="app", description="Открыть мини-приложение"),
            BotCommand(command="today", description="Сводка за сегодня"),
            BotCommand(command="plan", description="План питания на сегодня"),
            BotCommand(command="classes", description="Ближайшие занятия"),
            BotCommand(command="sleep", description="Сон и окно питания"),
            BotCommand(command="targets", description="Цели по КБЖУ и воде"),
            BotCommand(command="export", description="Отчёт: день/неделя/месяц (png, docx, xlsx)"),
            BotCommand(command="note", description="Заметка с разбором ИИ"),
            BotCommand(command="notes", description="Последние заметки и ответы ИИ"),
            BotCommand(command="ask", description="Спросить ИИ: любой вопрос (алиас /ai)"),
            BotCommand(command="subscription", description="Подписка и оплата (Stars)"),
            BotCommand(command="whoami", description="Мой Telegram ID и username"),
            BotCommand(command="grant", description="Владелец: выдать бесплатный доступ"),
            BotCommand(command="revoke", description="Владелец: снять бесплатный доступ"),
            BotCommand(command="free_list", description="Владелец: список бесплатного доступа"),
            BotCommand(command="help", description="Список команд"),
        ])
    except TelegramAPIError as exc:
        log.warning("Не удалось обновить меню команд: %s", exc)


# --- точка входа ---------------------------------------------------------------

async def _polling_forever(bot: Bot, dispatcher: Dispatcher, initial_delay: float = 3.0) -> None:
    """Long polling с автопереподключением.

    При деплое на Render старый и новый контейнеры на секунды пересекаются: Telegram
    отвечает ``409 Conflict``, aiogram останавливает polling и без повтора бот молчит
    до следующего рестарта. Поэтому запускаем polling в цикле, пока задачу не отменят.
    """
    delay = max(0.01, float(initial_delay))
    while True:
        try:
            await dispatcher.start_polling(bot)
            log.warning("Polling завершился, перезапуск через %.0f с", delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - любой сбой сети/Telegram
            log.warning(
                "Polling упал (%s: %s), перезапуск через %.0f с",
                type(exc).__name__,
                str(exc)[:200],
                delay,
            )
        await asyncio.sleep(delay)
        delay = min(delay * 1.6, 60.0)
        log.info("Перезапуск polling")


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
        await _polling_forever(bot, dispatcher)
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
