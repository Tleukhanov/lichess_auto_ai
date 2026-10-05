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
WAHA_SESSION = os.environ.get("WAHA_SESSION", "default")
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")      # 12345@g.us — вписать после подключения
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")      # твой номер ...@c.us для эскалации
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")
THRESHOLD = float(os.environ.get("RAG_THRESHOLD", "0.30"))
ANNOUNCE_MINUTES = 10

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "db", "federation.db"
)

app = Flask(__name__)

FAQ_VECTORS = None


# ---------- WAHA транспорт ----------

def waha_send(chat_id: str, text: str) -> dict:
    """Отправка текста через WAHA. Возвращает ответ шлюза."""
    response = requests.post(
        f"{WAHA_URL}/api/sendText",
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


def handle_direct_message(sender: str, text: str) -> str:
    """ЛС: RAG-ответ или эскалация. Возвращает текст ответа пользователю."""
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


# ---------- Анонсы ----------

def _db():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE tournaments ADD COLUMN announced INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # колонка уже есть
    return conn


def announce_due(now=None) -> list:
    """Турниры стартующие в ближайшие ANNOUNCE_MINUTES без флага -> анонс в группу.

    Возвращает id анонсированных. Без GROUP_CHAT_ID — молча пропускаем.
    """
    now = now or datetime.now(timezone.utc)
    if not GROUP_CHAT_ID:
        return []
    conn = _db()
    announced_ids = []
    for row in conn.execute(
        "SELECT id, name, starts_at FROM tournaments WHERE COALESCE(announced, 0) = 0"
    ):
        tournament_id, name, starts_at = row
        try:
            start = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        delta = (start - now).total_seconds() / 60
        if 0 <= delta <= ANNOUNCE_MINUTES:
            link = f"https://lichess.org/tournament/{tournament_id}"
            waha_send(
                GROUP_CHAT_ID,
                f"До турнира «{name}» осталось 10 минут!\nЗаходи: {link}",
            )
            conn.execute("UPDATE tournaments SET announced = 1 WHERE id = ?", (tournament_id,))
            announced_ids.append(tournament_id)
    conn.commit()
    conn.close()
    return announced_ids


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
