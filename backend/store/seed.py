"""Isi data demo ke database.

Dipakai saat startup (kalau database kosong) dan oleh POST /seed.
Idempoten: klaim yang sama tidak diduplikasi.
"""

from __future__ import annotations

import json
import logging

import config
from priority import hitung_prioritas
from schemas import Klaim

from .repo import Repo

log = logging.getLogger("netra.store.seed")


def muat_klaim(repo: Repo) -> list[Klaim]:
    f = config.DUMMY_DIR / "klaim.json"
    if not f.exists():
        return []
    hasil = []
    for item in json.loads(f.read_text(encoding="utf-8")):
        k = hitung_prioritas(Klaim.model_validate(item))
        repo.simpan_klaim(k, aktor="seed")
        hasil.append(k)
    return hasil


def seed_kalau_kosong(repo: Repo) -> int:
    """Isi data demo hanya kalau belum ada klaim sama sekali."""
    if repo.daftar_klaim():
        return 0
    klaim = muat_klaim(repo)
    log.info("Seed: %d klaim demo dimuat", len(klaim))
    return len(klaim)


def seed_ulang(repo: Repo) -> int:
    repo.hapus_semua()
    klaim = muat_klaim(repo)
    log.info("Seed ulang: %d klaim demo dimuat", len(klaim))
    return len(klaim)