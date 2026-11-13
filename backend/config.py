"""Konfigurasi dari environment (.env).

Kalau API key kosong, modul otomatis memakai mode demo (data contoh),
jadi API tetap bisa jalan dan didemokan tanpa key.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

def _key(nama: str) -> str:
    """API key tidak pernah mengandung spasi: buang spasi dan teks tambahan yang ikut tertulis."""
    nilai = os.getenv(nama, "").strip().strip('"').strip("'")
    return nilai.split()[0] if nilai else ""


GEMINI_API_KEY = _key("GEMINI_API_KEY")
# Model ringan untuk prioritas & pembuatan query (modul Faris)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
# Model untuk OCR, perbandingan & klarifikasi (modul Adriel). Default sama dengan GEMINI_MODEL.
GEMINI_MODEL_VERIFIKASI = os.getenv("GEMINI_MODEL_VERIFIKASI", "") or GEMINI_MODEL
SERPAPI_KEY = _key("SERPAPI_KEY")
# Postgres (Neon). Kosong = simpan di memori.
DATABASE_URL = _key("DATABASE_URL")

DATA_DIR = BASE_DIR / "data"
DUMMY_DIR = DATA_DIR / "dummy"
WORK_DIR = DATA_DIR / "work"  # tempat unduhan video & frame sementara

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))


def llm_aktif() -> bool:
    return bool(GEMINI_API_KEY)


def search_aktif() -> bool:
    return bool(SERPAPI_KEY)

# Awalan nama tabel milik backend, supaya tidak bentrok dengan tabel lain di database yang sama
TABLE_PREFIX = os.getenv("TABLE_PREFIX", "netra_api_")
