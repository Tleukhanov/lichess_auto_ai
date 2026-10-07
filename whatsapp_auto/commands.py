"""Команды бота: привязка, стата, топы, запись + RAG/эскалация на остальное."""

from .config import ADMIN_CHAT_ID, THRESHOLD
from .db_store import connect, link_nick, my_stats, week_top
from .rag import llm_answer, search_faq
from .waha import waha_send


def month_top_text(conn) -> str:
    """Топ месяца по очкам Lichess (дубль backend/db/analytics: в контейнере нет backend)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = conn.execute(
        "SELECT r.nick, r.score, t.clock_time, t.clock_inc, t.starts_at "
        "FROM results r JOIN tournaments t ON t.id = r.tournament_id"
    ).fetchall()
    per_speed: dict = {}
    overall: dict = {}
    for nick, score, clock_time, clock_inc, starts_at in rows:
        from .announce import _parse_moment

        moment = _parse_moment(starts_at)
        if moment is None or moment.replace(tzinfo=timezone.utc) < start:
            continue
        estimate = (clock_time or 0) * 60 + (clock_inc or 0) * 40
        speed = "bullet" if estimate < 180 else ("blitz" if estimate < 600 else "rapid")
        earned = score if score is not None else 0
        per_speed.setdefault(speed, {}).setdefault(nick, 0)
        per_speed[speed][nick] += earned
        overall[nick] = overall.get(nick, 0) + earned
    if not overall:
        return "В этом месяце пока пусто — играйте турниры!"
    names = {"rapid": "Рапид", "blitz": "Блиц", "bullet": "Пуля"}
    lines = ["Топ месяца (очки Lichess):"]
    for speed in ("rapid", "blitz", "bullet"):
        if speed in per_speed:
            top = sorted(per_speed[speed].items(), key=lambda item: item[1], reverse=True)[:5]
            lines.append(names[speed] + ": " + ", ".join(f"{n} ({p})" for n, p in top))
    top_all = sorted(overall.items(), key=lambda item: item[1], reverse=True)[:5]
    lines.append("Общий: " + ", ".join(f"{n} ({p})" for n, p in top_all))
    return "\n".join(lines)


def handle_direct_message(sender: str, text: str) -> str:
    """Маршрутизация: команды -> персональное/RAG -> эскалация."""
    conn = connect()
    lowered = text.strip().lower()
    if lowered.startswith("я "):
        link_nick(sender, text.strip()[2:], conn)
        conn.close()
        return "Запомнил твой ник! Теперь команда «стата» покажет твои результаты."
    if lowered in ("стата", "статистика", "моя стата"):
        row = conn.execute("SELECT nick FROM wa_links WHERE wa_id=?", (sender,)).fetchone()
        conn.close()
        if not row:
            return "Сначала представься: напиши «я твой_ник_на_lichess»."
        conn2 = connect()
        try:
            return my_stats(row[0], conn2)
        finally:
            conn2.close()
    if lowered in ("топ", "топ недели"):
        try:
            return week_top(conn)
        finally:
            conn.close()
    if lowered in ("топ месяца", "месяц"):
        try:
            return month_top_text(conn)
        finally:
            conn.close()
    conn.close()
    # Записать на турнир API не умеет за другого (нужна его авторизация),
    # поэтому даём прямую ссылку — человеку остаётся один клик
    if "запиши" in lowered:
        return (
            "Самому записать тебя не могу — Lichess требует твой клик. "
            "Открой ближайший турнир из анонсов и жми «Участвовать» — ты уже в клубе."
        )
    hits, lang = search_faq(text)
    best = hits[0][1] if hits else 0.0
    if best >= THRESHOLD:
        return llm_answer(text, [c for c, _ in hits], lang)
    if ADMIN_CHAT_ID:
        waha_send(ADMIN_CHAT_ID, f"Вопрос от {sender} [{lang}] (бот не нашёл в базе):\n{text}")
    if lang == "kk":
        return (
            "Жақсы сұрақ — клуб ережелерінде нақты жауап жоқ. "
            "Ұйымдастырушыға жібердім, ол жеке жауап береді."
        )
    return (
        "Хороший вопрос — точного ответа в правилах клуба нет. "
        "Передал организатору, он ответит лично."
    )
