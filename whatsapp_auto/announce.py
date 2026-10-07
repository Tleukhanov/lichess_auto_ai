"""Анонсы турниров: за час, за 10 минут, итоги после финиша.

Состояния флага announced: 0 нет -> 1 за час -> 2 за 10 мин -> 3 итоги отправлены.
Тексты — случайный шаблон (без LLM: быстро и бесплатно), рассылка — во все группы.
"""

import random as _random
from datetime import datetime, timezone

from .config import ANNOUNCE_MINUTES, GROUP_CHAT_IDS
from .db_store import connect
from .waha import waha_send

ANNOUNCE_TEMPLATES = [
    "♟️ {name} уже скоро! {control}, играем {duration}. Жми: {link} 🔥",
    "Эй, шахматисты! {when} стартует «{name}» ({control}, {duration}). Кто не успел — {link} ♟️",
    "🏆 Турнир на носу: {name} — {control}, {duration}. Ссылка: {link}. Берсерк разрешён 😏",
    "Готовьте фигуры! «{name}» ({control}) начинается {when}. {link} ⏳",
]


def render_announce(template_kind: str, name: str, control: str, duration: str, link: str, when: str) -> str:
    """Случайный шаблон + подстановка."""
    return _random.choice(ANNOUNCE_TEMPLATES).format(
        name=name, control=control, duration=duration, link=link, when=when
    )


def broadcast(text: str) -> int:
    """Разослать текст по всем группам. Возвращает число отправок."""
    sent_count = 0
    for chat_id in GROUP_CHAT_IDS:
        waha_send(chat_id, text)
        sent_count += 1
    return sent_count


def _parse_moment(value):
    """ISO или epoch-миллисы -> datetime UTC (форматы Lichess гуляют)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        number = int(text)
        if number > 1_000_000_000_000:
            return datetime.fromtimestamp(number / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(number, tz=timezone.utc)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def announce_due(now=None) -> list:
    """Проверяет расписание и рассылает due-уведомления. Возвращает id затронутых."""
    now = now or datetime.now(timezone.utc)
    if not GROUP_CHAT_IDS:
        return []
    conn = connect()
    touched = []
    for row in conn.execute(
        "SELECT id, name, starts_at, finishes_at, clock_time, clock_inc, COALESCE(announced, 0) FROM tournaments"
    ):
        tournament_id, name, starts_at, finishes_at, clock_time, clock_inc, flag = row
        start = _parse_moment(starts_at)
        if start is None:
            continue
        minutes_to_start = (start - now).total_seconds() / 60
        link = f"https://lichess.org/tournament/{tournament_id}"
        control = f"{clock_time or '?'}+{clock_inc or '?'}"
        duration = ""
        if finishes_at:
            finish = _parse_moment(finishes_at)
            if finish is not None:
                length = round((finish - start).total_seconds() / 60)
                duration = f"{length} минут"
        if not duration:
            duration = "скоротечный турнир"
        if flag == 0 and 0 <= minutes_to_start <= 60:
            broadcast(render_announce("hour", name, control, duration, link, "через час"))
            conn.execute("UPDATE tournaments SET announced = 1 WHERE id = ?", (tournament_id,))
            touched.append(tournament_id)
        elif flag == 1 and 0 <= minutes_to_start <= ANNOUNCE_MINUTES:
            broadcast(render_announce("ten", name, control, duration, link, "через 10 минут"))
            conn.execute("UPDATE tournaments SET announced = 2 WHERE id = ?", (tournament_id,))
            touched.append(tournament_id)
        elif flag == 2:
            finish = _parse_moment(finishes_at)
            if finish is not None and now >= finish:
                top = conn.execute(
                    "SELECT nick, rank FROM results WHERE tournament_id=? ORDER BY rank LIMIT 3",
                    (tournament_id,),
                ).fetchall()
                if top:
                    places = "\n".join(f"{i + 1}. {nick}" for i, (nick, _) in enumerate(top))
                    broadcast(f"Итоги «{name}»:\n{places}\n{link}")
                else:
                    broadcast(f"Турнир «{name}» завершён. Результаты — в дашборде.")
                conn.execute("UPDATE tournaments SET announced = 3 WHERE id = ?", (tournament_id,))
                touched.append(tournament_id)
    conn.commit()
    conn.close()
    return touched
