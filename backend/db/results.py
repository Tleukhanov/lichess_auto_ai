"""Снапшот турниров + результаты: Lichess -> SQLite.

- tournaments: upsert из листинга созданных (id, имя, контроль, старт/финиш, участники)
- results: строки /api/tournament/{id}/results (сырой JSON сохраняем в raw,
  разбор ключевых полей — best effort через .get, без падений на новых полях)

Запуск из корня проекта:
    python -m backend.db.results
"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
from dotenv import load_dotenv

from backend.db.members import DB_PATH, init_db
from backend.lichess_auto.client import BASE_URL, get_session

load_dotenv()


def snapshot_tournaments(session, username: str, conn: sqlite3.Connection) -> int:
    """Upsert созданных турниров. Возвращает число обработанных."""
    from backend.lichess_auto.tournaments import list_my_upcoming

    count = 0
    for tournament in list_my_upcoming(session, username):
        # В листинге variant — объект {key,...}, в одиночном виде — строка
        variant = tournament.get("variant")
        if isinstance(variant, dict):
            variant = variant.get("key")
        conn.execute(
            """
            INSERT INTO tournaments (id, name, variant, clock_time, clock_inc,
                                     starts_at, finishes_at, nb_players)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, nb_players=excluded.nb_players,
                finishes_at=excluded.finishes_at
            """,
            (
                tournament.get("id"),
                tournament.get("fullName"),
                variant,
                (tournament.get("clock") or {}).get("limit", 0) // 60,
                (tournament.get("clock") or {}).get("increment"),
                tournament.get("startsAt"),
                tournament.get("finishesAt"),
                tournament.get("nbPlayers", 0),
            ),
        )
        count += 1
    conn.commit()
    return count


def import_results(session, tournament_id: str, conn: sqlite3.Connection) -> int:
    """Строки результатов турнира. Возвращает число строк."""
    response = session.get(f"{BASE_URL}/api/tournament/{tournament_id}/results", timeout=60)
    response.raise_for_status()
    count = 0
    for line in response.iter_lines():
        if not line:
            continue
        row = json.loads(line)
        player = row.get("player") or {}
        nick = player.get("id") or player.get("name")
        if not nick:
            continue
        conn.execute(
            """
            INSERT INTO results (tournament_id, nick, rank, score, nb_games,
                                 rating_before, rating_after, berserk_pct, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tournament_id, nick) DO UPDATE SET
                rank=excluded.rank, score=excluded.score, nb_games=excluded.nb_games,
                rating_before=excluded.rating_before, rating_after=excluded.rating_after,
                berserk_pct=excluded.berserk_pct, raw=excluded.raw
            """,
            (
                tournament_id,
                nick,
                row.get("rank"),
                row.get("score"),
                row.get("nbGames") or row.get("nb_games"),
                None,  # rating_before: из rating-history (следующая итерация)
                row.get("rating"),  # текущий рейтинг игрока
                None,  # berserk_pct: из PGN-разбора (фаза 3)
                line.decode("utf-8") if isinstance(line, bytes) else line,
            ),
        )
        count += 1
    conn.commit()
    return count


def main() -> None:
    username = os.environ["LICHESS_USERNAME"]
    session = get_session()
    conn = init_db()
    tournaments = snapshot_tournaments(session, username, conn)
    print(f"турниров в базе: {tournaments}")
    total_rows = 0
    for (tournament_id,) in conn.execute("SELECT id FROM tournaments"):
        rows = import_results(session, tournament_id, conn)
        total_rows += rows
    print(f"строк результатов: {total_rows} (пусто пока нет участников — норма)")
    conn.close()


if __name__ == "__main__":
    main()
