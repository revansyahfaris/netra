"""Pastikan tes tidak menyentuh database sungguhan.

Harus dieksekusi sebelum modul apa pun mengimpor `config`.
"""

import os

os.environ["DATABASE_URL"] = ""
os.environ["SEED_KALAU_KOSONG"] = "0"
os.environ["IZINKAN_SEED"] = "1"