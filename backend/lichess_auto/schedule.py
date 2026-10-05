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


def load_schedule(path: str = SCHEDULE_PATH) -> list:
    with open(path, encoding="utf-8") as schedule_file:
        raw_items = json.load(schedule_file)
    return [TournamentConfig.from_dict(item) for item in raw_items]


def main() -> None:
    load_dotenv()
    username = os.environ["LICHESS_USERNAME"]
    session = get_session()
    for config in load_schedule():
        result = ensure_tournament(session, username, config)
        status = "уже был (дубль)" if result["duplicate"] else "СОЗДАН"
        print(f"{status}: {config.name} -> {result['id']}")


if __name__ == "__main__":
    main()
