"""RAG: детект языка, поиск по FAQ-корпусу, ответы LLM.

Корпусов два (RU + KK), языки не смешиваем: KZ-вопрос ищется по KZ-чанкам.
"""

import requests

from .config import LLM_API_KEY, LLM_MODEL, THRESHOLD
from .faq_base import FAQ_CHUNKS, FAQ_CHUNKS_KK

FAQ_VECTORS = None
FAQ_VECTORS_KK = None

# Буквы, которых нет в русском алфавите, — маркер казахского.
# Дешевле и точнее любой либы для нашего случая.
KZ_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")


def detect_lang(text: str) -> str:
    return "kk" if any(char in KZ_LETTERS for char in text) else "ru"


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
    """Ленивая инициализация обоих корпусов: при первом вопросе, а не на старте."""
    global FAQ_VECTORS, FAQ_VECTORS_KK
    if FAQ_VECTORS is not None and FAQ_VECTORS_KK is not None:
        return
    if not LLM_API_KEY:
        raise RuntimeError("Нет LLM_API_KEY — впиши ключ в .env и перезапусти api")
    if FAQ_VECTORS is None:
        FAQ_VECTORS = _embed([chunk["text"] for chunk in FAQ_CHUNKS])
    if FAQ_VECTORS_KK is None:
        FAQ_VECTORS_KK = _embed([chunk["text"] for chunk in FAQ_CHUNKS_KK])


def search_faq(question: str, top_k: int = 2):
    """Поиск по корпусу языка вопроса. Возвращает (хиты, язык)."""
    init_faq_vectors()
    lang = detect_lang(question)
    if lang == "kk":
        corpus, vectors = FAQ_CHUNKS_KK, FAQ_VECTORS_KK
    else:
        corpus, vectors = FAQ_CHUNKS, FAQ_VECTORS
    question_vector = _embed([question])[0]
    ranked = sorted(
        zip(corpus, vectors),
        key=lambda item: _cosine(question_vector, item[1]),
        reverse=True,
    )
    return [(chunk, _cosine(question_vector, vec)) for chunk, vec in ranked[:top_k]], lang


def llm_answer(question: str, chunks: list, lang: str = "ru") -> str:
    """Ответ по контексту (чанк есть) или честная передача человеку (нет)."""
    if lang == "kk":
        if chunks:
            context = "\n\n".join(f"[{c['title']}] {c['text']}" for c in chunks)
            system = (
                "Сен шахмат федерациясының көмекшісісің. Қазақша, қысқа жауап бер. "
                "Тек төмендегі контекст бойынша. Жауап болмаса: ҰЙЫМДАСТЫРУШЫҒА ЖІБЕРЕМІН.\n\n"
                f"Контекст:\n{context}"
            )
        else:
            system = (
                "Сен шахмат федерациясының көмекшісісің. "
                "Пайдаланушы клуб туралы емес сұрады. Сыпайы түрде тақырыптан тыс "
                "екенін айт және турнирлар туралы сұрауды ұсын. Қысқа, қазақша."
            )
    elif chunks:
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
