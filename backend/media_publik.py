"""Tautan publik sementara untuk file kerja lokal (keyframe video).

Google Lens (SerpAPI) hanya menerima URL gambar yang bisa diakses publik. Keyframe hasil Tahap 1
tersimpan di `WORK_DIR`, jadi modul ini menerbitkan token bertanda tangan HMAC dengan masa berlaku
pendek. Token hanya bisa membuka file gambar di dalam `WORK_DIR`; isi token tidak bisa diubah tanpa
kunci, dan endpoint `GET /media-sementara/{token}` menolak token kedaluwarsa.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from pathlib import Path

import config

EKSTENSI_DIIZINKAN = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_KUNCI_PROSES = secrets.token_bytes(32)


class TokenTidakSah(Exception):
    pass


def _kunci() -> bytes:
    return config.MEDIA_SECRET.encode("utf-8") if config.MEDIA_SECRET else _KUNCI_PROSES


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


def _tanda_tangan(payload: bytes) -> str:
    return _b64(hmac.new(_kunci(), payload, hashlib.sha256).digest()[:18])


def aktif() -> bool:
    return bool(config.PUBLIC_BASE_URL)


def buat_token(path: Path, ttl_detik: int | None = None, sekarang: float | None = None) -> str:
    akar = config.WORK_DIR.resolve()
    target = Path(path).resolve()
    try:
        relatif = target.relative_to(akar)
    except ValueError as e:
        raise TokenTidakSah("File berada di luar WORK_DIR") from e
    if target.suffix.lower() not in EKSTENSI_DIIZINKAN:
        raise TokenTidakSah(f"Ekstensi {target.suffix} tidak diizinkan")
    kedaluwarsa = int((sekarang or time.time()) + (ttl_detik or config.MEDIA_TTL_DETIK))
    payload = f"{relatif.as_posix()}|{kedaluwarsa}".encode("utf-8")
    return f"{_b64(payload)}.{_tanda_tangan(payload)}"


def terbitkan_url(path: Path, ttl_detik: int | None = None) -> str | None:
    """URL publik sementara untuk file di WORK_DIR, atau None bila PUBLIC_BASE_URL belum diisi."""
    if not aktif():
        return None
    return f"{config.PUBLIC_BASE_URL}/media-sementara/{buat_token(path, ttl_detik)}"


def buka_token(token: str, sekarang: float | None = None) -> tuple[Path, str]:
    """Validasi token lalu kembalikan (path file, mime type)."""
    try:
        bagian_payload, tanda = token.split(".", 1)
        payload = _unb64(bagian_payload)
    except (ValueError, TypeError) as e:
        raise TokenTidakSah("Format token salah") from e
    if not hmac.compare_digest(_tanda_tangan(payload), tanda):
        raise TokenTidakSah("Tanda tangan token tidak cocok")
    try:
        relatif, kedaluwarsa = payload.decode("utf-8").rsplit("|", 1)
        batas = int(kedaluwarsa)
    except (UnicodeDecodeError, ValueError) as e:
        raise TokenTidakSah("Isi token rusak") from e
    if (sekarang or time.time()) > batas:
        raise TokenTidakSah("Token kedaluwarsa")

    akar = config.WORK_DIR.resolve()
    target = (akar / relatif).resolve()
    try:
        target.relative_to(akar)
    except ValueError as e:
        raise TokenTidakSah("Path keluar dari WORK_DIR") from e
    mime = EKSTENSI_DIIZINKAN.get(target.suffix.lower())
    if mime is None or not target.is_file():
        raise TokenTidakSah("File tidak ditemukan")
    return target, mime
