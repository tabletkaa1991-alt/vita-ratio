"""Бесплатный доступ к боту/подписке для отдельных людей (CONTRACT §29).

Список задаётся в Render-переменных:
  FREE_ACCESS_IDS=123456789,987654321
  FREE_ACCESS_USERNAMES=amogyss12,levadsf
Username сравнивается без @ и без учёта регистра; ID — как числа.
"""
from __future__ import annotations

from .config import Settings


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
        name = chunk.strip().lstrip("@").lower()
        if name:
            result.add(name)
    return result


def is_free(settings: Settings, user_id: int | None = None, username: str | None = None) -> bool:
    """True, если пользователь в whitelist бесплатного доступа (мусор -> False)."""
    if user_id is not None:
        try:
            if int(user_id) in _ids(settings.free_access_ids):
                return True
        except (TypeError, ValueError):
            pass
    if username:
        name = str(username).lstrip("@").lower()
        if name in _usernames(settings.free_access_usernames):
            return True
    return False


def free_usernames(settings: Settings) -> list[str]:
    """Список ников для отладки/логов (без секретов)."""
    return sorted(_usernames(settings.free_access_usernames))


def free_ids(settings: Settings) -> list[int]:
    return sorted(_ids(settings.free_access_ids))
