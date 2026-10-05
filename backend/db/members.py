"""Синк участников клуба: Lichess -> SQLite (upsert).

Источники:
- состав: GET /api/team/{team}/users (NDJSON)
- рейтинги: POST /api/users (до 300 ников за раз -> perfs)

Запуск из корня проекта:
    python -m backend.db.members
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
from dotenv import load_dotenv

from backend.lichess_auto.client import BASE_URL

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "federation.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
PERFS = ("rapid", "blitz", "bullet")


def init_db(path: str = DB_PATH) -> sqlite3.Connection:
    fresh = not os.path.exists(path)
    conn = sqlite3.connect(path)
    if fresh:
        with open(SCHEMA_PATH, encoding="utf-8") as schema_file:
            conn.executescript(schema_file.read())
    return conn


def fetch_team_nicks(team_id: str) -> list:
    """Ники участников команды (NDJSON)."""
    response = requests.get(f"{BASE_URL}/api/team/{team_id}/users", timeout=30)
    response.raise_for_status()
    nicks = []
    for line in response.iter_lines():
        if line:
            import json as _json
            # Лёгкие объекты: {id, name} (без username) — берём id
            nicks.append(_json.loads(line)["id"])
    return nicks


def fetch_perfs(nicks: list) -> dict:
    """Рейтинги пачкой: {nick: {rapid, blitz, bullet, games, last_seen}}."""
    import json as _json

    response = requests.post(f"{BASE_URL}/api/users", data=",".join(nicks), timeout=30)
    response.raise_for_status()
    # Bulk-эндпоинт отдаёт один JSON-массив (не NDJSON) — парсим целиком,
    # с фолбэком на построчный разбор, если формат сменится
    body = response.text.strip()
    if body.startswith("["):
        users = _json.loads(body)
    else:
        users = [_json.loads(line) for line in response.iter_lines() if line]
    result = {}
    for user in users:
        perfs = user.get("perfs", {})
        games = sum((perfs.get(p, {}) or {}).get("games", 0) for p in PERFS)
        # Ключ — id строчными (так пришли ники из команды)
        result[user["id"]] = {
            "rapid": (perfs.get("rapid", {}) or {}).get("rating"),
            "blitz": (perfs.get("blitz", {}) or {}).get("rating"),
            "bullet": (perfs.get("bullet", {}) or {}).get("rating"),
            "games_total": games,
            # last_seen: Lichess отдаёт seenAt в миллисекундах
            "last_seen": user.get("seenAt"),
        }
    return result


def sync_members(team_id: str, conn: sqlite3.Connection) -> int:
    """Upsert участников. Возвращает число обработанных."""
    nicks = fetch_team_nicks(team_id)
    if not nicks:
        return 0
    stats = fetch_perfs(nicks)
    for nick in nicks:
        row = stats.get(nick, {})
        conn.execute(
            """
            INSERT INTO members (nick, rapid, blitz, bullet, games_total, last_seen, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(nick) DO UPDATE SET
                rapid=excluded.rapid, blitz=excluded.blitz, bullet=excluded.bullet,
                games_total=excluded.games_total, last_seen=excluded.last_seen,
                updated_at=datetime('now')
            """,
            (nick, row.get("rapid"), row.get("blitz"), row.get("bullet"),
             row.get("games_total", 0), row.get("last_seen")),
        )
    conn.commit()
    return len(nicks)


def main() -> None:
    team_id = os.environ.get("CLUB_TEAM_ID", "test_auto_bot")
    conn = init_db()
    count = sync_members(team_id, conn)
    print(f"синхронизировано участников: {count}")
    for row in conn.execute("SELECT member_id, nick, rapid, blitz, bullet FROM members"):
        print(row)
    conn.close()


if __name__ == "__main__":
    main()
