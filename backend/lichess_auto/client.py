"""HTTP-клиент Lichess API.

Токен берётся из корневого .env (LICHESS_TOKEN) — один файл на весь проект.
Запуск скриптов — из корня проекта, чтобы load_dotenv нашёл .env.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://lichess.org"


def get_session() -> requests.Session:
    token = os.environ["LICHESS_TOKEN"]
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    return session
