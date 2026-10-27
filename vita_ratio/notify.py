"""Уведомления в чат Telegram от имени бота (например, приветствие после онбординга).

Отправка идёт напрямую в Bot API по токену из настроек сервера: бот и веб-сервер
живут в одном процессе, отдельный экземпляр aiogram не нужен.
"""
from __future__ import annotations

import asyncio
import html
import logging

import aiohttp

from .config import Settings

log = logging.getLogger("vita_ratio.notify")

WELCOME_CHECK = "✅"


def registration_text(first_name: str | None = None, targets: dict | None = None) -> str:
    """Текст поздравления после успешной регистрации (онбординга)."""
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
) -> bool:
    """Поздравление после создания профиля (онбординг завершён)."""
    return await send_message(settings, user_id, registration_text(first_name, targets))
