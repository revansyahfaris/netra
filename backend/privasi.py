"""Penyamaran akun media sosial pada keluaran API publik.

Rulebook Kartika Cyber Hackathon 2026 melarang karya memuat data pribadi pihak ketiga
tanpa izin. Klaim nyata yang diuji tim berasal dari akun X pribadi, jadi nama akun
disamarkan sebelum data keluar dari API. Data di database tetap utuh agar pipeline bisa
bekerja; penyamaran hanya terjadi pada respons.

- https://x.com/<akun>/status/<id> menjadi https://x.com/i/status/<id> (tautan tetap jalan)
- @akun di teks bebas menjadi @akun
- uploader kandidat berjenis "pribadi" menjadi "Akun pribadi"

Matikan dengan SAMARKAN_AKUN=0.
"""

from __future__ import annotations

import re
from typing import Any

_URL_X = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(?!i/)[A-Za-z0-9_]{1,30}/status(?:es)?/(\d+)[^\s\"'<>)]*",
    re.IGNORECASE,
)
_HANDLE = re.compile(r"(?<![\w.@/])@[A-Za-z0-9_]{2,30}\b")


def samarkan_teks(teks: str) -> str:
    teks = _URL_X.sub(lambda m: f"https://x.com/i/status/{m.group(1)}", teks)
    return _HANDLE.sub("@akun", teks)


def samarkan(data: Any) -> Any:
    """Salinan data dengan akun pribadi disamarkan. Menerima dict, list, atau str."""
    if isinstance(data, str):
        return samarkan_teks(data)
    if isinstance(data, list):
        return [samarkan(x) for x in data]
    if isinstance(data, dict):
        hasil = {k: samarkan(v) for k, v in data.items()}
        if hasil.get("jenis_sumber") == "pribadi" and hasil.get("uploader"):
            hasil["uploader"] = "Akun pribadi"
        return hasil
    return data
