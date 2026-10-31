"""aiohttp-приложение и REST API Vita Ratio.

Успешный ответ: ``{"ok": true, "data": ...}``; ошибка: ``{"ok": false, "error": "<code>"}``
(плюс ``"message"`` с русским пояснением для отладки). Все даты — ISO
``YYYY-MM-DD``, время — ``HH:MM`` (локальная зона из настроек).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import uuid
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

import aiohttp
from aiohttp import web

from . import __version__, auth, calc, foods, notify, payments, reports, store

log = logging.getLogger("vita_ratio.api")

#: Размер тела запроса, дальше — 413 от aiohttp.
MAX_BODY_BYTES = 256 * 1024
#: Пресеты палитры (CONTRACT §11): id, подпись и три цвета.
THEME_PRESETS: list[dict] = [
    {"id": "lime", "title": "Лайм", "accent": "#B7F75C", "bg": "#0E1116", "card": "#151A21"},
    {"id": "violet", "title": "Фиолетовый", "accent": "#C4B5FD", "bg": "#0F0B1A", "card": "#1A1426"},
    {"id": "cyan", "title": "Бирюзовый", "accent": "#67E8F9", "bg": "#071318", "card": "#102028"},
    {"id": "pink", "title": "Розовый", "accent": "#F9A8D4", "bg": "#160B12", "card": "#221018"},
    {"id": "orange", "title": "Оранжевый", "accent": "#FDBA74", "bg": "#160F08", "card": "#241709"},
    {"id": "mint", "title": "Мята", "accent": "#6EE7B7", "bg": "#081513", "card": "#0F211E"},
    {"id": "blue", "title": "Синий", "accent": "#93C5FD", "bg": "#0A1018", "card": "#131C27"},
    {"id": "graphite", "title": "Графит", "accent": "#E5E7EB", "bg": "#0D0D0F", "card": "#18181B"},
]
#: Дефолтная палитра (lime).
THEME_DEFAULTS = {"accent": "#B7F75C", "bg": "#0E1116", "card": "#151A21"}
#: Допустимый цвет — только hex #RRGGBB.
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
#: Расширения файлов, которые можно отдавать из webapp/.
STATIC_SUFFIXES = {
    ".html",
    ".js",
    ".css",
    ".svg",
    ".png",
    ".ico",
    ".json",
    ".webp",
    ".woff",
    ".woff2",
    ".txt",
}
#: Коды/сообщения для стандартных HTTP-ошибок aiohttp.
_HTTP_ERRORS = {
    400: ("bad_request", "Некорректный запрос"),
    403: ("forbidden", "Доступ запрещён"),
    404: ("not_found", "Не найдено"),
    405: ("method_not_allowed", "Метод не поддерживается"),
    413: ("payload_too_large", "Слишком большое тело запроса"),
    415: ("unsupported_media_type", "Неподдерживаемый тип данных"),
    500: ("internal_error", "Внутренняя ошибка сервера"),
}

# --- подписка (CONTRACT §22–23) --------------------------------------------------
#: API-пути, доступные без активной base-подписки.
SUBSCRIPTION_FREE_PATHS = frozenset({
    "/api/health",
    "/api/bootstrap",
    "/api/subscription",
    "/api/pay/invoice",
    "/api/pay/refresh",
    # Вебхуки эквайринга: публичные, подлинность проверяется провайдером.
    "/api/pay/yookassa",
    "/api/pay/robokassa/result",
    "/api/pay/robokassa/success",
})
#: URL Bot API для создания ссылки на оплату Telegram Stars.
INVOICE_API_URL = "https://api.telegram.org/bot{token}/createInvoiceLink"


def _is_date_active(value, today: str) -> bool:
    """Дата ``until`` действует по сегодня включительно (ISO ``YYYY-MM-DD``)."""
    if not value:
        return False
    try:
        return date_cls.fromisoformat(str(value)[:10]) >= date_cls.fromisoformat(str(today)[:10])
    except (TypeError, ValueError):
        return False


def subscription_active(profile: dict | None, today: str) -> bool:
    """Активна ли base-подписка (дата включительно)."""
    return _is_date_active((profile or {}).get("sub_until"), today)


def ai_active(profile: dict | None, today: str) -> bool:
    """Активен ли ИИ-аддон (дата включительно)."""
    return _is_date_active((profile or {}).get("ai_until"), today)


def effective_ai(profile: dict | None, today: str) -> bool:
    """Эффективный ИИ: флаг включён пользователем И оплачен до сегодня."""
    return bool((profile or {}).get("ai_enabled")) and ai_active(profile, today)


def gate_enabled(settings_obj) -> bool:
    """Платный режим реально включён: enforced и это не dev-среда."""
    return bool(settings_obj.subscription_enforced) and not settings_obj.is_dev


def subscription_gate(
    settings_obj,
    path: str,
    profile: dict | None,
    today: str,
    ai_required: bool = False,
) -> "ApiError | None":
    """Чистая проверка гейта: ``None`` — доступ есть, иначе :class:`ApiError` 402.

    Пропускает не-API пути (статика/мини-приложение) и белый список §23.
    Новый пользователь без профиля может создать его (онбординг) и получить триал —
    иначе триал, создаваемый вместе с профилем, был бы недостижим.
    """
    if not gate_enabled(settings_obj):
        return None
    if not str(path).startswith("/api/"):
        return None
    if path in SUBSCRIPTION_FREE_PATHS:
        return None
    if path == "/api/profile" and profile is None:
        return None
    if not subscription_active(profile, today):
        return ApiError(402, "subscription_required", "Подписка 250 ₽/мес нужна для доступа")
    if ai_required and not ai_active(profile, today):
        return ApiError(402, "ai_subscription_required", "ИИ +100 ₽/мес — подключите для доступа")
    return None


def _subscription_json(profile: dict | None, settings_obj, today: str) -> dict:
    """Ответ GET /api/subscription и статусы подписки для bootstrap/profile."""
    profile = profile or {}
    return {
        "active": subscription_active(profile, today),
        "until": profile.get("sub_until") or None,
        "ai_active": ai_active(profile, today),
        "ai_until": profile.get("ai_until") or None,
        "ai_enabled": effective_ai(profile, today),
        "base_price_rub": int(settings_obj.base_price_rub),
        "base_price_stars": int(settings_obj.base_price_stars),
        "ai_price_rub": int(settings_obj.ai_price_rub),
        "ai_price_stars": int(settings_obj.ai_price_stars),
        "period_days": int(settings_obj.sub_period_days),
        "trial_days": int(settings_obj.trial_days),
        "enforced": gate_enabled(settings_obj),
    }


class ApiError(Exception):
    """Ошибка API с HTTP-статусом и машиночитаемым кодом."""

    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status = int(status)
        self.code = code
        self.message = message or _HTTP_ERRORS.get(self.status, ("error", "Ошибка"))[1]


# --- JSON-ответы ----------------------------------------------------------------

def json_ok(data=None, status: int = 200) -> web.Response:
    payload = json.dumps({"ok": True, "data": data}, ensure_ascii=False)
    return web.Response(
        text=payload,
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


def json_error(status: int, code: str, message: str | None = None) -> web.Response:
    body: dict = {"ok": False, "error": code}
    if message:
        body["message"] = message
    return web.Response(
        text=json.dumps(body, ensure_ascii=False),
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


# --- платежи Telegram Stars ------------------------------------------------------

def invoice_product(settings_obj, kind: str) -> dict:
    """Описание продукта для Bot API: title, description, price_stars, price_rub."""
    kind = str(kind or "").strip().lower()
    days = max(int(getattr(settings_obj, "sub_period_days", 30) or 30), 1)
    if kind == "base":
        return {
            "kind": "base",
            "title": "Vita Ratio — подписка",
            "description": f"Доступ к боту и мини-приложению Vita Ratio на {days} дн.",
            "price_stars": int(settings_obj.base_price_stars),
            "price_rub": int(settings_obj.base_price_rub),
            "period_days": days,
        }
    if kind == "ai":
        return {
            "kind": "ai",
            "title": "Vita Ratio — ИИ-разбор",
            "description": f"ИИ-разбор заметок и отчётов Vita Ratio на {days} дн.",
            "price_stars": int(settings_obj.ai_price_stars),
            "price_rub": int(settings_obj.ai_price_rub),
            "period_days": days,
        }
    raise ApiError(400, "bad_request", "Поле «kind» должно быть base или ai")


async def create_invoice_link(settings_obj, user_id: int, kind: str) -> dict:
    """Создаёт ссылку на оплату через Bot API ``createInvoiceLink`` (XTR, рекуррентно).

    Возвращает ``{"invoice_url", "kind", "price_stars", "price_rub", "period_days"}``.
    Ошибки Bot API/сети — ``502 invoice_failed`` (CONTRACT §23).
    """
    product = invoice_product(settings_obj, kind)
    token = (getattr(settings_obj, "bot_token", "") or "").strip()
    if not token:
        raise ApiError(502, "invoice_failed", "no bot token")
    uid = int(user_id)
    body = {
        "title": product["title"],
        "description": product["description"],
        "payload": f"{product['kind']}:{uid}",
        "currency": "XTR",
        "prices": [{"label": product["title"], "amount": product["price_stars"]}],
        "subscription_period": product["period_days"] * 86400,
    }
    url = INVOICE_API_URL.format(token=token)
    status = 0
    payload = None
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body) as response:
                status = int(response.status)
                try:
                    payload = await response.json(content_type=None)
                except Exception:  # noqa: BLE001 — не-JSON ответ Bot API
                    payload = None
    except Exception as exc:  # noqa: BLE001 — сеть/таймаут/прокси: 502 по контракту
        log.warning("invoice: Bot API недоступен (%s: %s)", type(exc).__name__, str(exc)[:200])
        raise ApiError(502, "invoice_failed", f"Bot API: {type(exc).__name__}") from None
    if status >= 400 or not isinstance(payload, dict) or not payload.get("ok"):
        description = ""
        if isinstance(payload, dict):
            description = str(payload.get("description") or "")[:200]
        log.warning("invoice: Bot API ответил %s: %s", status, description or payload)
        raise ApiError(502, "invoice_failed", description or "Bot API error")
    invoice_url = payload.get("result")
    if not invoice_url:
        raise ApiError(502, "invoice_failed", "Bot API не вернул ссылку на оплату")
    return {
        "invoice_url": str(invoice_url),
        "kind": product["kind"],
        "price_stars": product["price_stars"],
        "price_rub": product["price_rub"],
        "period_days": product["period_days"],
    }


@web.middleware
async def subscription_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Гейт платного режима: без активной base-подписки — 402 на ``/api/*``.

    Включается только при ``subscription_enforced`` и вне dev. Статика и ``/``
    не проверяются, чтобы paywall-экран мини-приложения открывался.
    """
    settings_obj = _settings(request)
    if not gate_enabled(settings_obj):
        return await handler(request)
    path = request.path
    if not path.startswith("/api/") or path in SUBSCRIPTION_FREE_PATHS:
        return await handler(request)
    user = auth.authenticate(request, settings_obj)
    profile = store.get_profile(_conn(request), user["id"])
    today = calc.local_today(settings_obj.timezone)
    error = subscription_gate(settings_obj, path, profile, today)
    if error is not None:
        raise error
    return await handler(request)


@web.middleware
async def error_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Превращает исключения и HTTP-ошибки роутера в JSON-envelope."""
    try:
        return await handler(request)
    except ApiError as exc:
        return json_error(exc.status, exc.code, exc.message)
    except auth.AuthError as exc:
        return json_error(401, exc.code, exc.message)
    except web.HTTPException as exc:
        if exc.status < 400:
            raise
        code, message = _HTTP_ERRORS.get(exc.status, ("error", "Ошибка"))
        return json_error(exc.status, code, message)
    except Exception:  # noqa: BLE001 — последний рубеж, наружу только JSON
        log.exception("Необработанная ошибка: %s %s", request.method, request.path)
        return json_error(500, "internal_error", "Внутренняя ошибка сервера")


# --- чтение запроса -------------------------------------------------------------

def _settings(request: web.Request):
    return request.app[auth.SETTINGS_KEY]


def _conn(request: web.Request):
    return request.app[auth.CONN_KEY]


def _user(request: web.Request) -> dict:
    return auth.authenticate(request, _settings(request))


async def _body(request: web.Request) -> dict:
    try:
        raw = await request.text()
    except web.HTTPException:
        raise
    except Exception:  # noqa: BLE001 — битое тело/кодировка
        raise ApiError(400, "bad_request", "Не удалось прочитать тело запроса") from None
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "Тело запроса — некорректный JSON") from None
    if not isinstance(payload, dict):
        raise ApiError(400, "bad_request", "Тело запроса должно быть JSON-объектом")
    return payload


def _query(request: web.Request, name: str, default: str = "") -> str:
    value = request.query.get(name)
    return (value if value is not None else default).strip()


def _query_int(request: web.Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw = _query(request, name)
    if not raw:
        return default
    return _int_value(raw, name, minimum, maximum)


# --- валидация ------------------------------------------------------------------

def _bad(message: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, code, message)


def _int_value(value, field: str, minimum: int, maximum: int, code: str = "invalid_value") -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise _bad(f"Поле «{field}» должно быть целым числом") from None
    if not (minimum <= number <= maximum):
        raise ApiError(400, code, f"Поле «{field}» должно быть от {minimum} до {maximum}")
    return number


def _float_value(value, field: str, minimum: float, maximum: float, code: str = "invalid_value") -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _bad(f"Поле «{field}» должно быть числом") from None
    if not math.isfinite(number) or not (minimum <= number <= maximum):
        raise ApiError(400, code, f"Поле «{field}» должно быть от {minimum} до {maximum}")
    return number


def _time_value(value, field: str = "time") -> str:
    if value is None or str(value).strip() == "":
        raise _bad(f"Не указано время в поле «{field}»")
    try:
        minutes = calc.time_to_minutes(str(value))
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_time", f"Неверное время в поле «{field}»: {value}") from None
    return calc.minutes_to_time(minutes)


def _date_value(value, field: str = "date") -> str | None:
    """ISO-дата из тела запроса; None — поле отсутствует."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()[:10]
    try:
        return date_cls.fromisoformat(text).isoformat()
    except ValueError:
        raise ApiError(400, "invalid_date", f"Неверная дата в поле «{field}»: {value}") from None


def _query_date(request: web.Request, settings, name: str = "date") -> str:
    raw = _query(request, name)
    if not raw:
        return calc.local_today(settings.timezone)
    parsed = _date_value(raw, name)
    return parsed or calc.local_today(settings.timezone)


def _text_value(value, field: str, maximum: int, default: str = "", required: bool = False) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        if required:
            raise _bad(f"Заполните поле «{field}»")
        return default
    if len(text) > maximum:
        raise _bad(f"Поле «{field}» слишком длинное (до {maximum} символов)")
    return text


def _bool_value(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _color_value(value, field: str = "accent") -> str:
    """Цвет палитры строго #RRGGBB (регистр нормализуем в верхний)."""
    text = str(value or "").strip()
    if not _HEX_COLOR.match(text):
        raise ApiError(400, "invalid_color", f"Цвет «{field}» должен быть в формате #RRGGBB")
    return text.upper()


def _optional_float(value, field: str, minimum: float, maximum: float):
    """Необязательное число: None/пустая строка -> None, иначе валидация диапазона."""
    if value is None or str(value).strip() == "":
        return None
    return _float_value(value, field, minimum, maximum)


def _day_kind_value(value) -> str:
    kind = str(value or "other").strip().lower()
    if kind not in calc.DAY_KIND_LABELS:
        raise ApiError(
            400,
            "invalid_kind",
            "Тип блока должен быть одним из: " + ", ".join(calc.DAY_KIND_LABELS),
        )
    return kind


def _number(value):
    """Число для JSON: целое, если оно целое, иначе с одним знаком."""
    number = float(value or 0)
    if abs(number - round(number)) < 1e-9:
        return int(round(number))
    return round(number, 1)


def _path_id(request: web.Request, name: str) -> int:
    raw = request.match_info.get(name, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(404, "not_found", "Запись не найдена") from None
    if value <= 0:
        raise ApiError(404, "not_found", "Запись не найдена")
    return value


# --- сериализация доменных объектов ---------------------------------------------

def _user_json(user: dict) -> dict:
    return {
        "id": int(user.get("id") or 0),
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
    }


def _profile_json(profile: dict | None, today: str | None = None) -> dict | None:
    if not profile:
        return None
    day = today or calc.local_today()
    return {
        "sex": profile.get("sex"),
        "age": int(profile.get("age") or 0),
        "height_cm": _number(profile.get("height_cm")),
        "weight_kg": _number(profile.get("weight_kg")),
        "activity": profile.get("activity"),
        "goal_rate": round(float(profile.get("goal_rate") or 0), 2),
        "protein_per_kg": round(float(profile.get("protein_per_kg") or 0), 1),
        "sleep_bed": profile.get("sleep_bed"),
        "sleep_wake": profile.get("sleep_wake"),
        "reminders": bool(profile.get("reminders")),
        "ai_enabled": effective_ai(profile, day),
        "sub_until": profile.get("sub_until") or None,
        "ai_until": profile.get("ai_until") or None,
        "timezone": profile.get("timezone"),
        "goal_weight_kg": (
            _number(profile.get("goal_weight_kg"))
            if profile.get("goal_weight_kg") is not None
            else None
        ),
        "goal_date": profile.get("goal_date") or None,
        "theme_accent": profile.get("theme_accent") or THEME_DEFAULTS["accent"],
        "theme_bg": profile.get("theme_bg") or THEME_DEFAULTS["bg"],
        "theme_card": profile.get("theme_card") or THEME_DEFAULTS["card"],
        "updated_at": profile.get("updated_at"),
    }


def _targets_obj(profile: dict) -> calc.Targets:
    return calc.targets(
        profile.get("sex") or "male",
        profile.get("age") if profile.get("age") is not None else 25,
        profile.get("height_cm") if profile.get("height_cm") is not None else 175,
        profile.get("weight_kg") if profile.get("weight_kg") is not None else 70,
        profile.get("activity") or "moderate",
        profile.get("goal_rate") if profile.get("goal_rate") is not None else 0.35,
        profile.get("protein_per_kg") if profile.get("protein_per_kg") is not None else 2.0,
    )


def _targets_json(profile: dict | None) -> dict | None:
    if not profile:
        return None
    return _targets_obj(profile).to_dict()


def _meal_items_json(meal: dict | None) -> list[dict]:
    """Ингредиенты приёма пищи для JSON (старые записи без items -> [])."""
    if not meal:
        return []
    items = meal.get("items")
    if items is None:
        items = store.parse_items(meal.get("items_json"))
    result: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "food_key": str(item.get("food_key") or ""),
                "title": str(item.get("title") or ""),
                "grams": _number(item.get("grams")),
                "kcal": _number(item.get("kcal")),
                "protein": _number(item.get("protein")),
                "fat": _number(item.get("fat")),
                "carbs": _number(item.get("carbs")),
            }
        )
    return result


def _meal_json(meal: dict | None) -> dict | None:
    if not meal:
        return None
    return {
        "id": int(meal["id"]),
        "date": meal["date"],
        "time": meal["time"],
        "title": meal["title"],
        "kcal": _number(meal.get("kcal")),
        "protein": _number(meal.get("protein")),
        "fat": _number(meal.get("fat")),
        "carbs": _number(meal.get("carbs")),
        "grams": _number(meal.get("grams")),
        "food_key": meal.get("food_key") or "",
        "note": meal.get("note") or "",
        "items": _meal_items_json(meal),
    }


def _totals_json(conn, user_id: int, day: str) -> dict:
    totals = store.meal_totals(conn, user_id, day)
    return {field: _number(totals[field]) for field in ("kcal", "protein", "fat", "carbs")}


def _sleep_json(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "date": row["date"],
        "bed_time": row["bed_time"],
        "wake_time": row["wake_time"],
        "duration_h": round(float(row.get("duration_h") or 0), 2),
        "quality": int(row.get("quality") or 0),
        "note": row.get("note") or "",
    }


def _class_json(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "kind": row["kind"],
        "weekday": int(row.get("weekday") or 0),
        "start_time": row["start_time"],
        "duration_min": int(row.get("duration_min") or 0),
        "place": row.get("place") or "",
        "note": row.get("note") or "",
        "active": bool(row.get("active")),
    }


def _weight_json(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "date": row["date"],
        "kg": _number(row.get("kg")),
        "note": row.get("note") or "",
    }


def _note_json(row: dict | None) -> dict | None:
    """Заметка v4 -> JSON: ai_text пустая строка, если разбора ИИ не было."""
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "date": row["date"],
        "text": row.get("text") or "",
        "ai_text": row.get("ai_text") or "",
        "created_at": row.get("created_at"),
    }


def _occurrences_with_status(conn, user_id: int, classes: list[dict], date_from: str, date_to: str) -> list[dict]:
    occurrences = calc.occurrences(classes, date_from, date_to)
    done = store.done_map(conn, user_id, date_from, date_to)
    for item in occurrences:
        item["status"] = done.get((item["class_id"], item["date"]))
    return occurrences


def _weights_json(rows: list[dict]) -> list[dict]:
    return [
        {"date": row["date"], "kg": _number(row["kg"])}
        for row in rows
    ]


def _food_json(item: dict) -> dict:
    """Продукт базы foods -> JSON (КБЖУ на 100 г, unit = «100 г»)."""
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "kcal": _number(item.get("kcal")),
        "protein": _number(item.get("protein")),
        "fat": _number(item.get("fat")),
        "carbs": _number(item.get("carbs")),
        "category": item.get("category"),
        "unit": item.get("unit") or foods.UNIT,
    }


def _theme_json(profile: dict | None) -> dict:
    profile = profile or {}
    return {
        "accent": profile.get("theme_accent") or THEME_DEFAULTS["accent"],
        "bg": profile.get("theme_bg") or THEME_DEFAULTS["bg"],
        "card": profile.get("theme_card") or THEME_DEFAULTS["card"],
    }


def _day_plan_json(row: dict | None) -> dict | None:
    if not row:
        return None
    kind = str(row.get("kind") or "other")
    return {
        "id": int(row["id"]),
        "date": row["date"],
        "time": row["time"],
        "title": row["title"],
        "kind": kind,
        "kind_label": calc.DAY_KIND_LABELS.get(kind, "Другое"),
        "duration_min": int(row.get("duration_min") or 0),
        "note": row.get("note") or "",
        "done": bool(row.get("done")),
    }


def _goal_payload(
    conn,
    user_id: int,
    profile: dict | None,
    day: str,
    trend_kg_per_week: float | None = None,
) -> dict:
    """Прогресс к цели по весу + статус (calc.goal_status) по тренду веса."""
    if not profile:
        goal = calc.goal_progress(None)
        goal["status"] = calc.goal_status(goal, None, 0.35)
        return goal
    weights = store.goal_weights(conn, user_id, profile, days=60, date_to=day)
    goal = calc.goal_progress(
        profile.get("goal_weight_kg"),
        profile.get("goal_date"),
        weights["start_weight_kg"],
        weights["current_weight_kg"],
        today=day,
    )
    goal_rate = profile.get("goal_rate")
    goal["status"] = calc.goal_status(
        goal,
        trend_kg_per_week,
        float(goal_rate) if goal_rate is not None else 0.35,
    )
    return goal


def _day_payload(conn, user_id: int, profile: dict | None, day: str) -> dict:
    """План дня: сохранённые блоки, рекомендации из calc.day_suggestions и итоги."""
    rows = store.list_day_plans(conn, user_id, day)
    items = [_day_plan_json(row) for row in rows]
    suggestions: list[dict] = []
    if profile:
        classes = store.list_classes(conn, user_id)
        classes_today = _occurrences_with_status(conn, user_id, classes, day, day)
        slots = calc.meal_plan(
            profile.get("sleep_bed") or "23:00",
            profile.get("sleep_wake") or "07:00",
            classes_today,
            _targets_obj(profile).kcal,
        )
        existing = {(item["time"], item["title"]) for item in items}
        suggestions = [
            suggestion
            for suggestion in calc.day_suggestions(profile, slots, classes_today)
            if (suggestion.get("time"), suggestion.get("title")) not in existing
        ]
    return {
        "date": day,
        "items": items,
        "suggestions": suggestions,
        "summary": calc.day_summary(items),
    }


# --- статистика -----------------------------------------------------------------

def _avg(values: list[float], digits: int = 0):
    if not values:
        return None
    result = sum(values) / len(values)
    return round(result) if digits == 0 else round(result, digits)


def _stats_payload(
    conn,
    user_id: int,
    profile: dict | None,
    classes: list[dict],
    date_to: str,
    days: int,
) -> dict:
    end = date_cls.fromisoformat(date_to)
    start = end - timedelta(days=max(int(days), 1) - 1)
    date_from = start.isoformat()

    day_rows = store.stats_days(conn, user_id, date_from, date_to)
    done = store.done_map(conn, user_id, date_from, date_to)
    occurrences = calc.occurrences(classes, date_from, date_to)
    by_date: dict[str, list[dict]] = {}
    for occurrence in occurrences:
        by_date.setdefault(occurrence["date"], []).append(occurrence)
    for row in day_rows:
        day_occurrences = by_date.get(row["date"], [])
        row["classes_planned"] = len(day_occurrences)
        row["classes_done"] = sum(
            1 for occ in day_occurrences if done.get((occ["class_id"], occ["date"])) == "present"
        )

    summary = calc.schedule_summary(occurrences, done)
    targets_obj = _targets_obj(profile) if profile else None
    goal_kcal = targets_obj.kcal if targets_obj else None
    sleep_goal = (
        calc.duration_between(profile.get("sleep_bed") or "23:00", profile.get("sleep_wake") or "07:00")
        if profile
        else 8.0
    )

    with_food = [row for row in day_rows if row["meals_count"]]
    with_sleep = [row for row in day_rows if row["sleep_h"] is not None]
    avg_kcal = _avg([row["kcal"] for row in with_food], 0)
    avg_protein = _avg([row["protein"] for row in with_food], 0)
    avg_fat = _avg([row["fat"] for row in with_food], 0)
    avg_carbs = _avg([row["carbs"] for row in with_food], 0)
    avg_sleep = _avg([row["sleep_h"] for row in with_sleep], 1)
    avg_quality = _avg([row["quality"] for row in with_sleep if row["quality"] is not None], 1)

    adherence = {
        "days_total": len(day_rows),
        "days_with_food": len(with_food),
        "days_with_sleep": len(with_sleep),
        "kcal_pct": round(avg_kcal / goal_kcal * 100) if (avg_kcal and goal_kcal) else None,
        "protein_pct": round(avg_protein / targets_obj.protein * 100) if (avg_protein and targets_obj) else None,
        "sleep_pct": round(avg_sleep / sleep_goal * 100) if (avg_sleep and sleep_goal) else None,
        "classes_total": summary["total"],
        "classes_done": summary["done"],
        "classes_pct": round(summary["done"] / summary["total"] * 100) if summary["total"] else None,
    }

    return {
        "days": day_rows,
        "avg": {
            "kcal": avg_kcal,
            "protein": avg_protein,
            "fat": avg_fat,
            "carbs": avg_carbs,
            "sleep_h": avg_sleep,
            "quality": avg_quality,
            "goal_kcal": goal_kcal,
        },
        "adherence": adherence,
        "by_kind": summary["by_kind"],
        "trend_kg_per_week": store.weight_trend(conn, user_id, days=14, date_to=date_to),
    }


def _week_payload(stats: dict) -> dict:
    days = stats["days"][-7:]
    with_food = [row for row in days if row["meals_count"]]
    avg_kcal = round(sum(row["kcal"] for row in with_food) / len(with_food)) if with_food else 0
    return {
        "days": [
            {
                "date": row["date"],
                "kcal": _number(row["kcal"]),
                "protein": _number(row["protein"]),
                "sleep_h": row["sleep_h"],
            }
            for row in days
        ],
        "avg_kcal": avg_kcal,
    }


def _checkin_json(row: dict | None) -> dict | None:
    """Недельный чек-ин -> JSON (None, если чек-ина нет)."""
    if not row:
        return None
    return {
        "id": int(row.get("id") or 0),
        "week_start": row.get("week_start"),
        "weight_kg": _number(row.get("weight_kg")),
        "feeling": row.get("feeling") or "ok",
        "note": row.get("note") or "",
        "created_at": row.get("created_at"),
    }


def _weekly_payload(conn, user_id: int, profile: dict | None, day: str) -> dict:
    """Недельный чек-ин: due = есть профиль и нет чек-ина за текущую ISO-неделю."""
    bounds = calc.week_bounds(day)
    checkin = store.get_weekly_checkin(conn, user_id, bounds["week_start"])
    return {
        "due": bool(profile) and checkin is None,
        "week_start": bounds["week_start"],
        "week_end": bounds["week_end"],
        "last": _checkin_json(store.last_weekly_checkin(conn, user_id)),
    }


def _plan_notes(profile: dict, classes_today: list[dict]) -> list[str]:
    window = calc.sleep_window(profile.get("sleep_bed") or "23:00", profile.get("sleep_wake") or "07:00")
    notes = [
        "Последний приём — до {end}, чтобы заснуть в {bed}.".format(
            end=window["eating_window"]["end"], bed=window["bed"]
        )
    ]
    gym = next((item for item in classes_today if item.get("kind") == "gym"), None)
    if gym is not None:
        notes.append(
            "Тренировка в {start}: перекус за {minutes} мин, приём белка после."
            .format(start=gym.get("start_time", ""), minutes=calc.PRE_WORKOUT_MIN)
        )
    duration = float(window["duration_h"])
    if duration < 7.0:
        notes.append(
            "Спишь {hours:.1f} ч — набор массы замедлится, добавь {minutes} мин сна."
            .format(hours=duration, minutes=int(round((7.0 - duration) * 60)))
        )
    elif duration > 9.5:
        notes.append(
            "Спишь {hours:.1f} ч — много; проверь качество сна и режим.".format(hours=duration)
        )
    else:
        notes.append("Окно сна {hours:.1f} ч — норма для набора массы.".format(hours=duration))
    return notes[:3]


# --- профиль --------------------------------------------------------------------

_PROFILE_REQUIRED = ("sex", "age", "height_cm", "weight_kg", "activity")


def _profile_payload(payload: dict, settings, existing: dict | None) -> dict:
    """Валидирует тело PUT /api/profile; недостающее берёт из текущего профиля."""
    existing = existing or {}
    for field in _PROFILE_REQUIRED:
        if field not in payload and field not in existing:
            raise _bad(f"Не хватает обязательного поля «{field}»")

    def pick(field, default=None):
        if field in payload and payload[field] is not None:
            return payload[field]
        if field in existing and existing[field] is not None:
            return existing[field]
        return default

    sex = str(pick("sex") or "").strip().lower()
    if sex not in ("male", "female"):
        raise ApiError(400, "invalid_sex", "Пол должен быть «male» или «female»")

    activity = str(pick("activity") or "").strip().lower()
    if activity not in calc.ACTIVITY:
        raise ApiError(
            400,
            "invalid_activity",
            "Активность должна быть одной из: " + ", ".join(calc.ACTIVITY),
        )

    result = {
        "sex": sex,
        "age": _int_value(pick("age"), "age", 10, 100),
        "height_cm": _float_value(pick("height_cm"), "height_cm", 100, 250),
        "weight_kg": _float_value(pick("weight_kg"), "weight_kg", 25, 400),
        "activity": activity,
        "goal_rate": _float_value(pick("goal_rate", 0.35), "goal_rate", 0.0, 1.5),
        "protein_per_kg": _float_value(pick("protein_per_kg", 2.0), "protein_per_kg", 1.0, 4.0),
        "sleep_bed": _time_value(pick("sleep_bed", "23:00"), "sleep_bed"),
        "sleep_wake": _time_value(pick("sleep_wake", "07:00"), "sleep_wake"),
        "reminders": _bool_value(pick("reminders", True), True),
        "timezone": _text_value(
            pick("timezone", settings.timezone), "timezone", 64, default=settings.timezone
        )
        or settings.timezone,
    }

    # Цель по весу: явный null в теле — сброс цели, отсутствие поля — «не менять».
    if "goal_weight_kg" in payload:
        result["goal_weight_kg"] = _optional_float(
            payload.get("goal_weight_kg"), "goal_weight_kg", 30, 300
        )
    else:
        result["goal_weight_kg"] = existing.get("goal_weight_kg") or None
    if "goal_date" in payload:
        result["goal_date"] = _date_value(payload.get("goal_date"), "goal_date")
    else:
        result["goal_date"] = existing.get("goal_date") or None

    # Палитра: hex-цвета, иначе 400 invalid_color.
    for field, key in (
        ("theme_accent", "accent"),
        ("theme_bg", "bg"),
        ("theme_card", "card"),
    ):
        if field in payload:
            result[field] = _color_value(payload.get(field), field)
        else:
            result[field] = str(existing.get(field) or THEME_DEFAULTS[key])
    return result


async def health(request: web.Request) -> web.Response:
    settings = _settings(request)
    provider = (os.environ.get("AI_PROVIDER") or "").strip().lower() or "pollinations"
    model = (os.environ.get("AI_MODEL") or "").strip() or None
    return json_ok({
        "status": "ok",
        "version": __version__,
        "env": settings.app_env,
        "ai": {"provider": provider, "model": model, "key_set": bool(os.environ.get("AI_API_KEY"))},
    })


async def get_profile(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    profile = store.get_profile(_conn(request), user["id"])
    today = calc.local_today(settings.timezone)
    return json_ok({
        "profile": _profile_json(profile, today),
        "targets": _targets_json(profile),
        "subscription": _subscription_json(profile, settings, today),
    })


async def put_profile(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    existing = store.get_profile(conn, user["id"])
    data = _profile_payload(payload, settings, existing)
    profile = store.upsert_profile(conn, user["id"], data)
    today = calc.local_today(settings.timezone)
    if existing is None:
        # Новый профиль получает триал (CONTRACT §22): sub_until = today + TRIAL_DAYS.
        store.ensure_trial(conn, user["id"], settings.trial_days, today=today)
        profile = store.get_profile(conn, user["id"]) or profile
    targets = _targets_obj(profile).to_dict()
    if existing is None:
        # Первый профиль = онбординг завершён: поздравительное сообщение в чат.
        try:
            task = asyncio.create_task(
                notify.notify_registration(settings, user["id"], user.get("first_name"), targets)
            )
            task.add_done_callback(_log_notify_result)
        except RuntimeError:  # нет running loop (например, в тестах)
            pass
    return json_ok({
        "profile": _profile_json(profile, today),
        "targets": targets,
        "subscription": _subscription_json(profile, settings, today),
    })


def _log_notify_result(task) -> None:
    try:
        task.result()
    except Exception as exc:  # pragma: no cover - защита от необработанных исключений
        log.warning("notify task failed: %s", exc)


# --- приёмы пищи ----------------------------------------------------------------

async def get_meals(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    day = _query_date(request, settings)
    meals = [_meal_json(row) for row in store.list_meals(conn, user["id"], day)]
    return json_ok({"date": day, "meals": meals, "totals": _totals_json(conn, user["id"], day)})


def _meal_items_value(payload: dict) -> list[dict] | None:
    """Разбирает ``items[]`` (v3): food_id/title + grams -> КБЖУ порции по базе foods."""
    raw = payload.get("items")
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise _bad("Список ингредиентов «items» не может быть пустым")
    portions: list[dict] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise _bad(f"Ингредиент №{index} должен быть объектом")
        grams_raw = entry.get("grams")
        grams = 100.0
        if grams_raw is not None and str(grams_raw).strip() != "":
            grams = _float_value(grams_raw, f"grams (ингредиент №{index})", 0, 5000)
        food_id = str(entry.get("food_id") or "").strip()
        if food_id:
            food = foods.find_by_id(food_id)
            if food is None:
                raise ApiError(400, "food_not_found", f"Не нашёл: {food_id}")
        else:
            name = _text_value(
                entry.get("title") or entry.get("name"),
                f"title (ингредиент №{index})",
                200,
                required=True,
            )
            food = foods.best_match(name)
            if food is None:
                raise ApiError(400, "food_not_found", f"Не нашёл: {name}")
        portions.append(foods.macros_for_grams(food, grams))
    return portions


async def post_meal(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)

    day = _date_value(payload.get("date"), "date") or calc.local_today(settings.timezone)
    now = calc.local_now(settings.timezone)
    if payload.get("time") is None or str(payload.get("time")).strip() == "":
        time_value = f"{now.hour:02d}:{now.minute:02d}"
    else:
        time_value = _time_value(payload.get("time"), "time")
    note = _text_value(payload.get("note"), "note", 500)

    # v3: несколько ингредиентов за раз — КБЖУ считает база продуктов.
    portions = _meal_items_value(payload)
    if portions is not None:
        totals = calc.meal_items_totals(portions)
        title = " + ".join(portion["title"] for portion in portions)
        meal = store.add_meal(
            conn,
            user["id"],
            day,
            time_value,
            title,
            kcal=totals["kcal"],
            protein=totals["protein"],
            fat=totals["fat"],
            carbs=totals["carbs"],
            note=note,
            grams=totals["grams"],
            food_key=portions[0]["food_key"] if len(portions) == 1 else "",
            items=portions,
        )
        return json_ok({"meal": _meal_json(meal), "totals": _totals_json(conn, user["id"], day)})

    # Режим автоКБЖУ: указаны граммы и/или food_id — состав считает база продуктов.
    food_id = str(payload.get("food_id") or "").strip()
    grams_raw = payload.get("grams")
    has_grams = grams_raw is not None and str(grams_raw).strip() != ""
    if has_grams or food_id:
        grams = _float_value(grams_raw, "grams", 0, 5000) if has_grams else 100.0
        if food_id:
            food = foods.find_by_id(food_id)
            if food is None:
                raise ApiError(
                    400,
                    "food_not_found",
                    f"Продукт «{food_id}» не найден в базе — уточни название",
                )
        else:
            title = _text_value(payload.get("title"), "title", 200, required=True)
            food = foods.best_match(title)
            if food is None:
                raise ApiError(
                    400,
                    "food_not_found",
                    f"Не нашёл продукт «{title}» — уточни название",
                )
        portion = foods.macros_for_grams(food, grams)
        meal = store.add_meal(
            conn,
            user["id"],
            day,
            time_value,
            portion["title"],
            kcal=portion["kcal"],
            protein=portion["protein"],
            fat=portion["fat"],
            carbs=portion["carbs"],
            note=note,
            grams=portion["grams"],
            food_key=portion["food_key"],
        )
        return json_ok({"meal": _meal_json(meal), "totals": _totals_json(conn, user["id"], day)})

    # Старый ручной режим: КБЖУ вводит пользователь.
    title = _text_value(payload.get("title"), "title", 200, required=True)
    meal = store.add_meal(
        conn,
        user["id"],
        day,
        time_value,
        title,
        kcal=_float_value(payload.get("kcal", 0), "kcal", 0, 20000),
        protein=_float_value(payload.get("protein", 0), "protein", 0, 2000),
        fat=_float_value(payload.get("fat", 0), "fat", 0, 2000),
        carbs=_float_value(payload.get("carbs", 0), "carbs", 0, 2000),
        note=note,
    )
    return json_ok({"meal": _meal_json(meal), "totals": _totals_json(conn, user["id"], day)})


async def delete_meal(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    meal_id = _path_id(request, "meal_id")
    if not store.delete_meal(conn, user["id"], meal_id):
        raise ApiError(404, "not_found", "Приём пищи не найден")
    return json_ok({"ok": True})


# --- продукты (автоКБЖУ) --------------------------------------------------------

async def get_foods(request: web.Request) -> web.Response:
    """Поиск по базе продуктов; пустой q — первые 12 позиций базы."""
    _user(request)
    query = _query(request, "q")
    if query:
        limit = _query_int(request, "limit", 8, 1, 50)
        items = [_food_json(item) for item in foods.search(query, limit=limit)]
    else:
        limit = _query_int(request, "limit", 12, 1, 50)
        items = [_food_json(item) for item in foods.all_items()[:limit]]
    return json_ok({"items": items})


# --- палитра --------------------------------------------------------------------

async def get_theme(request: web.Request) -> web.Response:
    user = _user(request)
    profile = store.get_profile(_conn(request), user["id"])
    data = _theme_json(profile)
    data["presets"] = [dict(preset) for preset in THEME_PRESETS]
    return json_ok(data)


async def put_theme(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    payload = await _body(request)
    profile = store.get_profile(conn, user["id"])
    updates: dict = {}
    for field, key in (
        ("theme_accent", "accent"),
        ("theme_bg", "bg"),
        ("theme_card", "card"),
    ):
        if key in payload:
            updates[field] = _color_value(payload.get(key), key)
    if not updates:
        return json_ok(_theme_json(profile))
    profile = store.upsert_profile(conn, user["id"], updates)
    return json_ok(_theme_json(profile))


# --- план дня -------------------------------------------------------------------

def _day_time_value(payload: dict, settings) -> str:
    if payload.get("time") is None or str(payload.get("time")).strip() == "":
        now = calc.local_now(settings.timezone)
        return f"{now.hour:02d}:{now.minute:02d}"
    return _time_value(payload.get("time"), "time")


async def get_day(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    day = _query_date(request, settings)
    profile = store.get_profile(conn, user["id"])
    return json_ok(_day_payload(conn, user["id"], profile, day))


async def post_day(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    day = _date_value(payload.get("date"), "date") or calc.local_today(settings.timezone)
    row = store.add_day_plan(
        conn,
        user["id"],
        day,
        _day_time_value(payload, settings),
        _text_value(payload.get("title"), "title", 200, required=True),
        kind=_day_kind_value(payload.get("kind")),
        duration_min=_int_value(payload.get("duration_min", 60), "duration_min", 5, 720),
        note=_text_value(payload.get("note"), "note", 500),
        done=_bool_value(payload.get("done"), False),
    )
    return json_ok({"item": _day_plan_json(row)})


async def put_day(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    item_id = _path_id(request, "item_id")
    if store.get_day_plan(conn, user["id"], item_id) is None:
        raise ApiError(404, "not_found", "Блок плана не найден")
    payload = await _body(request)
    patch: dict = {}
    if "date" in payload:
        dated = _date_value(payload.get("date"), "date")
        if dated is None:
            raise _bad("Поле «date» не может быть пустым")
        patch["date"] = dated
    if "time" in payload:
        patch["time"] = _time_value(payload.get("time"), "time")
    if "title" in payload:
        patch["title"] = _text_value(payload.get("title"), "title", 200, required=True)
    if "kind" in payload:
        patch["kind"] = _day_kind_value(payload.get("kind"))
    if "duration_min" in payload:
        patch["duration_min"] = _int_value(payload.get("duration_min"), "duration_min", 5, 720)
    if "note" in payload:
        patch["note"] = _text_value(payload.get("note"), "note", 500)
    if "done" in payload:
        patch["done"] = 1 if _bool_value(payload.get("done"), False) else 0
    row = store.update_day_plan(conn, user["id"], item_id, patch)
    if row is None:
        raise ApiError(404, "not_found", "Блок плана не найден")
    return json_ok({"item": _day_plan_json(row)})


async def delete_day(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    item_id = _path_id(request, "item_id")
    if not store.delete_day_plan(conn, user["id"], item_id):
        raise ApiError(404, "not_found", "Блок плана не найден")
    return json_ok({})


async def post_day_done(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    item_id = _path_id(request, "item_id")
    payload = await _body(request)
    done = _bool_value(payload.get("done"), True)
    row = store.set_day_done(conn, user["id"], item_id, done)
    if row is None:
        raise ApiError(404, "not_found", "Блок плана не найден")
    return json_ok({"item": _day_plan_json(row)})


# --- сон -----------------------------------------------------------------------

def _sleep_goal_h(profile: dict | None) -> float:
    if not profile:
        return 8.0
    bed = profile.get("sleep_bed") or "23:00"
    wake = profile.get("sleep_wake") or "07:00"
    try:
        return calc.duration_between(bed, wake)
    except ValueError:
        return 8.0


async def get_sleep(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    day = _query_date(request, settings)
    profile = store.get_profile(conn, user["id"])
    sleep = store.get_sleep(conn, user["id"], day)
    week = store.sleep_week(conn, user["id"], day, days=7)
    week_json = [_sleep_json(row) for row in week]
    durations = [float(row["duration_h"]) for row in week_json]
    goal = _sleep_goal_h(profile)
    avg_h = round(sum(durations) / len(durations), 1) if durations else None
    debt_h = round(sum(max(0.0, goal - value) for value in durations), 1) if durations else 0.0
    return json_ok({"sleep": _sleep_json(sleep), "week": week_json, "avg_h": avg_h, "debt_h": debt_h})


async def post_sleep(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    day = _date_value(payload.get("date"), "date") or calc.local_today(settings.timezone)
    bed_time = _time_value(payload.get("bed_time"), "bed_time")
    wake_time = _time_value(payload.get("wake_time"), "wake_time")
    quality = _int_value(payload.get("quality", 3), "quality", 1, 5)
    note = _text_value(payload.get("note"), "note", 500)
    duration = calc.duration_between(bed_time, wake_time)
    sleep = store.upsert_sleep(
        conn, user["id"], day, bed_time, wake_time, duration_h=duration, quality=quality, note=note
    )
    return json_ok({"sleep": _sleep_json(sleep)})


# --- вес -----------------------------------------------------------------------

async def get_weights(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    days = _query_int(request, "days", 60, 1, 365)
    day = calc.local_today(settings.timezone)
    rows = store.list_weights(conn, user["id"], days=days, date_to=day)
    return json_ok(
        {
            "weights": _weights_json(rows),
            "trend_kg_per_week": store.weight_trend(conn, user["id"], days=days, date_to=day),
        }
    )


async def post_weight(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    if payload.get("kg") is None or str(payload.get("kg")).strip() == "":
        raise _bad("Укажите вес в килограммах")
    day = _date_value(payload.get("date"), "date") or calc.local_today(settings.timezone)
    kg = _float_value(payload.get("kg"), "kg", 25, 400)
    note = _text_value(payload.get("note"), "note", 500)
    weight = store.add_weight(conn, user["id"], day, kg, note=note)
    return json_ok(
        {
            "weight": _weight_json(weight),
            "trend_kg_per_week": store.weight_trend(conn, user["id"], days=21, date_to=day),
        }
    )


# --- заметки и ИИ (v4/v5) --------------------------------------------------------

def _ai_enabled(profile: dict | None, today: str) -> bool:
    """Эффективный ИИ: флаг включён и аддон ai оплачен до сегодня (CONTRACT §22)."""
    return effective_ai(profile, today)


async def get_notes(request: web.Request) -> web.Response:
    """Последние заметки (новые сверху) + текущее состояние ИИ-разбора."""
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    limit = _query_int(request, "limit", 30, 1, 100)
    profile = store.get_profile(conn, user["id"])
    today = calc.local_today(settings.timezone)
    return json_ok(
        {
            "notes": [_note_json(row) for row in store.list_notes(conn, user["id"], limit)],
            "ai_enabled": _ai_enabled(profile, today),
        }
    )


async def post_note(request: web.Request) -> web.Response:
    """Сохраняет заметку за сегодня; ИИ-разбор только при оплаченном ai_until."""
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    text = _text_value(payload.get("text"), "text", 2000, required=True)
    profile = store.get_profile(conn, user["id"])
    today = calc.local_today(settings.timezone)
    ai_enabled = _ai_enabled(profile, today)
    # Модель может думать до 20 с — не блокируем event loop.
    await asyncio.to_thread(
        reports.save_note, conn, user["id"], text, today, ai_enabled=ai_enabled
    )
    saved = store.list_notes(conn, user["id"], 1)
    return json_ok(
        {"note": _note_json(saved[0]) if saved else None, "ai_enabled": ai_enabled}
    )


async def put_ai(request: web.Request) -> web.Response:
    """Включает/выключает ИИ-разбор заметок (флаг profiles.ai_enabled).

    В платном режиме включение требует активного аддона ``ai_until``
    (402 ``ai_subscription_required``); выключение доступно всегда.
    """
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise _bad("Поле «enabled» должно быть true или false")
    today = calc.local_today(settings.timezone)
    profile = store.get_profile(conn, user["id"])
    if enabled and gate_enabled(settings) and not ai_active(profile, today):
        raise ApiError(
            402,
            "ai_subscription_required",
            "ИИ +100 ₽/мес — подключите для доступа",
        )
    profile = store.upsert_profile(conn, user["id"], {"ai_enabled": 1 if enabled else 0})
    return json_ok({"ai_enabled": _ai_enabled(profile, today)})


# --- недельный чек-ин -----------------------------------------------------------

def _feeling_value(value) -> str:
    feeling = str(value or "ok").strip().lower()
    if feeling not in store.WEEKLY_FEELINGS:
        raise ApiError(400, "invalid_feeling", "Самочувствие должно быть good, ok или bad")
    return feeling


async def get_weekly(request: web.Request) -> web.Response:
    """Состояние недельного чек-ина: надо ли заполнять и когда был прошлый."""
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    day = _query_date(request, settings)
    profile = store.get_profile(conn, user["id"])
    payload = _weekly_payload(conn, user["id"], profile, day)
    weights = store.goal_weights(conn, user["id"], profile, days=60, date_to=day)
    payload["current_weight_kg"] = weights["current_weight_kg"]
    payload["goal_rate"] = (
        round(float(profile.get("goal_rate") or 0.35), 2) if profile else None
    )
    return json_ok(payload)


async def post_weekly(request: web.Request) -> web.Response:
    """Upsert чек-ина за текущую ISO-неделю + взвешивание на сегодня."""
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    if payload.get("weight_kg") is None or str(payload.get("weight_kg")).strip() == "":
        raise _bad("Укажите вес в килограммах")
    weight = _float_value(payload.get("weight_kg"), "weight_kg", 30, 300)
    feeling = _feeling_value(payload.get("feeling"))
    note = _text_value(payload.get("note"), "note", 500)
    day = _date_value(payload.get("date"), "date") or calc.local_today(settings.timezone)
    bounds = calc.week_bounds(day)

    checkin = store.upsert_weekly_checkin(
        conn, user["id"], bounds["week_start"], weight, feeling=feeling, note=note
    )
    store.add_weight(conn, user["id"], day, weight, note=note)

    recalc = _bool_value(payload.get("recalc"), False)
    profile = store.get_profile(conn, user["id"])
    if profile and recalc:
        profile = store.upsert_profile(conn, user["id"], {"weight_kg": weight})

    trend = store.weight_trend(conn, user["id"], days=14, date_to=day)
    return json_ok(
        {
            "checkin": _checkin_json(checkin),
            "profile": _profile_json(profile, day),
            "targets": _targets_json(profile),
            "goal": _goal_payload(conn, user["id"], profile, day, trend),
        }
    )


# --- занятия -------------------------------------------------------------------

def _class_create_payload(payload: dict) -> dict:
    if payload.get("active") is not None:
        active = 1 if _bool_value(payload.get("active"), True) else 0
    else:
        active = 1
    return {
        "title": _text_value(payload.get("title"), "title", 200, required=True),
        "kind": _kind_value(payload.get("kind")),
        "weekday": _int_value(payload.get("weekday"), "weekday", 0, 6, code="invalid_weekday"),
        "start_time": _time_value(payload.get("start_time"), "start_time"),
        "duration_min": _int_value(payload.get("duration_min"), "duration_min", 15, 480),
        "place": _text_value(payload.get("place"), "place", 300),
        "note": _text_value(payload.get("note"), "note", 500),
        "active": active,
    }


def _kind_value(value) -> str:
    kind = str(value or "").strip().lower()
    if kind not in calc.KIND_LABELS:
        raise ApiError(400, "invalid_kind", "Тип занятия должен быть gym, study или other")
    return kind


def _class_patch_payload(payload: dict) -> dict:
    data: dict = {}
    if "title" in payload:
        data["title"] = _text_value(payload.get("title"), "title", 200, required=True)
    if "kind" in payload:
        data["kind"] = _kind_value(payload.get("kind"))
    if "weekday" in payload:
        data["weekday"] = _int_value(payload.get("weekday"), "weekday", 0, 6, code="invalid_weekday")
    if "start_time" in payload:
        data["start_time"] = _time_value(payload.get("start_time"), "start_time")
    if "duration_min" in payload:
        data["duration_min"] = _int_value(payload.get("duration_min"), "duration_min", 15, 480)
    if "place" in payload:
        data["place"] = _text_value(payload.get("place"), "place", 300)
    if "note" in payload:
        data["note"] = _text_value(payload.get("note"), "note", 500)
    if "active" in payload:
        data["active"] = 1 if _bool_value(payload.get("active"), True) else 0
    return data


async def get_classes(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    classes = store.list_classes(conn, user["id"])
    return json_ok(
        {
            "classes": [_class_json(row) for row in classes],
            "week_load_min": store.week_load_min(conn, user["id"]),
        }
    )


async def post_class(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    payload = await _body(request)
    data = _class_create_payload(payload)
    row = store.create_class(conn, user["id"], **data)
    return json_ok({"class": _class_json(row)})


async def put_class(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    class_id = _path_id(request, "class_id")
    if store.get_class(conn, user["id"], class_id) is None:
        raise ApiError(404, "not_found", "Занятие не найдено")
    payload = await _body(request)
    data = _class_patch_payload(payload)
    row = store.update_class(conn, user["id"], class_id, data)
    if row is None:
        raise ApiError(404, "not_found", "Занятие не найдено")
    return json_ok({"class": _class_json(row)})


async def delete_class(request: web.Request) -> web.Response:
    user = _user(request)
    conn = _conn(request)
    class_id = _path_id(request, "class_id")
    if not store.delete_class(conn, user["id"], class_id):
        raise ApiError(404, "not_found", "Занятие не найдено")
    return json_ok({})


async def get_schedule(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    today = calc.local_today(settings.timezone)
    default_from = (date_cls.fromisoformat(today) - timedelta(days=7)).isoformat()
    default_to = (date_cls.fromisoformat(today) + timedelta(days=7)).isoformat()
    date_from = _query(request, "from")
    date_to = _query(request, "to")
    date_from = _date_value(date_from, "from") or default_from
    date_to = _date_value(date_to, "to") or default_to
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    classes = store.list_classes(conn, user["id"])
    occurrences = _occurrences_with_status(conn, user["id"], classes, date_from, date_to)
    summary = calc.schedule_summary(occurrences)
    return json_ok({"occurrences": occurrences, "summary": summary})


async def post_class_done(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    class_id = _path_id(request, "class_id")
    class_row = store.get_class(conn, user["id"], class_id)
    if class_row is None:
        raise ApiError(404, "not_found", "Занятие не найдено")
    payload = await _body(request)
    status = str(payload.get("status") or "present").strip().lower()
    if status not in ("present", "absent", "moved"):
        raise ApiError(400, "invalid_status", "Статус должен быть present, absent или moved")
    day = _date_value(payload.get("date"), "date") or calc.local_today(settings.timezone)
    note = _text_value(payload.get("note"), "note", 500)
    row = store.mark_class_done(conn, user["id"], class_id, day, status=status, note=note)
    occurrence = {
        "class_id": int(class_row["id"]),
        "title": class_row["title"],
        "kind": class_row["kind"],
        "date": day,
        "start_time": class_row["start_time"],
        "duration_min": int(class_row["duration_min"]),
        "place": class_row["place"],
        "note": class_row["note"],
        "status": (row or {}).get("status", status),
    }
    return json_ok({"occurrence": occurrence})


# --- статистика и план ----------------------------------------------------------

async def get_stats(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    days = _query_int(request, "days", 14, 1, 365)
    profile = store.get_profile(conn, user["id"])
    classes = store.list_classes(conn, user["id"])
    today = calc.local_today(settings.timezone)
    return json_ok(_stats_payload(conn, user["id"], profile, classes, today, days))


async def get_plan(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    day = _query_date(request, settings)
    profile = store.get_profile(conn, user["id"])
    classes = store.list_classes(conn, user["id"])
    classes_today = _occurrences_with_status(conn, user["id"], classes, day, day)

    if not profile:
        return json_ok(
            {
                "slots": [],
                "sleep_window": calc.sleep_window(),
                "notes": ["Заполните профиль, чтобы получить план питания."],
                "targets": None,
            }
        )

    targets_obj = _targets_obj(profile)
    slots = calc.meal_plan(
        profile.get("sleep_bed") or "23:00",
        profile.get("sleep_wake") or "07:00",
        classes_today,
        targets_obj.kcal,
    )
    return json_ok(
        {
            "slots": slots,
            "sleep_window": calc.sleep_window(
                profile.get("sleep_bed") or "23:00", profile.get("sleep_wake") or "07:00"
            ),
            "notes": _plan_notes(profile, classes_today),
            "targets": targets_obj.to_dict(),
        }
    )


# --- bootstrap -----------------------------------------------------------------

async def get_bootstrap(request: web.Request) -> web.Response:
    user = _user(request)
    settings = _settings(request)
    conn = _conn(request)
    day = _query_date(request, settings)
    profile = store.get_profile(conn, user["id"])
    classes = store.list_classes(conn, user["id"])
    now = calc.local_now(settings.timezone)

    meals = [_meal_json(row) for row in store.list_meals(conn, user["id"], day)]
    totals = _totals_json(conn, user["id"], day)
    sleep_row = store.get_sleep(conn, user["id"], day)
    classes_today = _occurrences_with_status(conn, user["id"], classes, day, day)
    next_classes = calc.next_occurrences(classes, now, limit=5)
    weights = _weights_json(store.list_weights(conn, user["id"], days=60, date_to=day))
    stats = _stats_payload(conn, user["id"], profile, classes, day, 14)

    data = {
        "user": _user_json(user),
        "profile": None,
        "targets": None,
        "ai_enabled": _ai_enabled(profile, day),
        "sub_until": (profile or {}).get("sub_until") or None,
        "ai_until": (profile or {}).get("ai_until") or None,
        "subscription": _subscription_json(profile, settings, day),
        "goal": _goal_payload(
            conn, user["id"], profile, day, stats["trend_kg_per_week"]
        ),
        "theme": _theme_json(profile),
        "weekly": _weekly_payload(conn, user["id"], profile, day),
        "day": _day_payload(conn, user["id"], profile, day),
        "today": {
            "date": day,
            **totals,
            "meals_count": len(meals),
            "goal_kcal": None,
        },
        "meals": meals,
        "sleep": _sleep_json(sleep_row),
        "plan": [],
        "classes_today": classes_today,
        "next_classes": next_classes,
        "weights": weights,
        "stats": {
            "days": stats["days"],
            "avg": stats["avg"],
            "trend_kg_per_week": stats["trend_kg_per_week"],
        },
        "insights": [],
        "week": _week_payload(stats),
    }

    if profile:
        targets_obj = _targets_obj(profile)
        classes_done = sum(
            1 for item in classes_today if item.get("status") == "present"
        )
        sleep_h = sleep_row["duration_h"] if sleep_row else None
        data["profile"] = _profile_json(profile, day)
        data["targets"] = targets_obj.to_dict()
        data["today"] = {
            "date": day,
            **totals,
            "meals_count": len(meals),
            "goal_kcal": targets_obj.kcal,
            "water_ml": targets_obj.water_ml,
        }
        data["plan"] = calc.meal_plan(
            profile.get("sleep_bed") or "23:00",
            profile.get("sleep_wake") or "07:00",
            classes_today,
            targets_obj.kcal,
        )
        data["insights"] = calc.day_insights(
            profile,
            {
                "kcal": totals["kcal"],
                "protein": totals["protein"],
                "sleep_h": sleep_h,
                "classes_done": classes_done,
                "classes_planned": len(classes_today),
            },
            targets_obj,
        )
    return json_ok(data)


# --- статика мини-приложения ----------------------------------------------------

def _serve_file(path: Path) -> web.StreamResponse:
    if not path.is_file():
        raise ApiError(404, "not_found", "Файл не найден")
    return web.FileResponse(path, headers={"Cache-Control": "no-cache"})


async def index(request: web.Request) -> web.Response:
    settings = _settings(request)
    return _serve_file(settings.webapp_dir / "index.html")


async def static_file(request: web.Request) -> web.Response:
    settings = _settings(request)
    name = request.match_info.get("name", "")
    filename = Path(name).name
    if not filename or filename != name or filename.startswith("."):
        raise ApiError(404, "not_found", "Файл не найден")
    if Path(filename).suffix.lower() not in STATIC_SUFFIXES:
        raise ApiError(404, "not_found", "Файл не найден")
    return _serve_file(settings.webapp_dir / filename)


# --- подписка и оплата (v5, CONTRACT §23) ---------------------------------------

async def get_subscription(request: web.Request) -> web.Response:
    """GET /api/subscription — статусы base/ai, даты, цены и режим оплаты."""
    user = _user(request)
    settings_obj = _settings(request)
    conn = _conn(request)
    profile = store.get_profile(conn, user["id"])
    today = calc.local_today(settings_obj.timezone)
    return json_ok(_subscription_json(profile, settings_obj, today))


async def post_pay_invoice(request: web.Request) -> web.Response:
    """POST /api/pay/invoice {"kind":"base"|"ai"} — ссылка на оплату.

    Если настроен рублёвый эквайринг (``PAY_PROVIDER=yookassa|robokassa`` и
    ключи), создаётся счёт провайдера и возвращается его ``invoice_url``.
    Иначе — прежний счёт Telegram Stars (``createInvoiceLink``).
    """
    user = _user(request)
    settings_obj = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in ("base", "ai"):
        raise _bad("Поле «kind» должно быть base или ai")
    if kind == "ai":
        profile = store.get_profile(conn, user["id"])
        today = calc.local_today(settings_obj.timezone)
        if not subscription_active(profile, today):
            raise ApiError(409, "base_required", "Сначала оформите подписку 250 ₽/мес")
    if payments.provided(settings_obj):
        try:
            data = _create_rub_invoice(conn, settings_obj, user["id"], kind)
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001 — сеть/БД/провайдер: единый код 502
            log.exception(
                "invoice: провайдер %s не создал счёт", getattr(settings_obj, "pay_provider", "?")
            )
            raise ApiError(
                502, "invoice_failed", f"{type(exc).__name__}: {str(exc)[:120]}"
            ) from None
        return json_ok(data)
    return json_ok(await create_invoice_link(settings_obj, user["id"], kind))


# --- рублёвый эквайринг: счета, вебхуки, refresh (v6) ---------------------------

def _rub_invoice_json(invoice_url, provider: str, kind: str, price_rub, settings_obj) -> dict:
    """Единый ответ POST /api/pay/invoice для рублёвого пути."""
    return {
        "invoice_url": str(invoice_url),
        "provider": str(provider),
        "kind": str(kind),
        "price_rub": int(price_rub),
        "price_stars": 0,
        "period_days": int(getattr(settings_obj, "sub_period_days", 30) or 30),
    }


def _create_rub_invoice(conn, settings_obj, user_id: int, kind: str) -> dict:
    """Создаёт счёт у настроенного провайдера (ЮKassa/Robokassa).

    ЮKassa: платёж создаётся сразу, его id — ``external_id`` счёта.
    Robokassa: сначала строка с ``tmp-<uuid>`` (нужен id для подписи), затем
    подписанная ссылка с InvId = id строки, после чего ``external_id``
    переписывается на ``str(id)``.
    """
    provider = str(getattr(settings_obj, "pay_provider", "") or "").strip().lower()
    amount = int(payments.rub_price(settings_obj, kind))
    if provider == "robokassa":
        row_id = store.create_invoice(
            conn,
            user_id,
            kind,
            "robokassa",
            f"tmp-{uuid.uuid4()}",
            amount,
            payload="robokassa",
        )
        created = payments.robokassa_url(settings_obj, user_id, kind, invoice_id=row_id)
        invoice_url = str(created.get("invoice_url") or "")
        if not invoice_url:
            raise RuntimeError("robokassa: пустая ссылка на оплату")
        store.update_invoice_external(conn, row_id, str(row_id))
        return _rub_invoice_json(
            invoice_url, "robokassa", kind, created.get("price_rub", amount), settings_obj
        )
    created = payments.create_yookassa(settings_obj, user_id, kind)
    invoice_url = str(created.get("invoice_url") or "")
    external_id = str(created.get("external_id") or "").strip()
    if not invoice_url or not external_id:
        raise RuntimeError("yookassa: нет invoice_url/external_id")
    store.create_invoice(
        conn,
        user_id,
        kind,
        "yookassa",
        external_id,
        created.get("price_rub", amount),
        payload="yookassa",
    )
    return _rub_invoice_json(
        invoice_url, "yookassa", kind, created.get("price_rub", amount), settings_obj
    )


def _payment_until(conn, settings_obj, user_id: int, kind: str) -> str:
    """Новая дата подписки: max(сегодня, текущая) + period_days."""
    today = date_cls.fromisoformat(calc.local_today(settings_obj.timezone))
    field = "ai_until" if kind == "ai" else "sub_until"
    current_raw = (store.get_subscription(conn, user_id) or {}).get(field)
    current = None
    if current_raw:
        try:
            current = date_cls.fromisoformat(str(current_raw)[:10])
        except ValueError:
            current = None
    base = max(today, current) if current is not None else today
    period = max(int(getattr(settings_obj, "sub_period_days", 30) or 30), 0)
    return (base + timedelta(days=period)).isoformat()


def _activate_provider_payment(
    conn,
    settings_obj,
    user_id: int,
    kind: str,
    charge_id: str,
    amount,
    currency: str = "RUB",
    payload: str = "",
) -> dict:
    """Пишет платёж и продлевает подписку (идемпотентно по ``charge_id``).

    Возвращает ``{"ok", "duplicate", "user_id", "kind", "until", "error"}``.
    Повторная доставка вебхука не продлевает подписку второй раз.
    """
    uid = int(user_id or 0)
    normalized = str(kind or "").strip().lower()
    charge = str(charge_id or "").strip()
    if uid <= 0 or normalized not in store.PAYMENT_KINDS or not charge:
        log.warning(
            "activate: некорректный платёж uid=%s kind=%r charge=%r", uid, kind, charge
        )
        return {
            "ok": False, "duplicate": False, "user_id": uid,
            "kind": normalized, "until": None, "error": "bad_payload",
        }
    try:
        amount_int = int(float(amount or 0))
    except (TypeError, ValueError):
        amount_int = 0
    store.upsert_user(conn, uid)
    if store.get_profile(conn, uid) is None:
        # Профиля ещё нет (оплата до онбординга) — создаём, чтобы было куда
        # записать sub_until/ai_until; платёж не теряется.
        store.upsert_profile(conn, uid, {})
    inserted = store.add_payment(
        conn, uid, normalized, charge, amount_int, currency, payload
    )
    if not inserted:
        log.info(
            "activate: платёж %s уже учтён (user_id=%s kind=%s) — без продления",
            charge, uid, normalized,
        )
        return {
            "ok": True, "duplicate": True, "user_id": uid,
            "kind": normalized, "until": None, "error": "",
        }
    until = _payment_until(conn, settings_obj, uid, normalized)
    field = "ai_until" if normalized == "ai" else "sub_until"
    store.set_subscription(conn, uid, **{field: until})
    if normalized == "ai":
        store.upsert_profile(conn, uid, {"ai_enabled": 1})
    log.info(
        "activate: user_id=%s kind=%s until=%s charge=%s amount=%s %s",
        uid, normalized, until, charge, amount_int, currency,
    )
    return {
        "ok": True, "duplicate": False, "user_id": uid,
        "kind": normalized, "until": until, "error": "",
    }


async def post_pay_yookassa(request: web.Request) -> web.Response:
    """POST /api/pay/yookassa — вебхук ЮKassa (без initData, всегда 200).

    Тело: ``{"event": "payment.succeeded", "object": {"id": "<payment_id>"}}``.
    Подлинность проверяется через API ЮKassa (``verify_yookassa``).
    """
    settings_obj = _settings(request)
    conn = _conn(request)
    try:
        payload = await _body(request)
    except (ApiError, web.HTTPException):
        payload = {}
    event = str(payload.get("event") or "").strip()
    obj = payload.get("object")
    obj = obj if isinstance(obj, dict) else {}
    payment_id = str(obj.get("id") or "").strip()
    if event != "payment.succeeded" or not payment_id:
        log.info("yookassa webhook: событие %r id=%r пропущено", event, payment_id)
        return web.json_response({"ok": True})
    try:
        verified = payments.verify_yookassa(settings_obj, payment_id)
    except Exception:  # noqa: BLE001 — провайдеру всегда 200
        log.exception("yookassa webhook: ошибка проверки платежа %s", payment_id)
        return web.json_response({"ok": True})
    if not verified:
        log.warning("yookassa webhook: платёж %s не подтверждён", payment_id)
        return web.json_response({"ok": True})

    uid = int(verified.get("user_id") or 0)
    kind = str(verified.get("kind") or "").strip().lower()
    charge_id = str(verified.get("charge_id") or payment_id)
    try:
        amount = int(float(verified.get("amount") or 0))
    except (TypeError, ValueError):
        amount = 0

    invoice = store.get_invoice_by_external(conn, payment_id)
    if invoice is None and uid > 0 and kind in store.PAYMENT_KINDS:
        # Счёт потерялся/создан не через API — восстанавливаем задним числом.
        try:
            store.upsert_user(conn, uid)
            store.create_invoice(
                conn,
                uid,
                kind,
                "yookassa",
                payment_id,
                amount or payments.rub_price(settings_obj, kind),
                payload="yookassa",
            )
            log.info("yookassa webhook: счёт %s создан задним числом", payment_id)
        except Exception:  # noqa: BLE001 — гонка/повтор: счёт мог уже появиться
            log.exception("yookassa webhook: не удалось создать счёт %s", payment_id)
        invoice = store.get_invoice_by_external(conn, payment_id)
    if invoice is not None:
        uid = int(invoice.get("user_id") or 0)
        kind = str(invoice.get("kind") or "").strip().lower()
        if not amount:
            try:
                amount = int(float(invoice.get("amount_rub") or 0))
            except (TypeError, ValueError):
                amount = 0

    try:
        _activate_provider_payment(
            conn, settings_obj, uid, kind, charge_id, amount, "RUB", "yookassa"
        )
        store.mark_invoice(conn, payment_id, "succeeded")
    except Exception:  # noqa: BLE001 — ЮKassa не должна получать 500 и ретраить
        log.exception("yookassa webhook: не удалось активировать платёж %s", payment_id)
    return web.json_response({"ok": True})


async def post_pay_robokassa_result(request: web.Request) -> web.Response:
    """POST /api/pay/robokassa/result — ResultURL Robokassa (form-urlencoded).

    Проверяет MD5-подпись (``verify_robokassa``), активирует счёт и отвечает
    ``text/plain`` строкой ``OK{InvId}`` (требование Robokassa).
    """
    settings_obj = _settings(request)
    conn = _conn(request)
    try:
        form = await request.post()
    except Exception:  # noqa: BLE001 — битая форма: провайдер получит 400
        log.exception("robokassa result: не удалось разобрать форму")
        return web.Response(text="bad request", status=400, content_type="text/plain")
    out_sum = str(form.get("OutSum") or "").strip()
    inv_id = str(form.get("InvId") or "").strip()
    signature = str(form.get("SignatureValue") or "").strip()
    invoice_id = payments.verify_robokassa(settings_obj, out_sum, inv_id, signature)
    if invoice_id is None:
        log.warning(
            "robokassa result: неверная подпись InvId=%r OutSum=%r", inv_id, out_sum
        )
        return web.Response(text="bad signature", status=400, content_type="text/plain")
    invoice = store.get_invoice_by_external(conn, str(invoice_id))
    if invoice is None:
        log.warning("robokassa result: счёт InvId=%s не найден", invoice_id)
        return web.Response(text="invoice not found", status=400, content_type="text/plain")
    try:
        amount = int(float(invoice.get("amount_rub") or 0))
    except (TypeError, ValueError):
        amount = 0
    try:
        _activate_provider_payment(
            conn,
            settings_obj,
            invoice.get("user_id"),
            invoice.get("kind"),
            f"robokassa:{invoice_id}",
            amount,
            "RUB",
            "robokassa",
        )
        store.mark_invoice(conn, str(invoice_id), "succeeded")
    except Exception:  # noqa: BLE001 — 500 заставит Robokassa повторить вебхук
        log.exception("robokassa result: не удалось активировать InvId=%s", invoice_id)
        return web.Response(text="error", status=500, content_type="text/plain")
    return web.Response(text=f"OK{inv_id}", content_type="text/plain")


async def get_pay_robokassa_success(request: web.Request) -> web.Response:
    """GET /api/pay/robokassa/success — страница «спасибо» после оплаты."""
    return web.Response(
        text=(
            "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            "<title>Vita Ratio — оплата</title></head><body>"
            "<p>Оплата прошла. Вернитесь в приложение.</p></body></html>"
        ),
        content_type="text/html",
        charset="utf-8",
    )


async def post_pay_refresh(request: web.Request) -> web.Response:
    """POST /api/pay/refresh {"kind": "base"|"ai"} — досрочная проверка счёта.

    ЮKassa подтверждает платёж через API (вебхук может запаздывать), Robokassa —
    только вебхуком, поэтому для неё просто возвращается текущий статус.
    Ответ — как у GET /api/subscription.
    """
    user = _user(request)
    settings_obj = _settings(request)
    conn = _conn(request)
    payload = await _body(request)
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in ("base", "ai"):
        raise _bad("Поле «kind» должно быть base или ai")
    invoice = store.find_pending_invoice(conn, user["id"], kind)
    if invoice is not None and str(invoice.get("provider") or "") == "yookassa":
        external_id = str(invoice.get("external_id") or "").strip()
        verified = None
        if external_id:
            try:
                verified = payments.verify_yookassa(settings_obj, external_id)
            except Exception:  # noqa: BLE001 — refresh не должен падать из-за сети
                log.exception("refresh: ЮKassa не подтвердила счёт %s", external_id)
                verified = None
        if verified:
            try:
                amount = int(float(invoice.get("amount_rub") or 0))
            except (TypeError, ValueError):
                amount = 0
            try:
                _activate_provider_payment(
                    conn,
                    settings_obj,
                    invoice.get("user_id"),
                    invoice.get("kind"),
                    str(verified.get("charge_id") or external_id),
                    amount,
                    "RUB",
                    "yookassa",
                )
                store.mark_invoice(conn, external_id, "succeeded")
            except Exception:  # noqa: BLE001 — статус всё равно вернём
                log.exception("refresh: не удалось активировать счёт %s", external_id)
    profile = store.get_profile(conn, user["id"])
    today = calc.local_today(settings_obj.timezone)
    return json_ok(_subscription_json(profile, settings_obj, today))


# --- сборка приложения ----------------------------------------------------------

async def get_export(request: web.Request) -> web.Response:
    """GET /api/export?period=day|week|month&fmt=png|xlsx|docx — файл-отчёт с разбором ИИ."""
    user = _user(request)
    settings_obj = _settings(request)
    conn = _conn(request)
    period = (request.query.get("period") or "day").lower()
    fmt = (request.query.get("fmt") or "png").lower()
    profile = store.get_profile(conn, user["id"])
    today = calc.local_today(settings_obj.timezone)
    use_llm = effective_ai(profile, today)
    try:
        filename, payload = await asyncio.to_thread(
            reports.build, conn, user["id"], period, fmt, use_llm=use_llm)
    except ValueError as exc:
        raise _bad(str(exc))
    content_type = {
        "png": "image/png",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[fmt]
    return web.Response(body=payload, headers={
        "Content-Type": content_type,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    })


def create_app(settings, conn) -> web.Application:
    """Собирает aiohttp-приложение: API, статика webapp и обработчики ошибок."""
    app = web.Application(
        middlewares=[error_middleware, subscription_middleware],
        client_max_size=MAX_BODY_BYTES,
    )
    app[auth.SETTINGS_KEY] = settings
    app[auth.CONN_KEY] = conn

    app.router.add_get("/api/health", health)
    app.router.add_get("/api/bootstrap", get_bootstrap)
    app.router.add_get("/api/subscription", get_subscription)
    app.router.add_post("/api/pay/invoice", post_pay_invoice)
    app.router.add_post("/api/pay/refresh", post_pay_refresh)
    app.router.add_post("/api/pay/yookassa", post_pay_yookassa)
    app.router.add_post("/api/pay/robokassa/result", post_pay_robokassa_result)
    app.router.add_get("/api/pay/robokassa/success", get_pay_robokassa_success)
    app.router.add_get("/api/profile", get_profile)
    app.router.add_put("/api/profile", put_profile)
    app.router.add_get("/api/meals", get_meals)
    app.router.add_post("/api/meals", post_meal)
    app.router.add_delete("/api/meals/{meal_id}", delete_meal)
    app.router.add_get("/api/sleep", get_sleep)
    app.router.add_post("/api/sleep", post_sleep)
    app.router.add_get("/api/weights", get_weights)
    app.router.add_post("/api/weights", post_weight)
    app.router.add_get("/api/weekly", get_weekly)
    app.router.add_post("/api/weekly", post_weekly)
    app.router.add_get("/api/classes", get_classes)
    app.router.add_post("/api/classes", post_class)
    app.router.add_put("/api/classes/{class_id}", put_class)
    app.router.add_delete("/api/classes/{class_id}", delete_class)
    app.router.add_get("/api/schedule", get_schedule)
    app.router.add_post("/api/classes/{class_id}/done", post_class_done)
    app.router.add_get("/api/stats", get_stats)
    app.router.add_get("/api/plan", get_plan)
    app.router.add_get("/api/foods", get_foods)
    app.router.add_get("/api/theme", get_theme)
    app.router.add_put("/api/theme", put_theme)
    app.router.add_get("/api/day", get_day)
    app.router.add_get("/api/export", get_export)
    app.router.add_post("/api/day", post_day)
    app.router.add_put("/api/day/{item_id}", put_day)
    app.router.add_delete("/api/day/{item_id}", delete_day)
    app.router.add_post("/api/day/{item_id}/done", post_day_done)
    app.router.add_get("/api/notes", get_notes)
    app.router.add_post("/api/notes", post_note)
    app.router.add_put("/api/ai", put_ai)

    app.router.add_get("/", index)
    app.router.add_get("/static/{name}", static_file)
    # На случай, если index.html ссылается на ассеты от корня (styles.css, app.js).
    app.router.add_get("/{name}", static_file)
    return app
