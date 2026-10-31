"""Персистентность SQLite между пересборками Render: бэкап в приватный GitHub.

Render Free стирает диск контейнера при каждом деплое/рестарте, поэтому файл
``DB_PATH`` (``data/vita.db``) теряется. Модуль хранит копию базы в приватном
GitHub-репозитории (``DATA_REPO``) через Contents API и восстанавливает её при
старте:

* :func:`restore_db` — скачивает ``db/vita.db.b64`` и атомарно кладёт по
  ``settings.db_path``, но только если локальной непустой базы ещё нет;
* :func:`backup_db` — делает консистентный снимок через SQLite backup API
  (безопасно при WAL) и загружает его в GitHub (с ``sha``, если файл уже есть);
* :func:`backup_loop` — фоновый цикл по таймеру; ошибки только логируются.

Сеть — только ``urllib`` из stdlib, новых зависимостей нет. Публичные функции
не бросают исключений наружу: любая ошибка → запись в лог и ``False``.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .config import settings as load_settings

log = logging.getLogger("vita_ratio.persistence")

API_ROOT = "https://api.github.com"
#: Путь к бэкапу внутри data-репозитория (файл содержит base64 от байтов SQLite).
REMOTE_DB_PATH = "db/vita.db.b64"
SQLITE_HEADER = b"SQLite format 3\x00"
REQUEST_TIMEOUT_SEC = 30.0
USER_AGENT = "vita-ratio-backup/1.0"

#: Снимок не делаем параллельно (таймер и финальный бэкап при остановке).
_BACKUP_LOCK = threading.Lock()
#: Отпечаток файла БД на момент последнего успешного бэкапа (таймерный режим).
_last_backup_fingerprint: tuple[tuple[str, int, int], ...] | None = None


def _configured(settings_obj: Settings) -> bool:
    """Заданы ли ``DATA_REPO`` и ``DATA_TOKEN`` (без них GitHub недоступен)."""
    return bool(str(settings_obj.data_repo or "").strip()) and bool(
        str(settings_obj.data_token or "").strip()
    )


def backup_configured(settings_obj: Settings) -> bool:
    """Нужно ли запускать фоновый бэкап: включён и репозиторий с токеном заданы."""
    return bool(settings_obj.backup_enabled) and _configured(settings_obj)


# --- GitHub Contents API (stdlib urllib) ---------------------------------------


def _api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    settings_obj: Settings | None,
) -> dict[str, Any] | None:
    """Запрос к Contents API. Любая ошибка (в т.ч. 404) → ``None`` и запись в лог."""
    cfg = settings_obj if settings_obj is not None else load_settings()
    repo = str(cfg.data_repo or "").strip().strip("/")
    token = str(cfg.data_token or "").strip()
    if not repo or not token:
        log.debug("GitHub: DATA_REPO/DATA_TOKEN не заданы — запрос %s %s пропущен", method, path)
        return None
    branch = str(cfg.data_branch or "main").strip() or "main"
    url = f"{API_ROOT}/repos/{repo}/contents/{str(path).lstrip('/')}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data: bytes | None = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode({"ref": branch})
    else:
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SEC) as response:
            raw = response.read()
        if not raw:
            return {}
        decoded = json.loads(raw.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {"data": decoded}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            log.info("GitHub: %s %s не найден (404)", method, path)
        else:
            log.warning("GitHub: %s %s -> HTTP %s", method, path, exc.code)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        log.warning("GitHub: %s %s не удался: %s", method, path, exc)
        return None


def api_get(path: str, settings_obj: Settings | None = None) -> dict[str, Any] | None:
    """GET ``/repos/{data_repo}/contents/{path}``; ``None``, если файла нет/ошибка."""
    return _api_request("GET", path, None, settings_obj)


def api_put(
    path: str, payload: dict[str, Any], settings_obj: Settings | None = None
) -> dict[str, Any] | None:
    """PUT ``/repos/{data_repo}/contents/{path}``; ``None`` при ошибке."""
    return _api_request("PUT", path, payload, settings_obj)


# --- восстановление ------------------------------------------------------------


def _decode_remote_content(data: Any) -> bytes | None:
    """Достаёт байты SQLite из ответа Contents API.

    GitHub отдаёт ``content`` как base64 от содержимого файла, а в файле лежит
    ещё один base64 (``*.b64``). Поэтому сначала декодируем обёртку API, затем
    сам файл. Дополнительно принимаем и «одинарный» base64 — так удобнее тестам
    и ручным бэкапам. Результат обязан начинаться с заголовка SQLite.
    """
    if isinstance(data, dict):
        content = data.get("content")
    else:
        content = data
    if not content:
        return None
    raw = "".join(str(content).split())
    if not raw:
        return None
    try:
        first = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError):
        return None
    if first.startswith(SQLITE_HEADER):
        return first
    try:
        text = first.decode("ascii").strip()
        second = base64.b64decode(text, validate=False)
    except (UnicodeDecodeError, binascii.Error, ValueError):
        return None
    return second if second.startswith(SQLITE_HEADER) else None


def _atomic_write(path: Path, payload: bytes) -> None:
    """Пишет файл целиком через временный файл и ``os.replace`` в той же папке."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def restore_db(settings_obj: Settings) -> bool:
    """Восстанавливает БД из GitHub, только если локальной непустой базы нет.

    :returns: ``True`` — база восстановлена; ``False`` — не потребовалось,
        хранилище не настроено или произошла ошибка (с логом).
    """
    try:
        if not _configured(settings_obj) or not settings_obj.backup_enabled:
            log.info(
                "Восстановление БД пропущено: DATA_REPO/DATA_TOKEN не заданы "
                "или BACKUP_ENABLED=0"
            )
            return False
        db_path = Path(settings_obj.db_path)
        try:
            if db_path.exists() and db_path.stat().st_size > 0:
                log.info(
                    "Локальная БД уже есть (%s, %d байт) — восстановление не требуется",
                    db_path,
                    db_path.stat().st_size,
                )
                return False
        except OSError as exc:
            log.warning("Не удалось проверить локальную БД %s: %s", db_path, exc)
            return False

        data = api_get(REMOTE_DB_PATH, settings_obj)
        if not data:
            log.info("Бэкапа %s в GitHub нет — стартуем с пустой БД", REMOTE_DB_PATH)
            return False
        payload = _decode_remote_content(data)
        if not payload:
            log.warning(
                "Бэкап %s повреждён или не является SQLite — восстановление пропущено",
                REMOTE_DB_PATH,
            )
            return False
        _atomic_write(db_path, payload)
        # Старые WAL/SHM от прежнего запуска не должны «наложиться» на восстановленную БД.
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(OSError):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)
        log.info(
            "БД восстановлена из GitHub: %s (%d байт, sha=%s)",
            db_path,
            len(payload),
            str(data.get("sha") if isinstance(data, dict) else "—"),
        )
        return True
    except Exception:  # noqa: BLE001 — восстановление не должно ронять приложение
        log.exception("Восстановление БД из GitHub не удалось")
        return False


# --- бэкап ---------------------------------------------------------------------


def _fingerprint(db_path: Path) -> tuple[tuple[str, int, int], ...] | None:
    """Отпечаток основного файла и WAL: mtime_ns + размер.

    ``-shm`` не учитываем: он меняется от обычных чтений и вызывал бы лишние
    коммиты в GitHub, хотя данные не изменились.
    """
    parts: list[tuple[str, int, int]] = []
    for suffix in ("", "-wal"):
        candidate = Path(f"{db_path}{suffix}")
        try:
            stat = candidate.stat()
        except OSError:
            continue
        parts.append((suffix, stat.st_mtime_ns, stat.st_size))
    return tuple(parts) if parts else None


def _snapshot_bytes(db_path: Path) -> bytes | None:
    """Консистентный снимок БД через ``sqlite3.Connection.backup`` (учитывает WAL)."""
    fd, tmp_name = tempfile.mkstemp(prefix=".vita-backup-", suffix=".db", dir=str(db_path.parent))
    os.close(fd)
    try:
        source = sqlite3.connect(str(db_path), timeout=15.0)
        try:
            destination = sqlite3.connect(tmp_name)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        return Path(tmp_name).read_bytes()
    except (sqlite3.Error, OSError) as exc:
        log.warning("Не удалось сделать снимок БД %s: %s", db_path, exc)
        return None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)


def backup_db(settings_obj: Settings, force: bool = False) -> bool:
    """Загружает снимок БД в GitHub.

    :param force: ``True`` (остановка приложения) — без проверки изменений;
        ``False`` (таймер) — только если файл БД/WAL изменился с прошлого бэкапа.
    :returns: ``True`` — бэкап загружен; ``False`` — пропущен или ошибка.
    """
    global _last_backup_fingerprint
    try:
        db_path = Path(settings_obj.db_path)
        try:
            if not db_path.exists() or db_path.stat().st_size <= 0:
                log.info("Бэкап БД пропущен: файла %s нет или он пуст", db_path)
                return False
        except OSError as exc:
            log.warning("Не удалось проверить БД %s: %s", db_path, exc)
            return False
        if not settings_obj.backup_enabled:
            log.info("Бэкап БД пропущен: BACKUP_ENABLED=0")
            return False
        if not _configured(settings_obj):
            log.info("Бэкап БД пропущен: DATA_REPO/DATA_TOKEN не заданы")
            return False

        fingerprint = _fingerprint(db_path)
        if (
            not force
            and fingerprint is not None
            and fingerprint == _last_backup_fingerprint
        ):
            log.debug("Бэкап БД: изменений с прошлого раза нет — пропуск")
            return False

        if not _BACKUP_LOCK.acquire(blocking=False):
            log.info("Бэкап БД уже выполняется — пропуск")
            return False
        try:
            payload = _snapshot_bytes(db_path)
            if payload is None:
                return False
            try:
                existing = api_get(REMOTE_DB_PATH, settings_obj)
            except Exception:  # noqa: BLE001 — мок/сеть могут бросить
                log.exception("Бэкап: не удалось получить sha файла %s", REMOTE_DB_PATH)
                existing = None
            sha = str((existing or {}).get("sha") or "").strip()
            body: dict[str, Any] = {
                "message": f"backup db {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
                "content": base64.b64encode(payload).decode("ascii"),
                "branch": str(settings_obj.data_branch or "main").strip() or "main",
            }
            if sha:
                body["sha"] = sha
            try:
                result = api_put(REMOTE_DB_PATH, body, settings_obj)
            except Exception:  # noqa: BLE001 — бэкап не должен ронять приложение
                log.exception("Бэкап: не удалось загрузить %s в GitHub", REMOTE_DB_PATH)
                return False
            if result is None:
                log.warning(
                    "Бэкап не загружен: GitHub вернул ошибку (%s/%s)",
                    settings_obj.data_repo,
                    REMOTE_DB_PATH,
                )
                return False
            _last_backup_fingerprint = fingerprint
            log.info(
                "Бэкап БД загружен в %s/%s (%d байт, %s)",
                settings_obj.data_repo,
                REMOTE_DB_PATH,
                len(payload),
                f"sha={sha}" if sha else "новый файл",
            )
            return True
        finally:
            _BACKUP_LOCK.release()
    except Exception:  # noqa: BLE001 — «лучшие усилия»: приложение не падает
        log.exception("Бэкап БД не удался")
        return False


async def backup_loop(
    settings_obj: Settings,
    stop_event: asyncio.Event | None = None,
    interval: float | None = None,
) -> None:
    """Фоновый бэкап: ждёт ``interval`` секунд и сохраняет БД, пока не остановят.

    :param stop_event: если задан, цикл завершается сразу после его установки
        (без ожидания следующего интервала); задача также отменяется через
        ``task.cancel()``.
    :param interval: период в секундах; по умолчанию ``BACKUP_INTERVAL_SEC``.
    """
    try:
        delay = float(interval if interval is not None else settings_obj.backup_interval_sec or 300)
    except (TypeError, ValueError):
        delay = 300.0
    delay = max(0.01, delay)
    log.info(
        "Фоновый бэкап БД запущен: каждые %.0f с -> %s/%s",
        delay,
        settings_obj.data_repo,
        REMOTE_DB_PATH,
    )
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                else:
                    break
            else:
                await asyncio.sleep(delay)
            try:
                await asyncio.to_thread(backup_db, settings_obj, False)
            except Exception:  # noqa: BLE001 — цикл переживает сбой одного бэкапа
                log.exception("Ошибка фонового бэкапа БД")
    except asyncio.CancelledError:
        log.info("Фоновый бэкап БД остановлен")
        raise
    finally:
        log.info("Цикл бэкапа БД завершён")
