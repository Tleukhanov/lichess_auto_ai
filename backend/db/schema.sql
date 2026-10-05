-- Схема аналитической БД федерации (SQLite).
-- members: срез клуба (обновляется ежедневно).
-- tournaments/results: история турниров (пишется по окончании).
-- Файл БД (db/federation.db) живёт локально и НЕ коммитится.

CREATE TABLE IF NOT EXISTS members (
    member_id   INTEGER PRIMARY KEY AUTOINCREMENT,  -- наш id для удобства
    nick        TEXT UNIQUE NOT NULL,      -- ник Lichess: уникален, естественный ключ
    rapid       INTEGER,                   -- рейтинг rapid
    blitz       INTEGER,                   -- рейтинг blitz
    bullet      INTEGER,                   -- рейтинг bullet
    games_total INTEGER DEFAULT 0,         -- всего партий (активность)
    last_seen   TEXT,                      -- когда был онлайн, ISO (активность)
    updated_at  TEXT DEFAULT (datetime('now')),  -- когда срез обновлён
    -- Производные (считает analytics.py, не синк):
    is_active    INTEGER DEFAULT 0,        -- 1 = играл на этой неделе (Пн-Вс Астана)
    activity_pct REAL DEFAULT 0.0,         -- доля турниров клуба за 28 дней, где участвовал
    activity_tier TEXT DEFAULT 'dormant'   -- core / regular / casual / dormant
);

CREATE TABLE IF NOT EXISTS tournaments (
    id          TEXT PRIMARY KEY,          -- id турнира Lichess (LsywNwNt)
    name        TEXT NOT NULL,
    variant     TEXT DEFAULT 'standard',
    clock_time  INTEGER,
    clock_inc   INTEGER,
    starts_at   TEXT,
    finishes_at TEXT,
    nb_players  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS results (
    tournament_id TEXT REFERENCES tournaments(id),
    nick          TEXT REFERENCES members(nick),
    rank          INTEGER,
    score         REAL,
    nb_games      INTEGER,
    rating_before INTEGER,                 -- рейтинг на старт (из history)
    rating_after  INTEGER,                 -- рейтинг на финиш (из history)
    berserk_pct   REAL,                    -- % партий с берсерком (может быть NULL)
    raw           TEXT,                    -- сырой JSON строки (на случай новых полей)
    PRIMARY KEY (tournament_id, nick)
);

CREATE INDEX IF NOT EXISTS idx_results_nick ON results(nick);
