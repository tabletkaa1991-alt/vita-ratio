"""Настройки приложения: .env + переменные окружения (без внешних зависимостей)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Простой парсер .env: KEY=VALUE, # — комментарий, кавычки снимаются."""
    path = path or ENV_FILE
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _as_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    bot_token: str = ""
    bot_username: str = ""
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    app_url: str = "http://127.0.0.1:8080"
    app_env: str = "dev"
    db_path: Path = ROOT / "data" / "vita.db"
    timezone: str = "Europe/Moscow"
    admin_id: int | None = None
    proxy_url: str = ""
    root: Path = ROOT

    @property
    def webapp_dir(self) -> Path:
        return self.root / "webapp"

    @property
    def is_dev(self) -> bool:
        return self.app_env.strip().lower() not in {"prod", "production"}


def settings(from_env: bool = True) -> Settings:
    """Читает .env, затем переменные окружения (env важнее)."""
    file_values = load_env_file() if from_env else {}

    def get(name: str, default: str = "") -> str:
        if from_env and os.environ.get(name):
            return os.environ[name]
        return file_values.get(name, default)

    db_path = Path(get("DB_PATH", "data/vita.db"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    # Публичный адрес: явный APP_URL, иначе платформенные переменные хостингов.
    render_url = get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    koyeb_domain = get("KOYEB_PUBLIC_DOMAIN", "").strip()
    explicit_url = get("APP_URL", "").strip()
    if explicit_url:
        app_url = explicit_url
    elif render_url:
        app_url = render_url
    elif koyeb_domain:
        app_url = "https://" + koyeb_domain
    else:
        app_url = "http://127.0.0.1:8080"
    app_url = app_url.rstrip("/") or "http://127.0.0.1:8080"

    # Порт: APP_PORT, иначе PORT (Render/Koyeb/Fly подставляют свой), иначе 8080.
    port_raw = get("APP_PORT", "").strip() or get("PORT", "").strip() or "8080"

    admin_raw = get("ADMIN_ID", "").strip()
    return Settings(
        bot_token=get("BOT_TOKEN", "").strip(),
        bot_username=get("BOT_USERNAME", "").strip(),
        app_host=get("APP_HOST", "0.0.0.0").strip() or "0.0.0.0",
        app_port=_as_int(port_raw, 8080),
        app_url=app_url,
        app_env=get("APP_ENV", "dev").strip() or "dev",
        db_path=db_path,
        timezone=get("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow",
        admin_id=_as_int(admin_raw, 0) or None,
        proxy_url=get("PROXY_URL", "").strip(),
    )
