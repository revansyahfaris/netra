"""Tes selalu jalan dalam mode demo: tanpa memanggil Gemini/SerpAPI sungguhan
(supaya tidak memakai saldo & kuota) dan tanpa menyentuh database Neon.

Variabel diset kosong SEBELUM config dimuat; load_dotenv tidak menimpa variabel
yang sudah ada, jadi isi .env diabaikan selama tes.
"""

import os

for _nama in ("GEMINI_API_KEY", "SERPAPI_KEY", "DATABASE_URL"):
    os.environ[_nama] = ""

import config  # noqa: E402

assert not config.GEMINI_API_KEY and not config.SERPAPI_KEY and not config.DATABASE_URL
