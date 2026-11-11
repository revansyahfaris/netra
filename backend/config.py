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
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

DATA_DIR = BASE_DIR / "data"
DUMMY_DIR = DATA_DIR / "dummy"
WORK_DIR = DATA_DIR / "work"  # tempat unduhan video & frame sementara

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))


def llm_aktif() -> bool:
    return bool(GEMINI_API_KEY)


def search_aktif() -> bool:
    return bool(SERPAPI_KEY)
