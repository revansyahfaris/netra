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
# Model ringan untuk prioritas, pembuatan query & format draf klarifikasi
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
# Model untuk OCR & perbandingan fakta Tahap 4 (modul Adriel). Default sama dengan GEMINI_MODEL.
GEMINI_MODEL_VERIFIKASI = os.getenv("GEMINI_MODEL_VERIFIKASI", "") or GEMINI_MODEL
# Tingkat reasoning Tahap 4 Cross-Verification (minimal / low / medium / high)
GEMINI_THINKING_VERIFIKASI = os.getenv("GEMINI_THINKING_VERIFIKASI", "low").strip().lower() or "low"
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
SERPAPI_KEY = _key("SERPAPI_KEY")
# Postgres (Neon). Kosongkan untuk memakai SQLite lokal (backend/data/netra.db)
DATABASE_URL = _key("DATABASE_URL")

# Layanan Speech-to-Text (Whisper/speaches, API kompatibel OpenAI)
STT_BASE_URL = os.getenv("STT_BASE_URL", "http://localhost:8100").rstrip("/")
STT_API_KEY = _key("STT_API_KEY")
STT_MODEL = os.getenv("STT_MODEL", "deepdml/faster-whisper-large-v3-turbo-ct2")
# Isi data demo otomatis saat database masih kosong
SEED_KALAU_KOSONG = os.getenv("SEED_KALAU_KOSONG", "1") != "0"
# Izinkan POST /seed (reset data demo). Matikan saat dipakai sungguhan.
IZINKAN_SEED = os.getenv("IZINKAN_SEED", "1") != "0"
# Pengaman link publik: batas proses live (pencarian/verifikasi berbayar) per hari, 0 = tanpa batas.
BATAS_PROSES_HARIAN = int(os.getenv("BATAS_PROSES_HARIAN", "0") or 0)
# Jeda minimal sebelum klaim yang sama boleh diproses ulang (menit), 0 = tanpa jeda.
JEDA_PROSES_ULANG_MENIT = int(os.getenv("JEDA_PROSES_ULANG_MENIT", "0") or 0)
# Ikut muat kasus nyata (data/kasus_nyata) saat seed. Menyebut peristiwa & pejabat nyata.
DEMO_KASUS_NYATA = os.getenv("DEMO_KASUS_NYATA", "0") == "1"

DATA_DIR = BASE_DIR / "data"
DUMMY_DIR = DATA_DIR / "dummy"
KASUS_NYATA_DIR = DATA_DIR / "kasus_nyata"
WORK_DIR = DATA_DIR / "work"  # tempat unduhan video & frame sementara

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))
STT_TIMEOUT = float(os.getenv("STT_TIMEOUT", "180"))

# URL publik backend ini (mis. route Cloudflare Tunnel https://api.contoh.id). Dipakai untuk
# membagikan keyframe video ke Google Lens lewat GET /media-sementara/{token}. Kosong = Lens video mati.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
# Kunci tanda tangan token media sementara. Kosong = kunci acak per proses (token hilang saat restart).
MEDIA_SECRET = _key("MEDIA_SECRET")
MEDIA_TTL_DETIK = int(os.getenv("MEDIA_TTL_DETIK", "900"))
# Pakai lapisan AI penuh (Tahap 1 -> pencarian -> Tahap 2/3 -> Tahap 4 -> Tahap 5) di /pipeline & /verifikasi.
# 0 = pakai verifikasi deterministik lama (untuk demo tanpa API key / tes).
PIPELINE_AI = os.getenv("PIPELINE_AI", "1") != "0"
# Indeks just-in-time kandidat Tier-2 (beda angle, sumber kredibel) ke pgvector cakupan 'temuan'.
JIT_TIER2 = os.getenv("JIT_TIER2", "1") != "0"


def llm_aktif() -> bool:
    return bool(GEMINI_API_KEY)


def search_aktif() -> bool:
    return bool(SERPAPI_KEY)


def stt_aktif() -> bool:
    return bool(STT_BASE_URL)


def db_aktif() -> bool:
    return bool(DATABASE_URL)
