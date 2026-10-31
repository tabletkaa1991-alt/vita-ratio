"""Уведомления в чат Telegram от имени бота (например, приветствие после онбординга).

Отправка идёт напрямую в Bot API по токену из настроек сервера: бот и веб-сервер
живут в одном процессе, отдельный экземпляр aiogram не нужен.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date as date_cls

import aiohttp

from .config import Settings

log = logging.getLogger("vita_ratio.notify")

WELCOME_CHECK = "✅"

#: Сколько дней по умолчанию в бесплатном периоде (совпадает с TRIAL_DAYS).
DEFAULT_TRIAL_DAYS = 7
#: Базовая цена подписки по умолчанию (₽/мес) — как BASE_PRICE_RUB.
DEFAULT_BASE_PRICE_RUB = 250


def _parse_day(value) -> date_cls | None:
    """ISO-дата/date из значения; мусор -> None (блок не показываем)."""
    if isinstance(value, date_cls):
        return value
    if not value:
        return None
    try:
        return date_cls.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _days_word(value: int) -> str:
    """Русская форма слова «день» для числа."""
    number = abs(int(value))
    if number % 10 == 1 and number % 100 != 11:
        return "день"
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return "дня"
    return "дней"


def _trial_lines(
    trial_until=None,
    trial_days: int | None = None,
    base_price_rub: int = DEFAULT_BASE_PRICE_RUB,
    today=None,
) -> list[str]:
    """Строки блока «бесплатный период»; [] — если даты нет/она уже прошла.

    Даты и числа экранировать не нужно (только цифры и точки), но цена берётся
    из настроек и приводится к целому, чтобы HTML не сломать.
    """
    until = _parse_day(trial_until)
    if until is None:
        return []
    current = _parse_day(today) or date_cls.today()
    try:
        total = int(trial_days) if trial_days is not None else (until - current).days
    except (TypeError, ValueError):
        total = (until - current).days
    left = (until - current).days
    if total <= 0 or left < 0:
        return []
    try:
        price = int(base_price_rub)
    except (TypeError, ValueError):
        price = DEFAULT_BASE_PRICE_RUB
    date_text = f"{until.day:02d}.{until.month:02d}.{until.year}"
    return [
        f"🎁 Бесплатный период активирован: {total} {_days_word(total)}, до {date_text}.",
        (
            f"⏳ Осталось: {left} дн. Таймер обновляется в /menu. "
            f"Следующая оплата не требуется — подписка {price} ₽/мес начнётся после периода."
        ),
    ]


def registration_text(
    first_name: str | None = None,
    targets: dict | None = None,
    trial_until=None,
    trial_days: int | None = None,
    base_price_rub: int = DEFAULT_BASE_PRICE_RUB,
    today=None,
) -> str:
    """Текст поздравления после успешной регистрации (онбординга).

    ``trial_until``/``trial_days`` добавляют блок про бесплатный период. Без
    ``trial_until`` текст прежний: старые вызовы ``registration_text(name,
    targets)`` работают как раньше. ``today`` — для детерминированного расчёта
    «осталось N дн.» в тестах (по умолчанию — сегодняшняя дата сервера).
    """
    name = html.escape(str(first_name).strip()) if first_name else ""
    greeting = f"{name}, " if name else ""
    lines = [
        "✅ <b>Регистрация прошла успешно!</b>",
        "",
        (
            f"{greeting}добро пожаловать в <b>Vita Ratio</b>! "
            "Желаем отличного настроения и продуктивного набора 💪"
        ),
    ]
    if targets and targets.get("kcal"):
        lines.append("")
        lines.append(
            "Твои цели: <b>{kcal} ккал</b> · белок {protein} г · жиры {fat} г · углеводы {carbs} г".format(
                kcal=int(targets.get("kcal") or 0),
                protein=int(targets.get("protein") or 0),
                fat=int(targets.get("fat") or 0),
                carbs=int(targets.get("carbs") or 0),
            )
        )
    trial_lines = _trial_lines(trial_until, trial_days, base_price_rub, today)
    if trial_lines:
        lines.extend(["", *trial_lines])
    lines.extend([
        "",
        "Открывай приложение, записывай еду, сон и тренировки — я напомню о приёмах пищи и отбое.",
        "",
        WELCOME_CHECK,
    ])
    return "\n".join(lines)


def should_notify(settings: Settings) -> bool:
    """В проде с токеном — да; локально/в тестах не спамим и не ходим в сеть."""
    return bool(settings.bot_token) and not settings.is_dev


async def send_message(settings: Settings, chat_id: int, text: str, with_webapp_button: bool = True) -> bool:
    """Отправляет сообщение в чат. Ошибки логирует и возвращает False (бота не роняет)."""
    if not should_notify(settings):
        return False
    payload: dict = {
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if with_webapp_button and settings.app_url.startswith("https://"):
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "Открыть Vita Ratio", "web_app": {"url": settings.app_url}}]]
        }
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    timeout = aiohttp.ClientTimeout(total=20)
    for attempt in (1, 2):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        return True
                    body = (await response.text())[:300]
                    log.warning("notify: sendMessage %s: %s", response.status, body)
                    return False
        except Exception as exc:  # сеть/таймаут — уведомление не критично
            log.warning(
                "notify: sendMessage attempt %s failed: %s: %s",
                attempt, type(exc).__name__, str(exc)[:200],
            )
            if attempt == 1:
                await asyncio.sleep(1.5)
    return False


async def notify_registration(
    settings: Settings,
    user_id: int,
    first_name: str | None = None,
    targets: dict | None = None,
    *,
    trial_until=None,
    trial_days: int | None = None,
    base_price_rub: int = DEFAULT_BASE_PRICE_RUB,
    today=None,
) -> bool:
    """Поздравление после создания профиля (онбординг завершён).

    Дополнительные kwargs (``trial_until``, ``trial_days``, ``base_price_rub``,
    ``today``) прокидываются в :func:`registration_text` и добавляют блок про
    активированный бесплатный период. Все они необязательные: старые вызовы
    ``notify_registration(settings, user_id, first_name, targets)`` работают
    как раньше.
    """
    text = registration_text(
        first_name,
        targets,
        trial_until=trial_until,
        trial_days=trial_days,
        base_price_rub=base_price_rub,
        today=today,
    )
    return await send_message(settings, user_id, text)
