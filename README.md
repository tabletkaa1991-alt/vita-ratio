# Vita Ratio — Telegram Mini App для набора массы

Проект состоит из двух частей, которые живут в одном процессе (или запускаются отдельно):

- **веб-сервер** (aiohttp): REST API `/api/*` + мини-приложение в `webapp/`;
- **Telegram-бот** (aiogram 3.x): команды, кнопка «Открыть Vita Ratio» и напоминания.

Данные — локальный SQLite (`data/vita.db`), профили раздельные по Telegram ID.
Мини-приложение: дневник еды по КБЖУ, сон и окно питания, универсальное расписание
(зал/учёба/секции), вес и прогресс, цели под набор массы.

## Что умеет

**Мини-приложение** (открывается кнопкой в боте; 5 экранов — «Сегодня», «Еда»,
«Сон», «Расписание», «Прогресс»):

- **АвтоКБЖУ по названию**: вводишь только что съел и граммовку — калории и БЖУ
  считаются сами из встроенной базы на 172 продукта (КБЖУ на 100 г, русские синонимы,
  живые подсказки при вводе). Ручной режим КБЖУ тоже остался.
- **Мультиингредиентный приём пищи**: в одном приёме можно добавить несколько продуктов
  (куриная грудка, яйцо, помидоры, макароны…) — у каждой строки своя граммовка и своё КБЖУ,
  под формой считается общий итог.
- **Цель прямо на главном**: целевой вес и дата, шкала заполнения, «осталось N кг» и
  «N дней до даты», редактирование веса/даты в один тап («Изменить цель»), плюс статус
  прогресса: «Идёшь по плану / Опережаешь / Отстаёшь» с подсказкой, что подкрутить.
- **Обязательный недельный чек-ин**: раз в неделю приложение просит ввести вес, самочувствие
  и заметку и по галочке пересчитывает КБЖУ под новый вес.
- **Расписание дня**: планировщик с таймлайном — блоки «еда / тренировка / учёба / сон /
  дела / другое», отметки выполнения, добавление по одному тапу из рекомендаций
  (подъём, приёмы пищи, занятия, отбой). Отдельный сегмент «Неделя» — прежняя сетка занятий.
- **Своя палитра**: 8 готовых тем (лайм, фиолетовый, бирюзовый, розовый, оранжевый, мята,
  синий, графит) + три color-пикера (акцент, фон, карточки); применяется мгновенно и
  сохраняется в профиле.
- Кольцо калорий и макросы, инсайты дня, план приёмов пищи под окно сна и тренировку,
  недельная сетка занятий и посещаемость, график веса со трендом, сон и «долг сна»,
  онбординг-визард при первом входе (ползунок темпа набора с контрастным треком).

**Бот**:

| Команда | Что делает |
|---|---|
| `/start` | приветствие + inline-кнопка «Открыть Vita Ratio» (WebApp), подсказка про онбординг, если профиля нет |
| `/app` | та же кнопка приложения |
| `/today` | калории/БЖУ за сегодня vs цель, сон, ближайшее занятие |
| `/plan` | план приёмов пищи на сегодня с временами и калориями |
| `/classes` | ближайшие 5 занятий |
| `/sleep` | последняя запись сна + окно сна и питания |
| `/targets` | цели по калориям, БЖУ и воде |
| `/help` | список команд |

**Напоминания** (фоновая asyncio-задача, тик 30 секунд) приходят, только если в
профиле включён тумблер «Напоминания» (`profiles.reminders = 1`):

| kind | Когда | Что приходит |
|---|---|---|
| `meal_breakfast`, `meal_lunch`, `meal_snack`, `meal_dinner`, `meal_pre_workout` | за 10 минут до слота `calc.meal_plan` | «Через 10 мин — Завтрак (~765 ккал)…» |
| `sleep` | за 30 минут до `sleep_bed` | напоминание об отбое |
| `morning` | в течение 60 минут после `sleep_wake` | утренняя сводка: цели на день |

Повторных отправок нет: факт отправки пишется в таблицу `reminder_log(user_id, date, kind)`
с UNIQUE-ключом. Пользователи без профиля и без напоминаний не затрагиваются.
Заблокировавшие бота помечаются в памяти и пропускаются до перезапуска.

## Скриншоты

Живые скриншоты приложения (эмуляция телефона 390×844, тёмная тема, демо-данные из
`scripts/seed-demo.py`) лежат в `docs/screenshots/`:

| Файл | Экран |
|---|---|
| `01-today-goal.png` | «Сегодня»: кольцо калорий + карточка «Цель» (75 кг, 29%, 90 дней) |
| `02-today-day-plan.png` | «Сегодня»: карточка «Расписание дня» с отметками выполнения |
| `03-food.png` | «Еда»: приёмы пищи с граммовками и автоКБЖУ |
| `04-food-automacros.png` | форма «Что съел»: подсказки продуктов и граммы |
| `05-sleep.png` | «Сон»: запись, качество, синхронизация с окном питания, график |
| `06-schedule-day.png` | «Расписание» → «День»: таймлайн плана и отметки |
| `07-schedule-week.png` | «Расписание» → «Неделя»: сетка занятий и посещаемость |
| `08-progress-palette.png` | «Прогресс»: цель по весу и палитра оформления (8 тем + пикеры) |
| `09-onboarding.png` | онбординг, шаг 1 |
| `10-goal-status.png` | «Сегодня»: цель со шкалой и статусом «Идёшь по плану» |
| `11-goal-editor.png` | «Сегодня»: редактирование цели прямо в карточке |
| `12-weekly-checkin.png` | обязательный недельный чек-ин (вес, самочувствие, пересчёт КБЖУ) |
| `13-meal-multi.png` | приём пищи из нескольких ингредиентов с граммовками и превью |
| `14-onboarding-rate.png` | онбординг, шаг 2: светлый ползунок темпа набора |
| `15-food-ingredients.png` | «Еда»: состав приёма (ингредиенты с граммовками) |

## Структура проекта

```
vita-ratio/
  .env / .env.example        # секреты и настройки
  .gitignore                 # .env, data/, __pycache__ и т.п.
  CONTRACT.md                # контракт проекта (источник правды)
  README.md                  # эта инструкция
  requirements.txt           # зависимости для чистой машины
  schema.sql                 # DDL SQLite
  vita_ratio/
    __init__.py              # версия
    config.py                # чтение .env -> dataclass Settings
    db.py                    # connect() + init_db()
    calc.py                  # вся доменная математика (цели, план, сон, расписание)
    auth.py                  # проверка Telegram initData (API)
    store.py                 # репозитории поверх SQLite (API)
    api.py                   # aiohttp-приложение и REST
    bot.py                   # aiogram-бот и напоминания
    main.py                  # точка входа: all | server | bot
  webapp/
    index.html               # экран мини-приложения
    styles.css
    app.js                   # классический скрипт, без сборки
    telegram-shim.js         # локальный фолбэк Telegram WebApp API
  tests/
    test_calc.py             # доменная математика
    test_auth.py             # initData
    test_api.py              # REST API
    test_bot.py              # команды/напоминания бота (без сети)
    check_webapp.mjs         # node-проверка фронтенда (id, пути, статика)
  scripts/
    _env.ps1                 # общий env: Python, PYTHONPATH, $Root
    start-all.ps1            # супервизор: туннель + сервер + бот (+ автоперезапуск)
    run-all.ps1              # то же, но с логами в консоли
    stop-all.ps1             # остановить весь стек
    install-autostart.ps1    # автозагрузка при входе в Windows (-Remove — убрать)
    run.ps1                  # сервер + бот без туннеля (или только server/bot)
    dev-server.ps1           # только веб-сервер для локальной отладки
    start-bot.ps1            # только бот
    sync-token.ps1           # токен из secrets\vita ratio.txt -> .env
    seed-demo.py             # демо-данные для браузера (?demo=1)
    test.ps1                 # все проверки
  start-hidden.vbs           # тихий запуск start-all.ps1 (для автозагрузки)
  tools/                     # cloudflared.exe (резервный туннель, gitignored)
  .run/                      # логи супервизора, туннеля и приложения (gitignored)
  data/                      # vita.db (создаётся сама, gitignored)
```

## Зависимости

Нужен **Python 3.12**. Внешние БД и сборка фронтенда не нужны: фронтенд — ванильный
JS/CSS, данные — SQLite.

**На этой машине интернета и `pip` нет.** Зависимости (`aiogram 3.31`, `aiohttp 3.14`)
уже лежат в `C:\Users\SPBNB\OneDrive\Документы\deepseek-harness\default-workspace\ton-swap-bot\vendor`.
`scripts/_env.ps1` сам добавляет эту папку (и `vita-ratio\vendor`, если она есть) в
`PYTHONPATH`, поэтому скриптами можно пользоваться без установки пакетов. Python берётся
из bundled-рантайма; переопределить можно переменной `$env:VITA_PYTHON`.

**На чистой машине** (VPS, другой компьютер) dependencies ставятся обычным способом:

```powershell
cd C:\путь\к\vita-ratio
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Linux: source .venv/bin/activate
pip install -r requirements.txt
```

На Linux/macOS/Windows-server `scripts/*.ps1` не нужны — там бот и сервер запускаются
напрямую (`python -m vita_ratio.main all`), см. раздел «Деплой на VPS».

Для `PROXY_URL` (прокси к `api.telegram.org`) нужен отдельный пакет **`aiohttp-socks`**:
в `requirements.txt` его нет, а aiogram без него не умеет прокси вообще (даже `http://`).
Установка: `pip install aiohttp-socks`. Если пакета нет, бот напишет ошибку в лог и
продолжит **без** прокси.

## Токен бота

1. Открой [@BotFather](https://t.me/BotFather) в Telegram.
2. Для нового бота: `/newbot`, задай имя и username — BotFather пришлёт токен.
   Для существующего: `/token` → выбери бота → токен.
3. Положи токен **одной строкой** в файл:

   ```
   C:\Users\SPBNB\secrets\vita ratio.txt
   ```

   (Только токен, без кавычек и подписей. Лишние пробелы по краям обрезаются.)
4. Подтяни токен в `.env`:

   ```powershell
   cd "C:\Users\SPBNB\OneDrive\Документы\deepseek-harness\default-workspace\vita-ratio"
   .\scripts\sync-token.ps1
   ```

   Скрипт найдёт токен вида `123456789:AA...`, заменит/добавит строку `BOT_TOKEN=` в
   `.env` и покажет только первые символы. Коды возврата: `0` — обновлено, `2` — файл
   пуст/не найден, `3` — строка не похожа на токен (ничего не меняет).

   Можно и вручную: `BOT_TOKEN=123456789:AA...` в `.env`.

**Смена бота «на ходу».** Если запущен `scripts\start-all.ps1` (супервизор), ничего
перезапускать вручную не нужно: он каждые 10 секунд смотрит на файл токена, при замене
подтягивает новый `BOT_TOKEN`, через `getMe` узнаёт username, обновляет `BOT_USERNAME` и
перезапускает только приложение (туннель и `APP_URL` не меняются). В `.run\supervisor.log`
появится строка вида `bot token changed -> @vita_ratio_bot, restarting bot`. Так же
переключается и бот, и проверка initData на сервере (она всегда использует текущий токен
из `.env`).

Безопасность:

- `.env` в `.gitignore` — **не коммить токен** и не вставляй его в чаты/скриншоты.
- При утечке: BotFather → `/revoke` (выпустит новый токен), затем повтори шаги 3–4.
- `BOT_USERNAME` не обязателен: он нужен только если хочется фильтровать команды с
  упоминанием бота (`/start@my_bot`); в личном чате достаточно `/start`.

## Настройки `.env`

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `BOT_TOKEN` | пусто | токен бота; **пусто → бот не стартует**, сервер работает |
| `BOT_USERNAME` | пусто | username бота без `@` (необязательно) |
| `APP_HOST` | `0.0.0.0` | адрес веб-сервера (`127.0.0.1`, если стоит reverse-proxy) |
| `APP_PORT` | `8080` | порт веб-сервера |
| `APP_URL` | `http://127.0.0.1:8080` | публичный URL мини-приложения для кнопки в боте; **заполняется автоматически** супервизором (`https://<id>.lhr.life`) |
| `APP_ENV` | `dev` | `dev` разрешает `X-Dev-User` и демо-режим; `prod` — только Telegram initData |
| `DB_PATH` | `data/vita.db` | путь к SQLite (относительно корня проекта) |
| `TIMEZONE` | `Europe/Moscow` | зона по умолчанию (в профиле можно указать свою) |
| `ADMIN_ID` | пусто | зарезервировано, сейчас не используется |
| `PROXY_URL` | пусто | прокси к `api.telegram.org`; требует `aiohttp-socks` |

## Запуск

Открой PowerShell в папке проекта:

```powershell
cd "C:\Users\SPBNB\OneDrive\Документы\deepseek-harness\default-workspace\vita-ratio"
```

Если PowerShell блокирует скрипты, разреши их для текущего процесса:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

| Команда | Что запускает |
|---|---|
| `.\scripts\run-all.ps1` | **основной запуск**: супервизор с публичным HTTPS-туннелем + сервер + бот, логи в консоли |
| `.\scripts\start-all.ps1` | то же в фоне (этот вариант запускает автозагрузка) |
| `.\scripts\stop-all.ps1` | остановить супервизор, сервер с ботом и туннель |
| `.\scripts\install-autostart.ps1` | включить автозагрузку при входе в Windows (`-Remove` — выключить) |
| `.\scripts\run.ps1` | сервер + бот без туннеля (локально; `server`/`bot` — только часть) |
| `.\scripts\dev-server.ps1` | только UI для отладки в браузере: <http://127.0.0.1:8080/?demo=1> |
| `.\scripts\start-bot.ps1` | только бот (`python -m vita_ratio.bot`) |
| `.\scripts\test.ps1` | все проверки: `py_compile`, unittest, `node --check webapp/app.js` |

Первый запуск сам создаёт `data/vita.db` (`schema.sql` идемпотентен). Остановка —
`.\scripts\stop-all.ps1` (если запускали `start-all.ps1`/автозагрузку) или `Ctrl+C`.

Чтобы в браузере были не пустые экраны, можно залить демо-данные (профиль, еда за 3 дня,
сон, вес, расписание) для пользователя `1` — ровно того, кого использует `?demo=1`:

```powershell
& "C:\Users\SPBNB\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" scripts\seed-demo.py --user 1
```

Скрипт идемпотентен и перезаписывает только демо-записи этого пользователя.

Проверка, что сервер жив (в другом окне PowerShell):

```powershell
Invoke-WebRequest http://127.0.0.1:8080/api/health | Select-Object -ExpandProperty Content
Invoke-WebRequest http://127.0.0.1:8080/api/bootstrap -Headers @{ "X-Dev-User" = "1" } | Select-Object -ExpandProperty Content
```

Проверить только код без запуска сервера:

```powershell
$env:PYTHONPATH = "C:\Users\SPBNB\OneDrive\Документы\deepseek-harness\default-workspace\ton-swap-bot\vendor;C:\Users\SPBNB\OneDrive\Документы\deepseek-harness\default-workspace\vita-ratio"
$py = "C:\Users\SPBNB\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
& $py -m py_compile vita_ratio\bot.py tests\test_bot.py
& $py -m unittest discover -s tests -v
```

## Публичный HTTPS для мини-приложения (уже настроено)

Telegram открывает Mini App **только по публичному `https://`-адресу**. Локальные
`http://127.0.0.1:8080` и `localhost` на телефоне недоступны. Поэтому запуск идёт через
`scripts\start-all.ps1`, который сам поднимает SSH-туннель **localhost.run** и публикует
его адрес в `.env` как `APP_URL`:

```powershell
.\scripts\run-all.ps1          # тот же супервизор, но с живыми логами в консоли
.\scripts\start-all.ps1        # фоновый запуск (используется автозагрузкой)
.\scripts\stop-all.ps1         # остановить всё: супервизор, сервер+бота и туннель
```

Что делает супервизор (`start-all.ps1`):

1. подтягивает токен из `C:\Users\SPBNB\secrets\vita ratio.txt` в `.env`;
2. открывает туннель `ssh -R 80:127.0.0.1:8080 nokey@localhost.run` (порт 22 — работает
   там, где провайдер блокирует QUIC/UDP 7844 и cloudflared);
3. ловит выданный `https://<id>.lhr.life` и записывает его в `.env` (`APP_URL`);
4. запускает `python -m vita_ratio.main all` (веб-сервер + бот);
5. следит за обоими процессами: упал туннель или приложение — перезапускает и обновляет
   `APP_URL` (адреса localhost.run меняются при каждом переподключении, бот при этом
   перезапускается сам, чтобы кнопка вела на актуальный адрес).

Всё пишется в `.run\`: `supervisor.log`, `tunnel.out.log`, `app.out.log`, `app.err.log`.

Автозагрузка при входе в Windows (без прав администратора) уже установлена:

```powershell
.\scripts\install-autostart.ps1        # включить
.\scripts\install-autostart.ps1 -Remove  # выключить
```

После запуска в Telegram: `/start` → кнопка **«Открыть Vita Ratio»** (это `web_app`-кнопка,
она работает только с HTTPS). Первый вход — онбординг: пол/возраст/рост/вес, активность и
темп набора, режим сна. Дальше данные сохраняются по твоему Telegram ID.

Если открыть тот же адрес в обычном браузере (вне Telegram), initData пуст — включится
демо-режим (`?demo=1`), см. «Частые проблемы».

Стабильнее всего — свой домен на VPS (ниже): тогда `APP_URL` не меняется и туннель не нужен.

## Бесплатный хостинг на Render (без карты, 24/7)

**Статус: развёрнуто.** Бот и мини-приложение работают на Render, туннель больше не нужен:

- приложение и API: **https://vita-ratio.onrender.com**
- бот: **@vita_ratio_bot** (long polling внутри того же контейнера)
- код: `https://github.com/tabletkaa1991-alt/vita-ratio` (ветка `main`, 20 файлов, без секретов)
- Render-сервис: `vita-ratio` (Docker, plan free, region frankfurt), деплой по push в `main`
- локальный стек (`start-all.ps1`) остановлен, автозагрузка локальной копии снята — иначе два
  поллера одного токена дают `409 Conflict`;
- **Render Free засыпает через 15 минут без HTTP-запросов**, поэтому на этой машине создана
  задача планировщика `VitaRatioKeepAlive`: каждые 10 минут дёргает `/api/health`
  (`scripts/keepalive-render.bat`). Пока компьютер включён — контейнер не спит; если выключен,
  сервис засыпает и просыпается от первого запроса (открытие мини-аппа или сообщение боту —
  ответ придёт после холодного старта ~30–60 с).
- Данные на free-плане Render хранятся на эфемерном диске: SQLite (`data/vita.db`) переживает
  сон/работу, но **при новом деплое обнуляется**. Для вечного хранения — VPS с доменом (ниже)
  или бесплатный Postgres (Neon/Supabase).

Остальное в этом разделе — как развернуть заново с нуля (если понадобится).

Локальный туннель (localhost.run) остаётся как аварийный вариант для отладки: он бесплатный,
но адрес меняется и зависит от компьютера.

В репозитории уже всё готово: `Dockerfile`, `.dockerignore`, `render.yaml` и `scripts/`.

### 1. Положить код в GitHub (без установки Git)

1. github.com → **New repository** → имя `vita-ratio`, **Private** → Create.
2. На пустой странице репозитория → **uploading an existing file** → перетащи
   **содержимое** `vita-ratio-deploy.zip` (папки `vita_ratio/`, `webapp/`, файлы
   `Dockerfile`, `render.yaml`, `requirements.txt`, `schema.sql`, `README.md`,
   `.dockerignore`) → **Commit changes**.
3. В репозитории **не должно быть** `.env` — токен вводится в панели Render.

### 2. Создать сервис в Render

1. https://render.com → **Get Started** → вход через GitHub.
2. **New → Blueprint** → выбрать репозиторий `vita-ratio` → **Apply**.
3. Render прочитает `render.yaml` и спросит только `BOT_TOKEN` — вставь токен @vita_ratio_bot.
   Остальное уже задано: `BOT_USERNAME=vita_ratio_bot`, `APP_ENV=prod`, `TIMEZONE=Europe/Moscow`;
   `PORT` и `RENDER_EXTERNAL_URL` Render подставляет сам, приложение берёт из них адрес
   мини-приложения для кнопки (менять `APP_URL` вручную не нужно).
4. Дождись сборки (3–5 минут) → сервис получит адрес вида
   `https://vita-ratio-xxxx.onrender.com` → открой бота: `/start` → «Открыть Vita Ratio».

### 3. Не давать Render засыпать (free-план спит через 15 минут)

Бесплатный сервис просыпается от входящего HTTP-запроса. Нужен бесплатный «пинг»:

1. https://cron-job.org → регистрация → **Create cronjob**.
2. URL: `https://vita-ratio-xxxx.onrender.com/api/health`, интервал **каждые 10 минут**, метод GET.
3. Сохранить. Теперь контейнер не спит, бот всегда на связи (750 часов/мес хватает на месяц
   непрерывной работы; если квота кончится — поставь пинг раз в 20 минут, тогда будет
   «сон/пробуждение» с холодным стартом ~50 секунд).

### Важно про данные на free-плане

Диск у Render free эфемерный: SQLite (`data/vita.db`) живёт, пока сервис запущен, но при
**новом деплое** база обнулится. Для личного трекера это обычно приемлемо (деплой — редко),
но если нужна гарантированная сохранность истории, варианты:

- **VPS + домен** (раздел ниже) — база на диске навсегда, тот же Docker-образ;
- бесплатный Postgres (Neon/Supabase) — потребует замены слоя хранения с SQLite на драйвер Postgres.

### Альтернатива: Koyeb Free

Тот же `Dockerfile` и `render.yaml`, только в Koyeb (**Create Service → GitHub → Dockerfile**,
порт 8080, env `BOT_TOKEN`, `APP_ENV=prod`). Koyeb даёт `KOYEB_PUBLIC_DOMAIN` — приложение
подхватит его автоматически (адрес мини-приложения). Засыпает через час, пинг раз в 20–30 мин.

## Деплой на VPS

Пример для Ubuntu/Debian и домена `vita.example.com`.

```bash
# 1) код и зависимости
sudo apt update
sudo apt install -y python3.12 python3.12-venv git
sudo mkdir -p /opt/vita-ratio && sudo chown "$USER" /opt/vita-ratio
git clone <адрес-репозитория> /opt/vita-ratio        # или скопируй папку проекта
cd /opt/vita-ratio
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Создай `.env` рядом с кодом (образец — `.env.example`), минимум:

```
BOT_TOKEN=123456789:AA...
APP_HOST=127.0.0.1        # Caddy стоит на том же сервере
APP_PORT=8080
APP_URL=https://vita.example.com
APP_ENV=prod
DB_PATH=data/vita.db
TIMEZONE=Europe/Moscow
```

**systemd** (автозапуск и перезапуск при падении): `/etc/systemd/system/vita-ratio.service`

```ini
[Unit]
Description=Vita Ratio (API + Telegram bot)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vita
WorkingDirectory=/opt/vita-ratio
ExecStart=/opt/vita-ratio/.venv/bin/python -m vita_ratio.main all
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vita-ratio
systemctl status vita-ratio
journalctl -u vita-ratio -f          # логи, здесь же ошибки Telegram
```

`config.py` сам читает `.env` из корня проекта, поэтому `EnvironmentFile` не обязателен.

**Без systemd (быстро, вручную)** — `screen` или `tmux`:

```bash
screen -S vita
cd /opt/vita-ratio && . .venv/bin/activate && python -m vita_ratio.main all
# отцепиться: Ctrl+A, затем D; вернуться: screen -r vita
```

**Caddy с автоматическим HTTPS** (`/etc/caddy/Caddyfile`):

```
vita.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

```bash
sudo systemctl reload caddy
```

`APP_URL=https://vita.example.com` должен совпадать с доменом из Caddyfile: initData
проверяется по `BOT_TOKEN`, но фронтенд должен открываться именно с этого HTTPS-адреса.

## Частые проблемы

**Бот не отвечает на `/start`, мини-приложение не открывается** — сначала запусти
диагностику (она покажет, что именно лежит и отвечает ли Telegram):

```powershell
.\scripts\diagnose.ps1
```

Она печатает: живы ли супервизор/сервер/туннель, текущий `APP_URL`, локальный и публичный
`/api/health`, `getMe` у бота (то есть валиден ли токен), вебхук и последние строки логов.
Если бот не запущен — `.\scripts\run-all.ps1` (логи в консоли) или `.\scripts\start-all.ps1`
(в фоне) + `.\scripts\stop-all.ps1` для остановки. Логи: `.run\supervisor.log`,
`.run\app.err.log`, `.run\tunnel.out.log`.

**`409 Conflict: terminated by other getUpdates request`** — запущено два процесса бота с
одним токеном (например, локально `.\scripts\run.ps1` и на VPS `vita-ratio.service`).
Telegram разрешает только один `getUpdates`. Останови лишний процесс
(`.\scripts\stop-all.ps1`, `Stop-Process -Name python`, `sudo systemctl stop vita-ratio`) и
оставь один экземпляр бота на токен.

**Кнопка Mini App открывается как обычная ссылка / не открывается на телефоне** —
`APP_URL` не начинается с `https://`. С `scripts\start-all.ps1` это исправляется само:
супервизор поднимает туннель и записывает HTTPS-адрес в `.env`. Если пользуешься
`run.ps1` без туннеля — кнопки Mini App не будет, это ожидаемо. В логе бота при старте
видно строку `Мини-приложение: https://...` — она должна совпадать с `APP_URL`.

**Туннель отвалился, а адрес в Telegram старый** — супервизор перезапускает SSH-туннель и
сам перезапускает бота с новым `APP_URL`; в Telegram заново нажми `/start`. Проверь
`.run\supervisor.log`: там видно «tunnel connection lost, reconnecting» и новый URL.
Если localhost.run недоступен — альтернатива свой VPS с доменом (раздел ниже).

**Пустой initData и «Демо-режим» в браузере** — это нормально: открытие вне Telegram
не даёт подписанного initData. В браузере используй `http://127.0.0.1:8080/?demo=1`
(фронтенд шлёт `X-Dev-User: 1`, требует `APP_ENV=dev`). Если открываешь через кнопку
Telegram, но всё равно демо-режим — проверь, что страница открыта именно по `APP_URL`
из `.env` (и что `telegram-web-app.js` загрузился; локальный `telegram-shim.js` — фолбэк).

**`Unauthorized` / `401 {"ok":false,"error":"unauthorized"}` от API** — не прошла проверка
initData: страница открыта не через Telegram, `BOT_TOKEN` в `.env` сервера не совпадает
с токеном бота, initData старше 24 часов (`auth_date`) или `APP_ENV=prod` без initData.
Открой приложение кнопкой бота заново; для локальной отладки — `APP_ENV=dev` и
`X-Dev-User`/`?demo=1`. `/api/health` доступен без авторизации — начни с него.

**Нет соединения с `api.telegram.org`** (таймауты, `TelegramNetworkError`, бот не
отвечает) — нужен прокси/VPN. Пропиши `PROXY_URL=http://host:port` (или `socks5://...`)
в `.env` и установи `aiohttp-socks` (`pip install aiohttp-socks`) — без него aiogram
прокси не использует. Перезапусти бота и проверь лог: при успехе будет строка
«Запросы к api.telegram.org идут через прокси …».

**Бот молчит или отвечает «Профиль ещё не заполнен»** — у пользователя нет профиля:
напоминания выбираются только из `profiles`, а `/today`, `/plan`, `/sleep`, `/targets`
подсказывают пройти онбординг. Открой `/start` → «Открыть Vita Ratio» → заполни профиль
(4 шага). После этого команды показывают реальные цифры.

**`BOT_TOKEN не задан — бот не запущен`** — `.env` пуст или токен не подтянулся. Проверь
`C:\Users\SPBNB\secrets\vita ratio.txt`, выполни `.\scripts\sync-token.ps1`, убедись, что
строка `BOT_TOKEN=` в `.env` непустая. Сервер при этом запускается и в браузере работает
демо-режим.

**Напоминания не приходят** — проверь: в профиле включён тумблер «Напоминания»; время
профиля в его зоне (`profiles.timezone`); приём пищи попадает в окно «за 10 минут», сон —
«за 30 минут», утренняя сводка — в течение часа после подъёма; факт отправки пишется в
`reminder_log`, поэтому повторно в те же сутки сообщение не уйдёт. Бот не стартовал —
смотри лог, может быть включён режим `server` без бота (`run.ps1 server`).

## REST API (кратко)

Префикс `/api`. Успех — `{"ok":true,"data":…}`, ошибка — `{"ok":false,"error":"…"}`.
Все `/api/*`, кроме `/api/health`, требуют `X-Init-Data` (Telegram initData) или, в
`APP_ENV=dev`, `X-Dev-User: <id>`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | проверка живучести (без авторизации) |
| GET | `/api/bootstrap?date=` | главный экран одним запросом |
| PUT | `/api/profile` | сохранить профиль и пересчитать цели |
| GET/POST | `/api/meals?date=` | приёмы пищи за дату / добавить приём |
| DELETE | `/api/meals/{id}` | удалить приём |
| GET/POST | `/api/sleep?date=` | сон за дату / сохранить сон |
| GET/POST | `/api/weights?days=60` | вес и тренд / добавить вес |
| GET/POST | `/api/classes` | занятия / добавить занятие |
| PUT/DELETE | `/api/classes/{id}` | изменить/удалить занятие |
| GET | `/api/schedule?from=&to=` | вхождения занятий и посещаемость |
| POST | `/api/classes/{id}/done` | отметить «Пришёл/Пропустил/Перенёс» |
| GET | `/api/stats?days=14` | статистика по дням |
| GET | `/api/plan?date=` | план приёмов пищи и окно сна |

Подробные форматы — в `CONTRACT.md`, раздел 6.

## Проверка и тесты

```powershell
.\scripts\test.ps1
```

Скрипт прогоняет `py_compile`/`compileall`, все unit-тесты, `node --check webapp/app.js`
(нужен Node.js) и `tests/check_webapp.mjs`, если он есть. Python-проверки без скрипта —
команды в разделе «Запуск» (`py_compile` + `unittest discover`).

Что покрывает `tests/test_bot.py` — без сети и без токена:

- форматирование `/today` с данными, без профиля, без сна/занятий, с экранированием HTML;
- `/plan`, `/classes`, `/targets`, `/sleep` (включая пустые состояния);
- `due_reminders` на разных временах: за 10 минут до еды (и что не срабатывает раньше/
  позже), за 30 минут до сна, утренняя сводка после подъёма, дедупликация повторного
  вызова, `reminders=0`, профиль отсутствует;
- вид кнопки: `https://` → `web_app`, локальный `http://` → обычная ссылка;
- `run_bot` с пустым/пробельным токеном: пишет ошибку в лог и возвращается без исключения.

## Известные ограничения (честно)

- **Бот не проверялся вживую**: в этом окружении нет интернета и настоящего токена.
  Проверены только чистые функции, выбор напоминаний и запуск без токена; сам
  `getUpdates`/отправка сообщений не выполнялись.
- Mini App на телефоне требует публичного HTTPS; локальный HTTP — только для браузера.
- `PROXY_URL` требует `aiohttp-socks` (нет в vendored-зависимостях и в `requirements.txt`).
- Напоминания живут в памяти процесса: после перезапуска бота «заблокировавшие бота»
  пользователи снова проверяются один раз (ошибка ловится, бот не падает).
- Напоминания — только для заполненного профиля; бот не создаёт профиль, это делает
  онбординг в мини-приложении.
- Один токен — один запущенный бот (иначе `409 Conflict`).
- `ADMIN_ID` пока нигде не используется (задел на админ-команды).
