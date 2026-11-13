"""Tes selalu jalan dalam mode demo dan tidak menyentuh database sungguhan.

Variabel diset SEBELUM config dimuat; load_dotenv tidak menimpa variabel yang sudah ada,
jadi isi .env diabaikan selama tes (tidak memakai saldo Gemini/kuota SerpAPI, tidak menyentuh Neon).
"""

import os

for _nama in ("GEMINI_API_KEY", "SERPAPI_KEY", "DATABASE_URL"):
    os.environ[_nama] = ""
os.environ["SEED_KALAU_KOSONG"] = "0"
os.environ["IZINKAN_SEED"] = "1"
os.environ["DEMO_KASUS_NYATA"] = "0"

import config  # noqa: E402

assert not config.GEMINI_API_KEY and not config.SERPAPI_KEY and not config.DATABASE_URL
