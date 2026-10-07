"""Голосовые: скачивание из WAHA + транскрибация faster-whisper (локально).

Цепочка: media.url из события -> GET (с API-ключом, localhost меняем на waha) ->
временный .oga -> текст -> общий пайплайн как обычное сообщение.
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


def download_audio(media_url: str) -> str:
    """Скачивает аудио во временный файл. Возвращает путь."""
    url = media_url.replace("http://localhost:3000", WAHA_URL)
    response = requests.get(
        url, headers={"X-Api-Key": WAHA_API_KEY}, timeout=120
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


def voice_to_text(media: dict) -> str:
    """media из события WAHA -> текст (с чисткой временного файла)."""
    url = (media or {}).get("url", "")
    if not url:
        return ""
    path = download_audio(url)
    try:
        return transcribe(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
