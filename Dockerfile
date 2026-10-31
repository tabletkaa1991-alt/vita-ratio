# Vita Ratio: мини-приложение + API + Telegram-бот в одном контейнере.
# Порт берётся из PORT (Render/Koyeb/Fly подставляют свой), локально 8080.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

# DejaVu нужен для PNG-экспорта с кириллицей (Pillow)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY vita_ratio ./vita_ratio
COPY webapp ./webapp
COPY schema.sql ./schema.sql

RUN mkdir -p /app/data \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8080'), timeout=3)"]

CMD ["python", "-m", "vita_ratio.main", "all"]
