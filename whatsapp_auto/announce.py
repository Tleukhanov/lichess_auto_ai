"""Анонсы турниров: за час, за 10 минут, итоги после финиша.

Состояния флага announced: 0 нет -> 1 за час -> 2 за 10 мин -> 3 итоги отправлены.
Тексты — случайный шаблон (без LLM: быстро и бесплатно), рассылка — во все группы.
"""

import random as _random
from datetime import datetime, timedelta, timezone

ASTANA_TZ = timezone(timedelta(hours=5))  # UTC+5, без DST — сдвиг фиксированный

from .config import ANNOUNCE_MINUTES, CLUB_TEAM_ID, GROUP_CHAT_IDS
from .db_store import connect
from .waha import waha_send

ANNOUNCE_TEMPLATES = [
    "♟️ {name} — {when}. Контроль {control}, {duration}. Ссылка: {link}",
    "Напоминаем: «{name}» ({control}, {duration}) — {when}. Ссылка для участия: {link} ♟️",
    "🏆 {name} — {control}, {duration}. Начало {when}. Ссылка: {link}",
    "«{name}» ({control}) — {when}. Присоединяйтесь: {link} ⏳",
]


def render_day_announce(name, control, duration, time_label, club_link, link) -> str:
    """Дневной анонс по черновику организатора: структура его, поля наши."""
    return (
        "Доброго времени суток! ♟️\n"
        f"\nСегодня в {time_label} планируется турнир «{name}»! 🏆\n"
        f"Тип: Арена 🏟️\n"
        f"Контроль: {control} ⏱️\n"
        f"Длительность: {duration} ⌛\n"
        f"Вступить в клуб: *{club_link}*\n"
        f"Турнир: *{link}*\n"
        "\nВсем удачи!"
    )


def render_reminder(name, link) -> str:
    """Напоминание за 10 минут по черновику организатора."""
    return f"⏰ Напоминаю: через 10 минут начало турнира «{name}»!\nЗаходи: {link}"


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


def _is_announce_time(start, now) -> bool:
    """Дневной анонс: турнир сегодня + уже после 10:00 Астаны (ночью не будим).

    Часовые пояса — через astimezone (пересчёт представления),
    НЕ через +timedelta (он сдвигает сам момент — классический баг).
    """
    astana_now = now.astimezone(ASTANA_TZ)
    if astana_now.hour < 10:
        return False
    astana_start = start.astimezone(ASTANA_TZ)
    return astana_start.date() == astana_now.date() and start > now


def _start_label(start) -> str:
    """'сегодня в 20:00' — для дневного анонса."""
    return f"сегодня в {start.astimezone(ASTANA_TZ):%H:%M}"


def _today_key(now: datetime) -> str:
    """Ключ дня в Астане: YYYY-MM-DD."""
    return now.astimezone(ASTANA_TZ).strftime("%Y-%m-%d")


def _day_digest_sent(conn, day_key: str) -> bool:
    row = conn.execute("SELECT 1 FROM day_digest WHERE day = ?", (day_key,)).fetchone()
    return row is not None


def _mark_day_digest_sent(conn, day_key: str) -> None:
    conn.execute("INSERT OR IGNORE INTO day_digest (day) VALUES (?)", (day_key,))


def _fmt_control(clock_time, clock_inc) -> str:
    """Контроль вида '3+0': 0 — валидное добавление, '?' — только если данных нет."""
    time_part = "?" if clock_time is None else str(clock_time)
    inc_part = "?" if clock_inc is None else str(clock_inc)
    return f"{time_part}+{inc_part}"


def _short_name(name: str) -> str:
    """Убирает технический хвост ' Arena' из fullName Lichess."""
    short = (name or "").strip()
    if short.lower().endswith(" arena"):
        short = short[: -len(" arena")].rstrip()
    return short or "Турнир"


def send_day_digest(now=None) -> bool:
    """Единый утренний дайджест: один раз в день в 10:00+ Астана."""
    now = now or datetime.now(timezone.utc)
    if not GROUP_CHAT_IDS:
        return False
    astana_now = now.astimezone(ASTANA_TZ)
    if astana_now.hour < 10:
        return False
    day_key = _today_key(now)
    conn = connect()
    try:
        if _day_digest_sent(conn, day_key):
            return False
        today_start = astana_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        utc_start = today_start.astimezone(timezone.utc)
        utc_end = today_end.astimezone(timezone.utc)
        rows = conn.execute(
            """SELECT id, name, starts_at, clock_time, clock_inc, finishes_at
               FROM tournaments
               WHERE starts_at IS NOT NULL
                 AND datetime(starts_at) >= datetime(?)
                 AND datetime(starts_at) < datetime(?)
               ORDER BY starts_at""",
            (utc_start.isoformat(), utc_end.isoformat()),
        ).fetchall()
        if not rows:
            return False
        lines = ["☀️ Доброе утро! Сегодня в клубе турниры:"]
        for tid, name, starts_at, clock_time, clock_inc, finishes_at in rows:
            start = _parse_moment(starts_at)
            if not start:
                continue
            t_label = start.astimezone(ASTANA_TZ).strftime("%H:%M")
            ctrl = _fmt_control(clock_time, clock_inc)
            dur = ""
            if finishes_at:
                fin = _parse_moment(finishes_at)
                if fin:
                    dur = f" ({round((fin - start).total_seconds() / 60)} мин)"
            link = f"https://lichess.org/tournament/{tid}"
            lines.append(f"• {t_label} — <b>{_short_name(name)}</b> [{ctrl}]{dur} — {link}")
        lines.append(f"\n🔗 Клуб: https://lichess.org/team/{CLUB_TEAM_ID}")
        lines.append("Удачных партий! ♟️")
        broadcast("\n".join(lines))
        _mark_day_digest_sent(conn, day_key)
        return True
    finally:
        conn.commit()
        conn.close()


def announce_due(now=None) -> list:
    """���?�?�'�?�?�?��?: 0 �?��' -> 1 �?�?�'�? -> 2 ���� �ؐ��? -> 3 ���� 10 �?��? -> 4 ��'�?�?��. �'�?���?�?���%����' id."""
    now = now or datetime.now(timezone.utc)
    if not GROUP_CHAT_IDS:
        return []
    conn = connect()
    # Единый утренний дайджест (раз в день)
    send_day_digest(now)
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
        club_link = f"https://lichess.org/team/{CLUB_TEAM_ID}" if CLUB_TEAM_ID else ""
        control = _fmt_control(clock_time, clock_inc)
        name = _short_name(name)
        duration = ""
        if finishes_at:
            finish = _parse_moment(finishes_at)
            if finish is not None:
                length = round((finish - start).total_seconds() / 60)
                duration = f"{length} минут"
        if not duration:
            duration = "скоротечный турнир"
        if flag == 0 and _is_announce_time(start, now):
            broadcast(render_day_announce(name, control, duration, _start_label(start).replace("сегодня в ", ""), club_link, link))
            conn.execute("UPDATE tournaments SET announced = 1 WHERE id = ?", (tournament_id,))
            touched.append(tournament_id)
        elif flag == 1 and 0 <= minutes_to_start <= 60:
            broadcast(render_announce("hour", name, control, duration, link, "через час"))
            conn.execute("UPDATE tournaments SET announced = 2 WHERE id = ?", (tournament_id,))
            touched.append(tournament_id)
        elif flag == 2 and 0 <= minutes_to_start <= ANNOUNCE_MINUTES:
            broadcast(render_reminder(name, link))
            conn.execute("UPDATE tournaments SET announced = 3 WHERE id = ?", (tournament_id,))
            touched.append(tournament_id)
        elif flag == 3:
            finish = _parse_moment(finishes_at)
            if finish is not None and now >= finish:
                # Синк ПЕРЕД итогами: иначе топ собирается по слепку
                # середины турнира (как было 16.10 с поздним блицем).
                try:
                    from backend.db.results import import_results as _import_results
                    from backend.lichess_auto.client import get_session as _get_session

                    _import_results(_get_session(), tournament_id, conn)
                except Exception:
                    pass  # Lichess недоступен — шлём то, что уже в базе
                top = conn.execute(
                    "SELECT nick, rank FROM results WHERE tournament_id=? ORDER BY rank LIMIT 3",
                    (tournament_id,),
                ).fetchall()
                if top:
                    places = "\n".join(f"{i + 1}. {nick}" for i, (nick, _) in enumerate(top))
                    broadcast(f"Итоги «{name}»:\n{places}\n{link}")
                else:
                    broadcast(f"Турнир «{name}» завершён. Результаты — в дашборде.")
                conn.execute("UPDATE tournaments SET announced = 4 WHERE id = ?", (tournament_id,))
                touched.append(tournament_id)
    conn.commit()
    conn.close()
    return touched
