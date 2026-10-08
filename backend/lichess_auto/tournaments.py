"""Создание турниров Lichess: арена и швейцарка (клубные)."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .client import BASE_URL
from .transport import post_with_retry

TournamentKind = Literal["arena", "swiss"]
Variant = Literal["standard", "chess960", "kingOfTheHill", "antichess"]


@dataclass
class TournamentConfig:
    """Фундамент: все параметры турнира в одном месте с типами."""

    name: str
    kind: TournamentKind = "arena"
    club_team_id: str = ""          # НАШ клуб: турнир живёт внутри него
    opponent_teams: list = field(default_factory=list)  # межклуб: соперники
    variant: Variant = "standard"   # standard | chess960 | ...
    opening_fen: str = ""           # выбранный дебют (FEN), если задан
    clock_time: int = 5             # минут на партию
    clock_increment: int = 3        # добавление секунд за ход
    minutes: int = 60               # длительность арены
    # Время старта, ISO с часовым поясом, напр. "2026-10-06T19:00:00+05:00" (Астана).
    # Пусто = старт по дефолту Lichess (через ~5 минут после создания).
    starts_at: str = ""
    # Закреплённый турнир ("рекомендую"): только ОДИН на всё расписание.
    # Проверяется в load_schedule — два флага = ошибка конфига.
    is_need: bool = False

    def validate(self) -> None:
        if not self.club_team_id:
            raise ValueError("Турнир создаём только внутри клуба — нужен club_team_id")
        if self.kind not in ("arena", "swiss"):
            raise ValueError(f"Неизвестный тип турнира: {self.kind}")
        if self.clock_time <= 0 or self.minutes <= 0:
            raise ValueError("Время должно быть положительным")
        if self.starts_at:
            try:
                _to_millis(self.starts_at)
            except ValueError:
                raise ValueError(
                    "starts_at — ISO с часовым поясом, напр. 2026-10-06T19:00:00+05:00"
                )

    @classmethod
    def from_dict(cls, data: dict) -> "TournamentConfig":
        """Строка расписания (JSON) → конфиг. Лишние ключи отбрасываются."""
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


def _to_millis(moment: str) -> int:
    """ISO-строка с часовым поясом -> миллисекунды epoch (так хочет Lichess)."""
    return int(datetime.fromisoformat(moment).timestamp() * 1000)


def _create_arena(session, config: TournamentConfig) -> dict:
    """Арена: открытый турнир по времени, вход только членам клуба."""
    payload = {
        "name": config.name,
        "clockTime": config.clock_time,
        "clockIncrement": config.clock_increment,
        "minutes": config.minutes,
        "variant": config.variant,
        "teamId": config.club_team_id,
        # Условие входа: только члены клуба (проверено: работает, verdict в ответе)
        "conditions.teamMember.teamId": config.club_team_id,
    }
    if config.starts_at:
        payload["startDate"] = _to_millis(config.starts_at)
    if config.opening_fen:
        payload["position"] = config.opening_fen
    return post_with_retry(session, f"{BASE_URL}/api/tournament", payload)


def _create_swiss(session, config: TournamentConfig) -> dict:
    """Швейцарка: турнир внутри команды."""
    payload = {
        "name": config.name,
        "clockTime": config.clock_time,
        "clockIncrement": config.clock_increment,
        "variant": config.variant,
    }
    return post_with_retry(session, f"{BASE_URL}/api/swiss/new/{config.club_team_id}", payload)


_CREATORS = {
    "arena": _create_arena,
    "swiss": _create_swiss,
}


def list_my_upcoming(session, username: str) -> list:
    """Турниры, которые я создал и которые ещё впереди."""
    # Lichess отдаёт NDJSON-поток (JSON на строку), а не один объект.
    # Пустой поток = турниров нет = пустой список (это норма, не ошибка).
    response = session.get(f"{BASE_URL}/api/user/{username}/tournament/created")
    response.raise_for_status()
    upcoming = []
    for line in response.iter_lines():
        if line:
            upcoming.append(json.loads(line))
    return upcoming


# Статусы арены у Lichess: 10 — создан (впереди), 20 — идёт, 30 — завершён.
FINISHED_STATUS = 30


def find_duplicate(created: list, config: TournamentConfig) -> dict | None:
    """То же имя + ещё не завершился = дубль, создавать нельзя.

    Завершённые (status 30) игнорируем: их время прошло,
    расписание должно создать свежие.
    """
    for tournament in created:
        if tournament.get("status") == FINISHED_STATUS:
            continue
        if tournament.get("fullName", "").startswith(config.name):
            return tournament
    return None


def ensure_tournament(session, username: str, config: TournamentConfig) -> dict:
    """Нет дубля → создаём, есть → возвращаем существующий."""
    config.validate()
    duplicate = find_duplicate(list_my_upcoming(session, username), config)
    if duplicate is not None:
        return {"id": duplicate["id"], "duplicate": True}
    created = _CREATORS[config.kind](session, config)
    created["duplicate"] = False
    return created
