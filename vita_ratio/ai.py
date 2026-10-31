"""Универсальный ИИ-ассистент Vita Ratio: свободный чат и общий гейт доступа.

Модуль не зависит от aiohttp и aiogram: его используют и REST-слой (``api.py``),
и бот (``bot.py``). Вызов модели делегируется в :func:`reports.chat_completion`,
поэтому провайдеры (Groq/OpenAI-совместимый/Gemini/Pollinations) настраиваются
там же через env и не дублируются.

История диалога хранится в таблице ``ai_chat`` (см. :mod:`vita_ratio.store`):
в модель уходят последние 12 сообщений плюс системный промпт.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any

from . import access, calc, reports, store

log = logging.getLogger("vita_ratio.ai")

#: Системный промпт обычного (не только про еду) ассистента.
SYSTEM_PROMPT = (
    "Ты универсальный ИИ-ассистент в приложении Vita Ratio. Отвечай на любые вопросы "
    "пользователя (не только про питание): учёба, тренировки, код, общие знания. "
    "Пиши по-русски, кратко и по делу (до 6 предложений), без markdown-списков. "
    "Если вопрос про еду/сон/тренировки — можешь отвечать как коуч."
)

#: Сколько последних сообщений диалога передавать модели.
HISTORY_LIMIT = 12

#: Текст, если модель недоступна совсем (чат при этом не ломается).
LOCAL_FALLBACK = "Сейчас не могу связаться с моделью, попробуй позже."

DEFAULT_TIMEZONE = "Europe/Moscow"


def _date_active(value: Any, today: str) -> bool:
    """Дата ``until`` действует по ``today`` включительно; мусор -> False."""
    if not value:
        return False
    try:
        return date_cls.fromisoformat(str(value)[:10]) >= date_cls.fromisoformat(str(today)[:10])
    except (TypeError, ValueError):
        return False


def _dget(row: Any, key: str, default: Any = None) -> Any:
    """Поле профиля из dict/sqlite3.Row/объекта; None -> default."""
    if row is None:
        return default
    if isinstance(row, dict):
        value = row.get(key, default)
    else:
        try:
            value = row[key]
        except (TypeError, IndexError, KeyError):
            value = getattr(row, key, default)
    return default if value is None else value


def local_chat_fallback(user_text: str) -> str:
    """Короткий честный ответ при полном сбое модели.

    ``user_text`` принимается для единообразия сигнатуры (и будущих вариаций),
    сейчас текст не зависит от вопроса.
    """
    del user_text
    return LOCAL_FALLBACK


def chat_reply(history: list[dict], user_text: str) -> str | None:
    """Ответ модели на вопрос пользователя с контекстом последних сообщений.

    ``history`` — сообщения из ``ai_chat`` (``{"role", "text"}``) в
    хронологическом порядке; берутся последние :data:`HISTORY_LIMIT`.
    Возвращает ``None`` при любом сбое — вызывающий код подставит
    :func:`local_chat_fallback`.
    """
    try:
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in list(history or [])[-HISTORY_LIMIT:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in ("user", "assistant"):
                continue
            content = item.get("text")
            if content is None:
                content = item.get("content")
            text = str(content).strip() if content is not None else ""
            if text:
                messages.append({"role": role, "content": text})
        question = str(user_text or "").strip()
        if not question:
            return None
        messages.append({"role": "user", "content": question})
        return reports.chat_completion(messages) or None
    except Exception:  # noqa: BLE001 — чат не должен падать из-за модели
        log.exception("ai: не удалось получить ответ чата")
        return None


def is_ai_available(
    settings_obj,
    user_id: int | None = None,
    username: str | None = None,
    conn=None,
    profile: Any = None,
    today: str | None = None,
) -> bool:
    """Доступен ли пользователю ИИ (free / оплаченный или промо-аддон ``ai_until``).

    Логика та же, что у ``effective_ai`` в API и боте: бесплатный доступ
    (CONTRACT §29) включает ИИ всегда; иначе нужен флаг ``ai_enabled=1`` и
    ``ai_until >= today`` (дата включительно). Промо-триал ИИ работает через
    тот же ``ai_until``, который выставляется при создании профиля, если задан
    ``AI_TRIAL_DAYS``. Ошибки чтения БД -> ``False`` (гейт не роняем).
    """
    try:
        if access.is_free(settings_obj, user_id=user_id, username=username, conn=conn):
            return True
    except Exception:  # noqa: BLE001 — whitelist не должен ронять гейт
        log.exception("ai: не удалось проверить бесплатный доступ")
    if profile is None and conn is not None and user_id is not None:
        try:
            profile = store.get_profile(conn, int(user_id))
        except Exception:  # noqa: BLE001 — нет таблицы/битая БД
            log.exception("ai: не удалось прочитать профиль")
            return False
    if not profile:
        return False
    try:
        enabled = int(_dget(profile, "ai_enabled", 0) or 0) == 1
    except (TypeError, ValueError):
        enabled = False
    if not enabled:
        return False
    if today is None:
        timezone = getattr(settings_obj, "timezone", None) or DEFAULT_TIMEZONE
        today = calc.local_today(timezone)
    return _date_active(_dget(profile, "ai_until", None), str(today))
