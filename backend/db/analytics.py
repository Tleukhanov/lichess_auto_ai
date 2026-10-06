"""Производная аналитика: тиры активности + история рейтингов.

Разделение: members.py/results.py — сырые данные (синк),
этот модуль — выводы (пересчёт). Сырьё не трогаем, выводы пересчитываем.

- Неделя: Пн 00:00 – Вс 23:59 по Астане (UTC+5, без DST — сдвиг фиксированный).
- Окно активности: скользящие 28 дней.
- Тиры: core >= 75%, regular >= 40%, casual > 0%, dormant = 0%.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

ASTANA = timezone(timedelta(hours=5))
CORE_THRESHOLD = 0.75
REGULAR_THRESHOLD = 0.40
ACTIVITY_WINDOW_DAYS = 28

# Очки месяца = сумма score Lichess (победа 2, стрик/берсерк считают они).
# Своих очков не выдумываем: официальный скоринг честнее и понятнее игрокам.


def speed_of(clock_time: int, clock_inc: int) -> str:
    """Контроль -> rapid / blitz / bullet (логика Lichess)."""
    estimate = (clock_time or 0) * 60 + (clock_inc or 0) * 40
    if estimate < 180:
        return "bullet"
    if estimate < 600:
        return "blitz"
    return "rapid"


def month_top(conn: sqlite3.Connection, year: int, month: int) -> dict:
    """Топ месяца: {speed: [(nick, points)], 'overall': [...]}.

    Очки — сумма score Lichess за турниры месяца (Астана).
    """
    start = datetime(year, month, 1, tzinfo=ASTANA)
    end_month = month + 1 if month < 12 else 1
    end_year = year if month < 12 else year + 1
    end = datetime(end_year, end_month, 1, tzinfo=ASTANA)

    tournaments = conn.execute(
        "SELECT id, clock_time, clock_inc, starts_at FROM tournaments"
    ).fetchall()
    per_speed: dict = {}
    overall: dict = {}
    for tournament_id, clock_time, clock_inc, starts_at in tournaments:
        moment = _parse_moment(starts_at)
        if moment is None or not (start <= moment < end):
            continue
        speed = speed_of(clock_time or 0, clock_inc or 0)
        for nick, score in conn.execute(
            "SELECT nick, score FROM results WHERE tournament_id=?", (tournament_id,)
        ):
            points = score if score is not None else 0
            per_speed.setdefault(speed, {}).setdefault(nick, 0)
            per_speed[speed][nick] += points
            overall[nick] = overall.get(nick, 0) + points

    def sort_board(board: dict) -> list:
        return sorted(board.items(), key=lambda item: item[1], reverse=True)

    result = {speed: sort_board(board) for speed, board in per_speed.items()}
    result["overall"] = sort_board(overall)
    return result

DERIVED_COLUMNS = {
    "is_active": "INTEGER DEFAULT 0",
    "activity_pct": "REAL DEFAULT 0.0",
    "activity_tier": "TEXT DEFAULT 'dormant'",
}


def migrate(conn: sqlite3.Connection) -> None:
    """Докрутить колонки в members, если БД создана по старой схеме."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(members)")}
    for name, ddl in DERIVED_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE members ADD COLUMN {name} {ddl}")
    conn.commit()


def week_bounds(now: datetime) -> tuple:
    """Начало (Пн 00:00) и конец (Вс 23:59:59) текущей недели, Астана."""
    local = now.astimezone(ASTANA)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    sunday_end = monday + timedelta(days=7) - timedelta(seconds=1)
    return monday, sunday_end


def _parse_moment(value):
    """ISO-строка, epoch-миллисекунды (число или строка) -> datetime UTC.

    Листинг Lichess отдаёт миллисы, одиночный вид — ISO. Принимаем оба.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        number = int(text)
        # Эвристика: миллисы (>1e12) vs секунды
        if number > 1_000_000_000_000:
            return datetime.fromtimestamp(number / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(number, tz=timezone.utc)
    text = text.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def refresh_activity(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Пересчёт is_active / activity_pct / tier. Возвращает сводку."""
    now = now or datetime.now(timezone.utc)
    monday, _ = week_bounds(now)
    window_start = now - timedelta(days=ACTIVITY_WINDOW_DAYS)

    tournaments = [
        (row[0], _parse_moment(row[1]))
        for row in conn.execute("SELECT id, starts_at FROM tournaments")
    ]
    in_window = [t for t in tournaments if t[1] and t[1] >= window_start]
    this_week = {t for t, moment in in_window if moment >= monday}

    played = {}
    for (tournament_id, nick) in conn.execute("SELECT tournament_id, nick FROM results"):
        played.setdefault(nick, set()).add(tournament_id)

    total = len(in_window)
    summary = {"core": 0, "regular": 0, "casual": 0, "dormant": 0}
    for (nick,) in conn.execute("SELECT nick FROM members"):
        mine = played.get(nick, set()) & {t for t, _ in in_window}
        pct = (len(mine) / total) if total else 0.0
        active = 1 if (mine & this_week) else 0
        if pct >= CORE_THRESHOLD:
            tier = "core"
        elif pct >= REGULAR_THRESHOLD:
            tier = "regular"
        elif pct > 0:
            tier = "casual"
        else:
            tier = "dormant"
        conn.execute(
            "UPDATE members SET is_active=?, activity_pct=?, activity_tier=? WHERE nick=?",
            (active, round(pct, 3), tier, nick),
        )
        summary[tier] += 1
    conn.commit()
    summary["tournaments_28d"] = total
    return summary


def fetch_rating_history(username: str) -> dict:
    """История рейтингов: {perf_name: [(date, rating)]}. Один запрос на игрока."""
    import requests

    from backend.lichess_auto.client import BASE_URL

    response = requests.get(f"{BASE_URL}/api/user/{username}/rating-history", timeout=30)
    response.raise_for_status()
    history = {}
    for perf in response.json():
        points = []
        for year, month, day, rating in perf.get("points", []):
            points.append((datetime(year, month, day, tzinfo=timezone.utc), rating))
        history[perf.get("name", "").lower()] = sorted(points)
    return history


def rating_at(history: list, moment, side: str) -> int | None:
    """Рейтинг на момент: side='before' — последняя точка <= moment,
    side='after' — первая точка >= moment (иначе ближайшая)."""
    if not history:
        return None
    if side == "before":
        past = [r for d, r in history if d <= moment]
        return past[-1] if past else history[0][1]
    future = [r for d, r in history if d >= moment]
    return future[0] if future else history[-1][1]


def backfill_ratings(conn: sqlite3.Connection) -> int:
    """Добивка rating_before/after из history. Возвращает число обновлённых строк."""
    updated = 0
    rows = conn.execute(
        """
        SELECT r.tournament_id, r.nick, t.starts_at, t.finishes_at, t.variant,
               t.clock_time, t.clock_inc, r.rating_before, r.rating_after
        FROM results r JOIN tournaments t ON t.id = r.tournament_id
        """
    ).fetchall()
    cache = {}
    for tournament_id, nick, starts_at, finishes_at, variant, clock_time, clock_inc, before, after in rows:
        if before is not None and after is not None:
            continue
        if nick not in cache:
            cache[nick] = fetch_rating_history(nick)
        perf = _perf_key(variant, clock_time or 0, clock_inc or 0)
        history = cache[nick].get(perf, [])
        start = _parse_moment(starts_at)
        finish = _parse_moment(finishes_at) or start
        conn.execute(
            "UPDATE results SET rating_before=?, rating_after=? "
            "WHERE tournament_id=? AND nick=?",
            (
                before if before is not None else (rating_at(history, start, "before") if start else None),
                after if after is not None else (rating_at(history, finish, "after") if finish else None),
                tournament_id,
                nick,
            ),
        )
        updated += 1
    conn.commit()
    return updated


def _perf_key(variant: str | None, clock_time: int, clock_inc: int) -> str:
    """Вариант+контроль -> имя перфа в history.

    Chess960 живёт отдельным перфом. Остальное — по оценке времени:
    bullet < 3 мин, blitz < 10 мин, иначе rapid (логика Lichess).
    """
    if (variant or "standard").lower() == "chess960":
        return "chess960"
    estimate = clock_time * 60 + clock_inc * 40
    if estimate < 180:
        return "bullet"
    if estimate < 600:
        return "blitz"
    return "rapid"
