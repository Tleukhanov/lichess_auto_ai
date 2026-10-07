"""Транспорт WAHA: отправка сообщений и разбор входящих событий."""

import requests

from .config import WAHA_API_KEY, WAHA_SESSION, WAHA_URL


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
