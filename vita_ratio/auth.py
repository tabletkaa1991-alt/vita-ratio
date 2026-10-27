"""Аутентификация запросов к API Vita Ratio.

Два способа:
1. Telegram Mini App: заголовок ``X-Init-Data`` проверяется по спеке Telegram
   (HMAC-SHA256, ``auth_date`` не старше 24 ч).
2. Демо-режим браузера: при ``APP_ENV=dev`` заголовок ``X-Dev-User: <int>``.

Ошибки авторизации поднимаются как :class:`AuthError`; api.py превращает их в
``401 {"ok": false, "error": "unauthorized"}``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from aiohttp import web

from . import store

#: Сколько секунд initData считается свежим (24 часа по спеке Telegram).
INIT_DATA_TTL_SECONDS = 24 * 60 * 60
#: Допустимое расхождение часов при проверке auth_date из будущего.
CLOCK_SKEW_SECONDS = 300
#: Ключи приложения aiohttp (AppKey вместо строк — без NotAppKeyWarning).
CONN_KEY = web.AppKey("conn", object)
SETTINGS_KEY = web.AppKey("settings", object)


class AuthError(Exception):
    """Не удалось определить пользователя запроса."""

    def __init__(self, message: str = "Требуется авторизация Telegram", code: str = "unauthorized") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _secret_key(bot_token: str) -> bytes:
    """secret = HMAC_SHA256(key="WebAppData", msg=bot_token)."""
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def _data_check_string(fields: dict[str, str]) -> str:
    """Пары key=value (без hash), отсортированные по ключу, через \\n."""
    return "\n".join(f"{key}={fields[key]}" for key in sorted(fields))


def _parse_user(fields: dict[str, str]) -> dict:
    raw = fields.get("user")
    if raw is None:
        raise AuthError("В initData нет поля user")
    try:
        user = json.loads(raw)
    except (TypeError, ValueError):
        raise AuthError("Поле user в initData — не JSON") from None
    if not isinstance(user, dict):
        raise AuthError("Поле user в initData — не объект")
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        raise AuthError("В initData нет корректного id пользователя") from None
    if user_id <= 0:
        raise AuthError("Некорректный id пользователя в initData")

    result = dict(user)
    result["id"] = user_id
    for key in ("username", "first_name", "last_name"):
        value = result.get(key)
        result[key] = str(value) if value not in (None, "") else None
    return result


def parse_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int | None = INIT_DATA_TTL_SECONDS,
) -> dict:
    """Проверяет подпись Telegram initData и разбирает её в dict.

    ``max_age_seconds=None`` отключает проверку свежести (используется в dev).
    Бросает :class:`AuthError` при любой проблеме.
    """
    if not init_data or not str(init_data).strip():
        raise AuthError("Пустая строка initData")
    if not bot_token:
        raise AuthError("BOT_TOKEN не настроен — проверить initData невозможно")

    pairs = parse_qsl(str(init_data).strip(), keep_blank_values=True)
    if not pairs:
        raise AuthError("Не удалось разобрать initData")

    fields: dict[str, str] = {}
    for key, value in pairs:
        fields[key] = value

    received_hash = (fields.pop("hash", "") or "").strip().lower()
    if not received_hash:
        raise AuthError("В initData нет hash")

    data_check_string = _data_check_string(fields)
    expected_hash = hmac.new(
        _secret_key(bot_token),
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise AuthError("Подпись initData не совпадает")

    try:
        auth_date = int(fields.get("auth_date", ""))
    except (TypeError, ValueError):
        raise AuthError("В initData нет корректного auth_date") from None

    if max_age_seconds is not None:
        now = int(time.time())
        if auth_date > now + CLOCK_SKEW_SECONDS:
            raise AuthError("auth_date из будущего — проверьте часы устройства")
        if now - auth_date > int(max_age_seconds):
            raise AuthError("initData просрочен — откройте мини-приложение заново")

    result: dict = dict(fields)
    result["hash"] = received_hash
    result["auth_date"] = auth_date
    result["user"] = _parse_user(fields)
    return result


def _dev_user(request, conn) -> dict:
    raw = (request.headers.get("X-Dev-User") or "").strip()
    try:
        user_id = int(raw)
    except (TypeError, ValueError):
        raise AuthError("Заголовок X-Dev-User должен быть целым числом") from None
    if user_id <= 0:
        raise AuthError("Заголовок X-Dev-User должен быть положительным числом")
    return _persist_user(conn, user_id, username="demo", first_name="Демо", last_name=None)


def _persist_user(conn, user_id: int, username=None, first_name=None, last_name=None) -> dict:
    if conn is None:
        return {
            "id": int(user_id),
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
    return store.upsert_user(conn, int(user_id), username=username, first_name=first_name, last_name=last_name)


def authenticate(request, settings) -> dict:
    """Определяет пользователя запроса и создаёт/обновляет запись в ``users``.

    Возвращает dict пользователя (``id``, ``username``, ``first_name``, ``last_name``).
    """
    init_data = (request.headers.get("X-Init-Data") or "").strip()
    application = getattr(request, "app", None)
    conn = application.get(CONN_KEY) if application is not None else None

    if init_data:
        fresh_seconds = None if settings.is_dev else INIT_DATA_TTL_SECONDS
        data = parse_init_data(init_data, settings.bot_token, max_age_seconds=fresh_seconds)
        tg_user = data["user"]
        return _persist_user(
            conn,
            int(tg_user["id"]),
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
            last_name=tg_user.get("last_name"),
        )

    if settings.is_dev:
        if (request.headers.get("X-Dev-User") or "").strip():
            return _dev_user(request, conn)

    raise AuthError("Требуется авторизация Telegram")
