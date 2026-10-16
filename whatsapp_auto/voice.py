"""Голосовые: скачивание из WAHA + транскрибация faster-whisper (локально).

Важно: событие вебхука НЕ содержит ссылку на файл (только флаг),
поэтому медиа докачиваем отдельным запросом downloadMedia по id сообщения.
"""

import os
import tempfile

import requests

from .config import WAHA_API_KEY, WAHA_SESSION, WAHA_URL

_model = None


def _get_model():
    """Ленивая загрузка: модель ~500МБ тянется при первом голосовом, дальше из кэша."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def download_audio(chat_id: str, message_id: str) -> str:
    """Скачивает голосовое во временный файл. Возвращает путь."""
    response = requests.get(
        f"{WAHA_URL}/api/{WAHA_SESSION}/chats/{chat_id}/messages/{message_id}",
        headers={"X-Api-Key": WAHA_API_KEY},
        params={"downloadMedia": "true"},
        timeout=120,
    )
    response.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=".oga", delete=False)
    tmp.write(response.content)
    tmp.close()
    return tmp.name


def transcribe(path: str) -> str:
    """Аудио -> текст. Язык определяем авто, дальше детектим по буквам."""
    segments, _ = _get_model().transcribe(path, language=None)
    return " ".join(segment.text.strip() for segment in segments).strip()


def voice_to_text(chat_id: str, message_id: str) -> str:
    """Голосовое -> текст (с чисткой временного файла)."""
    path = download_audio(chat_id, message_id)
    try:
        return transcribe(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    path = download_audio(url)
    try:
        return transcribe(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
