"""Рублёвый эквайринг для подписок Vita Ratio (ЮKassa / Robokassa).

Самозанятый владелец бота подключает магазин → деньги приходят на карту.
Платежи идут в рублях, подтверждение — вебхуком от провайдера.

Два провайдера:
  * yookassa  — REST API, idempotence-key, подтверждение через GET payment;
  * robokassa — подписанная ссылка (MD5), подтверждение через ResultURL.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
import uuid

from .config import Settings

log = logging.getLogger("vita_ratio.payments")

YOOKASSA_API = "https://api.yookassa.ru/v3/payments"
ROBOKASSA_URL = "https://auth.robokassa.ru/Merchant/Index.aspx"


def rub_price(settings: Settings, kind: str) -> int:
    return settings.base_price_rub if kind == "base" else settings.ai_price_rub


def provided(settings: Settings) -> bool:
    """Настроен ли рублёвый эквайринг (иначе используем Telegram Stars)."""
    if settings.pay_provider == "yookassa":
        return bool(settings.yookassa_shop_id and settings.yookassa_secret)
    if settings.pay_provider == "robokassa":
        return bool(settings.robokassa_login and settings.robokassa_password1)
    return False


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _get_json(url: str, headers: dict, timeout: int = 30) -> dict:
    request = urllib.request.Request(url, method="GET", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def create_yookassa(settings: Settings, user_id: int, kind: str) -> dict:
    """Создаёт платёж ЮKassa и возвращает confirmation_url для редиректа."""
    amount = rub_price(settings, kind)
    payload = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"{settings.app_url}/?paid={kind}",
        },
        "description": ("Vita Ratio — подписка на бота (30 дней)" if kind == "base"
                        else "Vita Ratio — ИИ-разбор (30 дней)"),
        "metadata": {"user_id": int(user_id), "kind": kind},
        "save_payment_method": True,
    }
    headers = {
        "Idempotence-Key": str(uuid.uuid4()),
        "Authorization": "Basic " + _basic(settings.yookassa_shop_id, settings.yookassa_secret),
    }
    result = _post_json(YOOKASSA_API, payload, headers)
    confirmation = (result.get("confirmation") or {}).get("confirmation_url")
    if not confirmation:
        raise RuntimeError("yookassa: no confirmation_url in response")
    return {"provider": "yookassa", "external_id": result.get("id", ""),
            "invoice_url": confirmation, "price_rub": amount}


def _basic(login: str, password: str) -> str:
    import base64
    return base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")


def verify_yookassa(settings: Settings, payment_id: str) -> dict | None:
    """Проверяет платёж в API ЮKassa (вебхуки не подписаны). None — если не оплачен/не найден."""
    headers = {"Authorization": "Basic " + _basic(settings.yookassa_shop_id, settings.yookassa_secret)}
    try:
        payment = _get_json(f"{YOOKASSA_API}/{payment_id}", headers)
    except Exception as exc:
        log.warning("yookassa verify failed: %s", exc)
        return None
    if payment.get("status") != "succeeded":
        return None
    metadata = payment.get("metadata") or {}
    return {"user_id": int(metadata.get("user_id") or 0), "kind": metadata.get("kind") or "",
            "charge_id": payment.get("id", ""), "amount": payment.get("amount", {}).get("value", "")}


def robokassa_url(settings: Settings, user_id: int, kind: str, invoice_id: int) -> dict:
    """Подписанная ссылка Robokassa (ResultURL/вебхук — verify_robokassa)."""
    amount = rub_price(settings, kind)
    signature = hashlib.md5(
        f"{settings.robokassa_login}:{amount:.2f}:{invoice_id}:".encode("utf-8")
        + settings.robokassa_password1.encode("utf-8")
    ).hexdigest()
    query = (
        f"?MerchantLogin={urllib.parse.quote(settings.robokassa_login)}"
        f"&OutSum={amount:.2f}&InvId={invoice_id}"
        f"&Description={urllib.parse.quote('Vita Ratio подписка')}"
        f"&SignatureValue={signature}&IsTest=0"
    )
    return {"provider": "robokassa", "external_id": str(invoice_id),
            "invoice_url": ROBOKASSA_URL + query, "price_rub": amount}


def verify_robokassa(settings: Settings, out_sum: str, inv_id: str, signature: str) -> int | None:
    """Проверяет подпись ResultURL → возвращает invoice_id (StrId) или None."""
    try:
        expected = hashlib.md5(
            f"{out_sum}:{inv_id}:".encode("utf-8") + settings.robokassa_password2.encode("utf-8")
        ).hexdigest()
    except Exception:
        return None
    if signature.lower() != expected.lower():
        return None
    try:
        return int(inv_id)
    except ValueError:
        return None
