"""Точка входа Vita Ratio: сервер (API + мини-приложение) и/или бот.

    python -m vita_ratio.main all      # сервер + бот (по умолчанию)
    python -m vita_ratio.main server   # только API и веб-приложение
    python -m vita_ratio.main bot      # только Telegram-бот
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from aiohttp import web

from . import __version__, db
from .config import settings


log = logging.getLogger("vita_ratio")


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
    conn = db.connect(settings_obj.db_path)
    db.init_db(conn)

    runner: web.AppRunner | None = None
    tasks: list[asyncio.Task] = []
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
