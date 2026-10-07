"""Точка входа: Flask (вебхук WAHA) + cron-эндпоинт для анонсов."""

import os
import sys

import logging

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

from whatsapp_auto.announce import announce_due
from whatsapp_auto.commands import handle_direct_message
from whatsapp_auto.waha import extract_message, is_group

app = Flask(__name__)


@app.post("/webhook/")
def webhook():
    """Входящее событие WAHA: ЛС -> бот, группы -> игнор. Голосовые -> в текст."""
    event = request.get_json(force=True, silent=True) or {}
    payload = event.get("payload", event)
    chat_id, sender, text, from_me = extract_message(payload)
    if from_me or is_group(chat_id):
        return jsonify({"ok": True, "skipped": True})
    if not text and isinstance(payload.get("media"), dict):
        # Голосовое (или аудио): media.url есть, текста нет — транскрибируем
        from whatsapp_auto.voice import voice_to_text

        text = voice_to_text(payload.get("media"))
    if not text:
        return jsonify({"ok": True, "skipped": True})
    reply = handle_direct_message(sender, text)
    from whatsapp_auto.waha import waha_send

    waha_send(chat_id, reply)
    return jsonify({"ok": True})


@app.post("/cron/announce")
def cron_announce():
    """Дёргать по расписанию (cron/планировщик): анонсы + итоги."""
    touched = announce_due()
    return jsonify({"ok": True, "touched": touched})


@app.get("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
