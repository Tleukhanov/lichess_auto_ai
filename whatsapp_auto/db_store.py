"""Данные федерации: привязки WA → nick, персональная статистика, топы."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import DB_PATH

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "db", "federation.db"
)


def db_path() -> str:
    return DB_PATH or DEFAULT_DB_PATH


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    try:
        conn.execute("ALTER TABLE tournaments ADD COLUMN announced INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # колонка уже есть
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wa_links (wa_id TEXT PRIMARY KEY, nick TEXT NOT NULL)"
    )
    return conn


def link_nick(wa_id: str, nick: str, conn: sqlite3.Connection) -> None:
    """Привязка WhatsApp-номера к нику Lichess. Ники храним строчными."""
    clean = nick.strip().lstrip("@").lower()
    conn.execute(
        "INSERT INTO wa_links (wa_id, nick) VALUES (?, ?) "
        "ON CONFLICT(wa_id) DO UPDATE SET nick=excluded.nick",
        (wa_id, clean),
    )
    conn.commit()


def my_stats(nick: str, conn: sqlite3.Connection) -> str:
    """Персональная статистика: тир, последние турниры с дельтами."""
    member = conn.execute(
        "SELECT activity_tier, activity_pct FROM members WHERE nick=?", (nick,)
    ).fetchone()
    if not member:
        return "Тебя пока нет в базе клуба. Сначала вступи в клуб на Lichess."
    rows = conn.execute(
        "SELECT t.name, r.rank, r.rating_before, r.rating_after FROM results r "
        "JOIN tournaments t ON t.id = r.tournament_id WHERE r.nick=? "
        "ORDER BY t.starts_at DESC LIMIT 5",
        (nick,),
    ).fetchall()
    tier, pct = member
    lines = [f"Тир активности: {tier} ({pct:.0%} турниров)."]
    for name, rank, before, after in rows:
        delta = f" ({after - before:+d})" if before is not None and after is not None else ""
        lines.append(f"• {name}: #{rank}{delta}")
    if not rows:
        lines.append("Турниров пока не играл — всё впереди.")
    return "\n".join(lines)


def week_top(conn: sqlite3.Connection, limit: int = 3) -> str:
    """Топ недели по среднему рангу."""
    rows = conn.execute(
        "SELECT nick, COUNT(*), AVG(rank) FROM results "
        "WHERE tournament_id IN (SELECT id FROM tournaments "
        "WHERE starts_at >= date('now', '-7 days')) "
        "GROUP BY nick ORDER BY AVG(rank) LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "На этой неделе турниров с участниками пока не было."
    return "Топ недели:\n" + "\n".join(
        f"{i + 1}. {nick} — средний ранг {avg:.1f} ({count} тур.)"
        for i, (nick, count, avg) in enumerate(rows)
    )
