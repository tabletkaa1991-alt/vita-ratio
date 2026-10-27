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
