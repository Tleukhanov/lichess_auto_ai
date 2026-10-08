"""Веб-API федерации: JSON поверх federation.db + раздача фронта.

Те же функции, что считает аналитика (month_top, тиры) — фронт их рисует.
Запуск из корня проекта:  python -m backend.webapi  (http://127.0.0.1:8001)
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.db.analytics import month_top

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "db", "federation.db"
)
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)

app = FastAPI(title="Federation Board")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/month")
def api_month(year: int = 0, month: int = 0):
    """Топ месяца: rapid/blitz/bullet/overall. По умолчанию текущий месяц."""
    now = datetime.now(timezone.utc)
    board = month_top(_db(), year or now.year, month or now.month)
    return board


@app.get("/api/activity")
def api_activity():
    """Тиры активности всех участников."""
    conn = _db()
    rows = conn.execute(
        "SELECT nick, rapid, blitz, bullet, is_active, activity_pct, activity_tier "
        "FROM members ORDER BY activity_pct DESC"
    ).fetchall()
    conn.close()
    return [
        {
            "nick": row["nick"],
            "rapid": row["rapid"],
            "blitz": row["blitz"],
            "bullet": row["bullet"],
            "is_active": bool(row["is_active"]),
            "activity_pct": row["activity_pct"],
            "tier": row["activity_tier"],
        }
        for row in rows
    ]


@app.get("/api/tournaments")
def api_tournaments(limit: int = 20):
    """Только ближайшие: стартовали не раньше 4 часов назад + все будущие.

    Закреплённый («рекомендую») — первым. Фильтр в Python, а не в SQL:
    starts_at лежит в двух форматах (ISO и миллисы), SQL их не сравнит.
    """
    from datetime import datetime, timedelta, timezone

    from backend.db.analytics import _parse_moment

    conn = _db()
    try:
        conn.execute("SELECT is_need FROM tournaments LIMIT 1")
        need_column = "COALESCE(is_need, 0)"
    except sqlite3.OperationalError:
        need_column = "0"  # старая БД без флага — считаем все обычными
    rows = conn.execute(
        "SELECT id, name, variant, clock_time, clock_inc, starts_at, nb_players, "
        f"({need_column}) AS need FROM tournaments"
    ).fetchall()
    now = datetime.now(timezone.utc)
    fresh = []
    for tournament in rows:
        moment = _parse_moment(tournament["starts_at"])
        if moment is None:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if moment >= now - timedelta(hours=4):
            fresh.append(tournament)
    fresh.sort(key=lambda row: (not row["need"], str(row["starts_at"])))
    tournaments = fresh[:limit]
    result = []
    for tournament in tournaments:
        top = conn.execute(
            "SELECT nick, rank, score FROM results WHERE tournament_id=? ORDER BY rank LIMIT 3",
            (tournament["id"],),
        ).fetchall()
        result.append(
            {
                "id": tournament["id"],
                "name": tournament["name"],
                "variant": tournament["variant"],
                "clock": f"{tournament['clock_time'] or '?'}+{tournament['clock_inc'] or '?'}",
                "starts_at": tournament["starts_at"],
                "nb_players": tournament["nb_players"],
                "is_need": bool(tournament["need"]),
                "link": f"https://lichess.org/tournament/{tournament['id']}",
                "top": [
                    {"nick": row["nick"], "rank": row["rank"], "score": row["score"]}
                    for row in top
                ],
            }
        )
    conn.close()
    return result


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.get("/api/docs", include_in_schema=False)
def api_index():
    return {"endpoints": ["/api/month", "/api/activity", "/api/tournaments"]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
