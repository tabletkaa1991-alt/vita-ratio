"""Точка входа Vita Ratio: сервер (API + мини-приложение) и/или бот.

    python -m vita_ratio.main all      # сервер + бот (по умолчанию)
    python -m vita_ratio.main server   # только API и веб-приложение
    python -m vita_ratio.main bot      # только Telegram-бот
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys

from aiohttp import web

from . import __version__, db, persistence
from .config import settings


log = logging.getLogger("vita_ratio")

#: Финальный бэкап при остановке не должен задерживать завершение дольше этого.
FINAL_BACKUP_TIMEOUT_SEC = 10.0


async def _restore_database(settings_obj) -> bool:
    """Пробует восстановить БД из GitHub до открытия соединения (ошибки не мешают)."""
    try:
        return await asyncio.to_thread(persistence.restore_db, settings_obj)
    except Exception:  # noqa: BLE001 — старт не должен падать из-за бэкапа
        log.exception("Восстановление БД из GitHub не удалось — продолжаем без него")
        return False


async def _final_backup(settings_obj) -> None:
    """Последний бэкап при остановке: не дольше 10 с, ошибки только в лог."""
    try:
        uploaded = await asyncio.wait_for(
            asyncio.to_thread(persistence.backup_db, settings_obj, True),
            timeout=FINAL_BACKUP_TIMEOUT_SEC,
        )
        log.info("Финальный бэкап БД: %s", "загружен" if uploaded else "пропущен")
    except asyncio.TimeoutError:
        log.warning("Финальный бэкап БД не уложился в %.0f с", FINAL_BACKUP_TIMEOUT_SEC)
    except asyncio.CancelledError:
        log.warning("Финальный бэкап БД прерван остановкой")
    except Exception:  # noqa: BLE001 — остановка не должна падать из-за бэкапа
        log.exception("Финальный бэкап БД не удался")


async def _start_server(settings_obj, conn) -> web.AppRunner:
    from .api import create_app

    app = create_app(settings_obj, conn)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings_obj.app_host, settings_obj.app_port)
    await site.start()
    log.info("Сервер: http://%s:%s (env=%s)", settings_obj.app_host, settings_obj.app_port, settings_obj.app_env)
    log.info("Мини-приложение: %s/?demo=1", settings_obj.app_url.rstrip("/"))
    return runner


async def _run(mode: str) -> None:
    settings_obj = settings()
    # Render Free теряет диск при рестарте: сначала пробуем вернуть БД из GitHub,
    # и только потом открываем соединение — закрывать/переоткрывать не требуется.
    restored = await _restore_database(settings_obj)
    conn = db.connect(settings_obj.db_path)
    db.init_db(conn)
    if restored:
        log.info("БД восстановлена — соединение открыто с восстановленным файлом")

    runner: web.AppRunner | None = None
    tasks: list[asyncio.Task] = []
    backup_task: asyncio.Task | None = None
    try:
        if mode in ("server", "all"):
            try:
                runner = await _start_server(settings_obj, conn)
            except OSError as exc:
                log.error("Не удалось поднять сервер на %s:%s — %s", settings_obj.app_host, settings_obj.app_port, exc)
                if mode == "server":
                    raise SystemExit(1) from exc

        if mode in ("bot", "all"):
            from . import bot as bot_module

            tasks.append(asyncio.create_task(bot_module.run_bot(settings_obj, conn), name="vita-bot"))

        if not tasks and runner is None:
            raise SystemExit("Нечего запускать: выбери server, bot или all")

        if persistence.backup_configured(settings_obj):
            backup_task = asyncio.create_task(
                persistence.backup_loop(settings_obj), name="vita-backup"
            )
        else:
            log.info(
                "Фоновый бэкап БД выключен: задай DATA_REPO и DATA_TOKEN (BACKUP_ENABLED=1)"
            )

        if tasks and runner is not None:
            # Сервер обязан жить, даже если бот завершился (например, пустой BOT_TOKEN).
            await asyncio.gather(*tasks)
            log.warning("Бот остановился — сервер и мини-приложение продолжают работу")
            await asyncio.Event().wait()
        elif tasks:
            await asyncio.gather(*tasks)
        else:
            await asyncio.Event().wait()
    finally:
        if runner is not None:
            await runner.cleanup()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if backup_task is not None:
            backup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await backup_task
            # Лучшие усилия: последний снимок перед тем, как Render убьёт контейнер.
            await _final_backup(settings_obj)
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vita_ratio", description="Vita Ratio — Telegram Mini App для набора массы")
    parser.add_argument("mode", nargs="?", default="all", choices=["all", "server", "bot"])
    parser.add_argument("--version", action="version", version=f"Vita Ratio {__version__}")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        asyncio.run(_run(args.mode))
    except KeyboardInterrupt:
        log.info("Остановлено пользователем")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
