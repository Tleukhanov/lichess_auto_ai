"""Планировщик: читает schedule.json → создаёт недостающие (без дублей).

Запуск из корня проекта:
    python -m backend.lichess_auto.schedule
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

from backend.lichess_auto.client import get_session
from backend.lichess_auto.tournaments import TournamentConfig, ensure_tournament

SCHEDULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.json")
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "federation.db"
)


def load_schedule(path: str = SCHEDULE_PATH) -> list:
    with open(path, encoding="utf-8") as schedule_file:
        raw_items = json.load(schedule_file)
    configs = [TournamentConfig.from_dict(item) for item in raw_items]
    pinned = [config.name for config in configs if config.is_need]
    if len(pinned) > 1:
        raise ValueError(f"Закреплённым может быть только один турнир, а помечены: {pinned}")
    return configs


def remember_tournament(tournament_id: str, config: TournamentConfig) -> None:
    """Сразу пишем созданное в БД, чтобы анонсы видели его без отдельного снапшота.

    finishes_at прикидываем: старт + длительность (Lichess считает так же).
    """
    import sqlite3
    from datetime import datetime, timedelta, timezone

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE tournaments ADD COLUMN announced INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE tournaments ADD COLUMN is_need INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    if config.starts_at:
        start = datetime.fromisoformat(config.starts_at.replace("Z", "+00:00"))
    else:
        start = datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    finish = start + timedelta(minutes=config.minutes)
    # Закреплённым может быть только один: сначала снимаем флаг со всех
    if config.is_need:
        conn.execute("UPDATE tournaments SET is_need = 0")
    conn.execute(
        "INSERT INTO tournaments (id, name, variant, clock_time, clock_inc, "
        "starts_at, finishes_at, nb_players, announced, is_need) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, starts_at=excluded.starts_at, "
        "finishes_at=excluded.finishes_at, is_need=excluded.is_need",
        (
            tournament_id,
            config.name,
            config.variant,
            config.clock_time,
            config.clock_increment,
            start.isoformat(),
            finish.isoformat(),
            1 if config.is_need else 0,
        ),
    )
    conn.commit()
    conn.close()


def main() -> None:
    load_dotenv()
    username = os.environ["LICHESS_USERNAME"]
    session = get_session()
    for config in load_schedule():
        result = ensure_tournament(session, username, config)
        status = "уже был (дубль)" if result["duplicate"] else "СОЗДАН"
        print(f"{status}: {config.name} -> {result['id']}")
        remember_tournament(result["id"], config)


if __name__ == "__main__":
    main()
