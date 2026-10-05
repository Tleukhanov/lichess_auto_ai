"""Недельный отчёт аналитика: эта неделя vs прошлая.

Что показывает: турниры, участники, новички, тиры активности,
средняя дельта рейтинга, берсерки. Пустые недели — тоже отчёт
(нули честно, а не молчание).

Запуск из корня проекта:
    python -m backend.db.weekly
Отчёт дублируется в reports/weekly_YYYY-Www.md (папка локальная, в git не едет).
"""

import os
import sqlite3
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.db.analytics import (
    _parse_moment,
    backfill_ratings,
    migrate,
    refresh_activity,
    week_bounds,
)
from backend.db.members import DB_PATH, init_db
from backend.db.results import import_results, snapshot_tournaments
from backend.lichess_auto.client import get_session

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "reports",
)


def _week_key(monday) -> str:
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def build_report(conn: sqlite3.Connection, offset_weeks: int = 0) -> str:
    """Текст отчёта за неделю (0 — текущая, 1 — прошлая)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    monday, sunday_end = week_bounds(now)
    monday = monday - timedelta(weeks=offset_weeks)
    sunday_end = sunday_end - timedelta(weeks=offset_weeks)

    tournaments = [
        (row[0], row[1], _parse_moment(row[2]))
        for row in conn.execute("SELECT id, name, starts_at FROM tournaments")
    ]
    in_week = [(t, n) for t, n, moment in tournaments if moment and monday <= moment <= sunday_end]

    lines = [f"# Неделя {_week_key(monday)} ({monday.date()} — {sunday_end.date()})", ""]
    if not in_week:
        lines.append("Турниров не было. Тишина — тоже данные.")
        return "\n".join(lines)

    lines.append(f"Турниров: {len(in_week)}")
    total_players = set()
    deltas = []
    berserks = []
    newcomers = []
    for tournament_id, name in in_week:
        rows = conn.execute(
            "SELECT nick, rank, rating_before, rating_after, berserk_pct FROM results "
            "WHERE tournament_id=?",
            (tournament_id,),
        ).fetchall()
        lines.append(f"\n## {name}")
        lines.append(f"Участников: {len(rows)}")
        for nick, rank, before, after, berserk in rows:
            total_players.add(nick)
            known_before = conn.execute(
                "SELECT COUNT(*) FROM results WHERE nick=? AND tournament_id != ?",
                (nick, tournament_id),
            ).fetchone()[0]
            if known_before == 0:
                newcomers.append(nick)
            if before is not None and after is not None:
                deltas.append(after - before)
            if berserk is not None:
                berserks.append(berserk)
            extra = " (новичок клуба в турнирах)" if known_before == 0 else ""
            lines.append(f"- #{rank} {nick}{extra}")

    lines.append(f"\nУникальных участников за неделю: {len(total_players)}")
    if newcomers:
        lines.append("Новички: " + ", ".join(sorted(set(newcomers))))
    if deltas:
        lines.append(
            f"Средняя дельта рейтинга: {sum(deltas) / len(deltas):+.1f} "
            f"(медиана: {sorted(deltas)[len(deltas) // 2]:+d})"
        )
    if berserks:
        lines.append(f"Средний % берсерков: {sum(berserks) / len(berserks):.1f}%")
    tiers = conn.execute(
        "SELECT activity_tier, COUNT(*) FROM members GROUP BY activity_tier"
    ).fetchall()
    lines.append("Тиры: " + ", ".join(f"{tier}={count}" for tier, count in tiers))
    return "\n".join(lines)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    username = os.environ["LICHESS_USERNAME"]
    session = get_session()
    conn = init_db()
    migrate(conn)
    snapshot_tournaments(session, username, conn)
    for (tournament_id,) in conn.execute("SELECT id FROM tournaments"):
        import_results(session, tournament_id, conn)
    backfill_ratings(conn)
    summary = refresh_activity(conn)
    print("активность:", summary)
    report = build_report(conn)
    print("\n" + report)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    from datetime import datetime, timezone

    monday, _ = week_bounds(datetime.now(timezone.utc))
    path = os.path.join(REPORTS_DIR, f"weekly_{_week_key(monday)}.md")
    with open(path, "w", encoding="utf-8") as report_file:
        report_file.write(report + "\n")
    print(f"\nсохранено: {path}")
    conn.close()


if __name__ == "__main__":
    main()
