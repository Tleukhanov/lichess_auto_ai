"""Ошибки и живучесть запросов к Lichess."""

import time

import requests


class TournamentError(Exception):
    """Постоянная ошибка API: дальше долбиться бессмысленно."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Lichess_{status_code}: {message}")


# Временные: чихнули — подождали — повторили
_RETRYABLE = {429, 500, 502, 503, 504}

# Постоянные обрабатываем сразу, без ретраев:
# 400 — кривые параметры (сам не починится), 401 — токен, 404 — нет URL


def post_with_retry(session, url: str, data: dict, tries: int = 3) -> dict:
    """POST с ретраями временных ошибок. Возвращает распарсенный JSON."""
    last_error = None
    for attempt in range(tries):
        try:
            response = session.post(url, data=data, timeout=30)
        except requests.ConnectionError as error:
            last_error = error  # обрыв сети = временная, повторяем
        else:
            if response.status_code in _RETRYABLE:
                last_error = TournamentError(response.status_code, response.text[:200])
            elif response.status_code >= 400:
                raise TournamentError(response.status_code, response.text[:200])
            else:
                return response.json()
        time.sleep(2 ** attempt)  # паузы: 1с, 2с, 4с
    raise TournamentError(0, f"Не дождались ответа за {tries} попытки: {last_error}")
