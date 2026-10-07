"""Все настройки бота из окружения — в одном месте."""

import os

WAHA_URL = os.environ.get("WAHA_URL", "http://localhost:3000")
WAHA_API_KEY = os.environ.get("WAHA_API_KEY", "")
WAHA_SESSION = os.environ.get("WAHA_SESSION", "default")

GROUP_CHAT_IDS = [
    chat.strip() for chat in os.environ.get("GROUP_CHAT_IDS", "").split(",") if chat.strip()
]
if not GROUP_CHAT_IDS and os.environ.get("GROUP_CHAT_ID", ""):
    GROUP_CHAT_IDS = [os.environ["GROUP_CHAT_ID"]]  # обратная совместимость с одной группой

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

CLUB_TEAM_ID = os.environ.get("CLUB_TEAM_ID", "")  # id клуба для ссылки вступления

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")
THRESHOLD = float(os.environ.get("RAG_THRESHOLD", "0.30"))

ANNOUNCE_MINUTES = 10

DB_PATH = os.environ.get("DB_PATH", "")
