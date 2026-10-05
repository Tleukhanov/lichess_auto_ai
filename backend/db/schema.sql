-- Схема аналитической БД федерации (PostgreSQL).
-- members: срез клуба (обновляется ежедневно).
-- tournaments/results: история турниров (пишется по окончании).

CREATE TABLE IF NOT EXISTS members (
    nick        TEXT PRIMARY KEY,          -- ник Lichess: уникален, естественный ключ
    member_id   SERIAL UNIQUE,             -- наш id для удобства (джойны, ссылки)
    rapid       INTEGER,                   -- рейтинг rapid
    blitz       INTEGER,                   -- рейтинг blitz
    bullet      INTEGER,                   -- рейтинг bullet
    games_total INTEGER DEFAULT 0,         -- всего партий (активность)
    last_seen   TIMESTAMPTZ,               -- когда был онлайн (активность)
    updated_at  TIMESTAMPTZ DEFAULT now()  -- когда срез обновлён
);

CREATE TABLE IF NOT EXISTS tournaments (
    id          TEXT PRIMARY KEY,          -- id турнира Lichess (LsywNwNt)
    name        TEXT NOT NULL,
    variant     TEXT DEFAULT 'standard',
    clock_time  INTEGER,
    clock_inc   INTEGER,
    starts_at   TIMESTAMPTZ,
    finishes_at TIMESTAMPTZ,
    nb_players  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS results (
    tournament_id TEXT REFERENCES tournaments(id),
    nick          TEXT REFERENCES members(nick),
    rank          INTEGER,
    score         NUMERIC,
    nb_games      INTEGER,
    rating_before INTEGER,                 -- рейтинг на старт (из history)
    rating_after  INTEGER,                 -- рейтинг на финиш (из history)
    berserk_pct   NUMERIC,                 -- % партий с берсерком (может быть NULL)
    PRIMARY KEY (tournament_id, nick)
);

CREATE INDEX IF NOT EXISTS idx_results_nick ON results(nick);
