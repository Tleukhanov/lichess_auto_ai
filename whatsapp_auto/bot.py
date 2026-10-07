"""WhatsApp-бот федерации через WAHA: анонсы турниров + FAQ на RAG + эскалация.

Потоки:
1. POST /webhook/ — входящие от WAHA (ЛС -> RAG-ответ или эскалация человеку).
2. announce_due() — турниры через <=10 мин без флага -> ссылка+текст в группу.

RAG — наш стек (эмбеддинги OpenRouter + порог), без langchain/chroma.
Формат событий WAHA сверять с дашбордом (Device -> логи) при первом запуске:
помечены места VERIFY.

Запуск локально (до Docker):  python -m whatsapp_auto.bot
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

try:
    # Запуск из корня репо: python -m whatsapp_auto.bot
    from whatsapp_auto.faq_base import FAQ_CHUNKS
except ImportError:
    # Запуск внутри Docker (файлы лежат плоско в /app)
    from faq_base import FAQ_CHUNKS

WAHA_URL = os.environ.get("WAHA_URL", "http://localhost:3000")
WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "")
WAHA_SESSION = os.environ.get("WAHA_SESSION", "default")
GROUP_CHAT_IDS = [
    chat.strip() for chat in os.environ.get("GROUP_CHAT_IDS", "").split(",") if chat.strip()
]
if not GROUP_CHAT_IDS and os.environ.get("GROUP_CHAT_ID", ""):
    GROUP_CHAT_IDS = [os.environ["GROUP_CHAT_ID"]]  # обратная совместимость с одной группой
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")      # твой номер ...@c.us для эскалации
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")
THRESHOLD = float(os.environ.get("RAG_THRESHOLD", "0.30"))
ANNOUNCE_MINUTES = 10

ANNOUNCE_TEMPLATES = [
    "♟️ {name} уже скоро! {control}, играем {duration}. Жми: {link} 🔥",
    "Эй, шахматисты! {when} стартует «{name}» ({control}, {duration}). Кто не успел — {link} ♟️",
    "🏆 Турнир на носу: {name} — {control}, {duration}. Ссылка: {link}. Берсерк разрешён 😏",
    "Готовьте фигуры! «{name}» ({control}) начинается {when}. {link} ⏳",
]


def render_announce(template_kind: str, name: str, control: str, duration: str, link: str, when: str) -> str:
    """Случайный шаблон + подстановка. Без LLM: быстро и бесплатно."""
    import random as _random

    return _random.choice(ANNOUNCE_TEMPLATES).format(
        name=name, control=control, duration=duration, link=link, when=when
    )

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "db", "federation.db"
    ),
)

app = Flask(__name__)

FAQ_VECTORS = None


# ---------- WAHA транспорт ----------

def waha_send(chat_id: str, text: str) -> dict:
    """Отправка текста через WAHA. Возвращает ответ шлюза."""
    response = requests.post(
        f"{WAHA_URL}/api/sendText",
        headers={"X-Api-Key": WAHA_API_KEY},
        json={"chatId": chat_id, "text": text, "session": WAHA_SESSION},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def extract_message(payload: dict):
    """Достаём (chat_id, sender, text, from_me) из события WAHA.

    VERIFY: точные ключи зависят от версии WAHA — сверить с логами дашборда
    при первом входящем и поправить здесь.
    """
    chat_id = payload.get("from") or payload.get("chatId") or ""
    sender = payload.get("sender") or payload.get("participant") or chat_id
    text = (
        payload.get("body")
        or (payload.get("_data") or {}).get("Message", {}).get("conversation")
        or ""
    )
    from_me = bool(payload.get("fromMe", False))
    return chat_id, sender, (text or "").strip(), from_me


def is_group(chat_id: str) -> bool:
    return chat_id.endswith("@g.us")


# ---------- RAG (наш стек) ----------

def _embed(texts: list) -> list:
    response = requests.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json={"model": "text-embedding-3-small", "input": texts},
        timeout=60,
    )
    response.raise_for_status()
    return [item["embedding"] for item in response.json()["data"]]


def _cosine(left, right) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm_l = sum(a * a for a in left) ** 0.5
    norm_r = sum(b * b for b in right) ** 0.5
    return dot / (norm_l * norm_r) if norm_l and norm_r else 0.0


def init_faq_vectors() -> None:
    """Ленивая инициализация: при первом вопросе, а не на старте.

    Контейнер должен стартовать без сети и ключа — иначе получим
    crash-loop: упал → перезапустился → упал.
    """
    global FAQ_VECTORS
    if FAQ_VECTORS is not None:
        return
    if not LLM_API_KEY:
        raise RuntimeError("Нет LLM_API_KEY — впиши ключ в .env и перезапусти api")
    FAQ_VECTORS = _embed([chunk["text"] for chunk in FAQ_CHUNKS])


def search_faq(question: str, top_k: int = 2):
    init_faq_vectors()
    question_vector = _embed([question])[0]
    ranked = sorted(
        zip(FAQ_CHUNKS, FAQ_VECTORS),
        key=lambda item: _cosine(question_vector, item[1]),
        reverse=True,
    )
    return [(chunk, _cosine(question_vector, vec)) for chunk, vec in ranked[:top_k]]


def llm_answer(question: str, chunks: list) -> str:
    """Ответ по контексту (чанк есть) или честная передача человеку (нет)."""
    if chunks:
        context = "\n\n".join(f"[{c['title']}] {c['text']}" for c in chunks)
        system = (
            "Ты помощник шахматной федерации. Отвечай коротко и по-русски, "
            "СТРОГО по контексту ниже. Если ответа нет — напиши ровно: ПЕРЕДАЮ ОРГАНИЗАТОРУ.\n\n"
            f"Контекст:\n{context}"
        )
    else:
        system = (
            "Ты помощник шахматной федерации. Пользователь спросил не про клуб. "
            "Вежливо скажи, что это вне твоей темы, и предложи спросить про турниры. "
            "Коротко, по-русски."
        )
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "temperature": 0.0,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


# ---------- Анонсы ----------

def _db():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE tournaments ADD COLUMN announced INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # колонка уже есть
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wa_links (wa_id TEXT PRIMARY KEY, nick TEXT NOT NULL)"
    )
    return conn


def link_nick(wa_id: str, nick: str, conn) -> None:
    """Привязка WhatsApp-номера к нику Lichess: 'я tleukhanov'.

    Ники храним строчными: Lichess id всегда lowercase, а юзер пишет как попало.
    """
    clean = nick.strip().lstrip("@").lower()
    conn.execute(
        "INSERT INTO wa_links (wa_id, nick) VALUES (?, ?) "
        "ON CONFLICT(wa_id) DO UPDATE SET nick=excluded.nick",
        (wa_id, clean),
    )
    conn.commit()


def my_stats(nick: str, conn) -> str:
    """Персональная статистика из БД: тир, дельта, турниры."""
    member = conn.execute(
        "SELECT activity_tier, activity_pct FROM members WHERE nick=?", (nick,)
    ).fetchone()
    if not member:
        return "Тебя пока нет в базе клуба. Сначала вступи в клуб на Lichess."
    rows = conn.execute(
        "SELECT t.name, r.rank, r.rating_before, r.rating_after FROM results r "
        "JOIN tournaments t ON t.id = r.tournament_id WHERE r.nick=? ORDER BY t.starts_at DESC LIMIT 5",
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


def week_top(conn, limit: int = 3) -> str:
    """Топ недели: лучшие ранги (средний ранг, минимум 1 турнир)."""
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


def handle_direct_message(sender: str, text: str) -> str:
    """Команды -> персональное/RAG -> эскалация. Возвращает ответ пользователю."""
    conn = _db()
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
        conn2 = _db()
        try:
            return my_stats(row[0], conn2)
        finally:
            conn2.close()
    if lowered in ("топ", "топ недели"):
        conn2 = _db()
        try:
            return week_top(conn2)
        finally:
            conn2.close()
    if lowered in ("топ месяца", "месяц"):
        # Локальная копия backend/db/analytics.month_top: в контейнере нет backend,
        # поэтому дублируем маленькую чистую функцию (держать синхронно!).
        # Очки — сумма score Lichess, не наши баллы.
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        conn2 = _db()
        try:
            now = _dt.now(_tz.utc)
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            rows = conn2.execute(
                "SELECT r.nick, r.score, t.clock_time, t.clock_inc, t.starts_at "
                "FROM results r JOIN tournaments t ON t.id = r.tournament_id"
            ).fetchall()
            per_speed: dict = {}
            overall: dict = {}
            for nick, score, clock_time, clock_inc, starts_at in rows:
                moment = _parse_moment(starts_at)
                if moment is None or moment.replace(tzinfo=_tz.utc) < start:
                    continue
                estimate = (clock_time or 0) * 60 + (clock_inc or 0) * 40
                speed = "bullet" if estimate < 180 else ("blitz" if estimate < 600 else "rapid")
                earned = score if score is not None else 0
                per_speed.setdefault(speed, {}).setdefault(nick, 0)
                per_speed[speed][nick] += earned
                overall[nick] = overall.get(nick, 0) + earned
        finally:
            conn2.close()
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
    conn.close()
    # Записать на турнир API не умеет за другого (нужна его авторизация),
    # поэтому даём прямую ссылку — человеку остаётся один клик
    if "запиши" in lowered:
        return (
            "Самому записать тебя не могу — Lichess требует твой клик. "
            "Открой ближайший турнир из анонсов и жми «Участвовать» — ты уже в клубе."
        )
    hits = search_faq(text)
    best = hits[0][1] if hits else 0.0
    if best >= THRESHOLD:
        return llm_answer(text, [c for c, _ in hits])
    if ADMIN_CHAT_ID:
        waha_send(ADMIN_CHAT_ID, f"Вопрос от {sender} (бот не нашёл в базе):\n{text}")
    return (
        "Хороший вопрос — точного ответа в правилах клуба нет. "
        "Передал организатору, он ответит лично."
    )


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
    """Состояния флага announced: 0 нет -> 1 за час -> 2 за 10 мин -> 3 итоги отправлены.

    Тексты — случайный шаблон из ANNOUNCE_TEMPLATES, рассылка — во все группы.
    Возвращает id затронутых. Без групп — молча пропускаем.
    """
    now = now or datetime.now(timezone.utc)
    if not GROUP_CHAT_IDS:
        return []
    conn = _db()
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
            for chat_id in GROUP_CHAT_IDS:
                waha_send(chat_id, render_announce("hour", name, control, duration, link, "через час"))
            conn.execute("UPDATE tournaments SET announced = 1 WHERE id = ?", (tournament_id,))
            touched.append(tournament_id)
        elif flag == 1 and 0 <= minutes_to_start <= ANNOUNCE_MINUTES:
            for chat_id in GROUP_CHAT_IDS:
                waha_send(chat_id, render_announce("ten", name, control, duration, link, "через 10 минут"))
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
                    for chat_id in GROUP_CHAT_IDS:
                        waha_send(chat_id, f"Итоги «{name}»:\n{places}\n{link}")
                else:
                    for chat_id in GROUP_CHAT_IDS:
                        waha_send(chat_id, f"Турнир «{name}» завершён. Результаты — в дашборде.")
                conn.execute("UPDATE tournaments SET announced = 3 WHERE id = ?", (tournament_id,))
                touched.append(tournament_id)
    conn.commit()
    conn.close()
    return touched


# ---------- Webhook ----------

@app.post("/webhook/")
def webhook():
    """Входящее событие WAHA: ЛС -> бот, группы -> игнор."""
    event = request.get_json(force=True, silent=True) or {}
    payload = event.get("payload", event)
    chat_id, sender, text, from_me = extract_message(payload)
    if from_me or not text or is_group(chat_id):
        return jsonify({"ok": True, "skipped": True})
    reply = handle_direct_message(sender, text)
    waha_send(chat_id, reply)
    return jsonify({"ok": True})


@app.get("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
