-- Vita Ratio · схема БД (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    last_name   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    sex            TEXT    NOT NULL DEFAULT 'male'    CHECK (sex IN ('male','female')),
    age            INTEGER NOT NULL DEFAULT 25         CHECK (age BETWEEN 10 AND 100),
    height_cm      REAL    NOT NULL DEFAULT 175        CHECK (height_cm BETWEEN 100 AND 250),
    weight_kg      REAL    NOT NULL DEFAULT 70         CHECK (weight_kg BETWEEN 25 AND 400),
    activity       TEXT    NOT NULL DEFAULT 'moderate' CHECK (activity IN ('sedentary','light','moderate','high','athlete')),
    goal_rate      REAL    NOT NULL DEFAULT 0.35       CHECK (goal_rate BETWEEN 0.0 AND 1.5),
    protein_per_kg REAL    NOT NULL DEFAULT 2.0        CHECK (protein_per_kg BETWEEN 1.0 AND 4.0),
    sleep_bed      TEXT    NOT NULL DEFAULT '23:00',
    sleep_wake     TEXT    NOT NULL DEFAULT '07:00',
    reminders      INTEGER NOT NULL DEFAULT 1,
    timezone       TEXT    NOT NULL DEFAULT 'Europe/Moscow',
    goal_weight_kg REAL,
    goal_date      TEXT,
    ai_enabled     INTEGER NOT NULL DEFAULT 0,  -- ИИ-разбор заметок (потом можно закрыть оплатой)
    sub_until      TEXT,                        -- подписка на бота (250 ₽/мес)
    ai_until       TEXT,                        -- аддон ИИ (+100 ₽/мес), продлевается отдельно
    theme_accent   TEXT    NOT NULL DEFAULT '#B7F75C',
    theme_bg       TEXT    NOT NULL DEFAULT '#0E1116',
    theme_card     TEXT    NOT NULL DEFAULT '#151A21',
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    time       TEXT    NOT NULL DEFAULT '12:00',
    title      TEXT    NOT NULL,
    kcal       REAL    NOT NULL DEFAULT 0,
    protein    REAL    NOT NULL DEFAULT 0,
    fat        REAL    NOT NULL DEFAULT 0,
    carbs      REAL    NOT NULL DEFAULT 0,
    grams      REAL    NOT NULL DEFAULT 0,
    food_key   TEXT    NOT NULL DEFAULT '',
    items_json TEXT    NOT NULL DEFAULT '[]',
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_meals_user_date ON meals(user_id, date);

CREATE TABLE IF NOT EXISTS sleep_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,              -- дата пробуждения
    bed_time   TEXT    NOT NULL,
    wake_time  TEXT    NOT NULL,
    duration_h REAL    NOT NULL DEFAULT 8,
    quality    INTEGER NOT NULL DEFAULT 3 CHECK (quality BETWEEN 1 AND 5),
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, date)
);

CREATE TABLE IF NOT EXISTS weights (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    kg         REAL    NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, date)
);

CREATE TABLE IF NOT EXISTS classes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    kind         TEXT    NOT NULL DEFAULT 'gym' CHECK (kind IN ('gym','study','other')),
    weekday      INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time   TEXT    NOT NULL DEFAULT '18:00',
    duration_min INTEGER NOT NULL DEFAULT 60 CHECK (duration_min BETWEEN 15 AND 480),
    place        TEXT    NOT NULL DEFAULT '',
    note         TEXT    NOT NULL DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_classes_user ON classes(user_id);

CREATE TABLE IF NOT EXISTS class_done (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'present' CHECK (status IN ('present','absent','moved')),
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, class_id, date)
);

CREATE TABLE IF NOT EXISTS reminder_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date     TEXT    NOT NULL,
    kind     TEXT    NOT NULL,
    sent_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, date, kind)
);

-- Планировщик дня: собственные блоки расписания пользователя (еда/тренировка/учёба/сон/дела)
CREATE TABLE IF NOT EXISTS day_plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date         TEXT    NOT NULL,
    time         TEXT    NOT NULL DEFAULT '12:00',
    title        TEXT    NOT NULL,
    kind         TEXT    NOT NULL DEFAULT 'other' CHECK (kind IN ('meal','gym','study','sleep','work','other')),
    duration_min INTEGER NOT NULL DEFAULT 60 CHECK (duration_min BETWEEN 5 AND 720),
    note         TEXT    NOT NULL DEFAULT '',
    done         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_day_plans_user_date ON day_plans(user_id, date);

-- Недельный чек-ин: раз в неделю пользователь вводит прогресс и КБЖУ пересчитывается
CREATE TABLE IF NOT EXISTS weekly_checkins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start  TEXT    NOT NULL,              -- понедельник ISO
    weight_kg   REAL    NOT NULL,
    feeling     TEXT    NOT NULL DEFAULT 'ok'  CHECK (feeling IN ('good','ok','bad')),
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, week_start)
);

-- Заметки пользователя с ответом ИИ-коуча (команда /note в боте)
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    text       TEXT    NOT NULL,
    ai_text    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_user_date ON notes(user_id, date);

-- Платежи Telegram Stars: base = 250 ₽/мес (доступ к боту), ai = +100 ₽/мес (ИИ-разбор)
CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('base', 'ai')),
    charge_id  TEXT    NOT NULL UNIQUE,
    amount     INTEGER NOT NULL,
    currency   TEXT    NOT NULL DEFAULT 'XTR',
    payload    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Рублёвые счета эквайринга (ЮKassa/Robokassa): оплата картой, деньги сразу на карту самозанятого
CREATE TABLE IF NOT EXISTS invoices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('base', 'ai')),
    provider    TEXT    NOT NULL DEFAULT 'yookassa',
    external_id TEXT    NOT NULL UNIQUE,  -- id платежа у провайдера (YooKassa payment id / Robokassa InvId)
    amount_rub  REAL    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'canceled')),
    payload     TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices(user_id);

-- Бесплатный доступ, управляемый из бота (/grant, /revoke): ID или @username.
CREATE TABLE IF NOT EXISTS free_access (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    value      TEXT    NOT NULL UNIQUE,  -- "123456789" или "username" (без @, lower)
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);


