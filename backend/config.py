"""Konfigurasi dari environment (.env).

Kalau API key kosong, modul otomatis memakai mode demo (data contoh),
jadi API tetap bisa jalan dan didemokan tanpa key.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
STT_BASE_URL = os.getenv("STT_BASE_URL", "http://localhost:8100").rstrip("/")
STT_API_KEY = os.getenv("STT_API_KEY", "")
STT_MODEL = os.getenv("STT_MODEL", "deepdml/faster-whisper-large-v3-turbo-ct2")

DATA_DIR = BASE_DIR / "data"
DUMMY_DIR = DATA_DIR / "dummy"
WORK_DIR = DATA_DIR / "work"  # tempat unduhan video & frame sementara

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))
STT_TIMEOUT = float(os.getenv("STT_TIMEOUT", "180"))


def llm_aktif() -> bool:
    return bool(GEMINI_API_KEY)


def search_aktif() -> bool:
    return bool(SERPAPI_KEY)


def stt_aktif() -> bool:
    return bool(STT_BASE_URL)


def db_aktif() -> bool:
    return bool(DATABASE_URL)
