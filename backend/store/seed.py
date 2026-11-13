"""Isi data demo ke database.

Dipakai saat startup (kalau database kosong) dan oleh POST /seed.
Idempoten: klaim yang sama tidak diduplikasi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import config
from priority import hitung_prioritas
from schemas import Klaim

from .repo import Repo

log = logging.getLogger("netra.store.seed")


def _file_klaim() -> list:
    berkas = [config.DUMMY_DIR / "klaim.json"]
    if config.DEMO_KASUS_NYATA:
        berkas.append(config.KASUS_NYATA_DIR / "klaim.json")
    return [f for f in berkas if f.exists()]


def muat_klaim(repo: Repo) -> list[Klaim]:
    hasil = []
    for f in _file_klaim():
        for item in json.loads(f.read_text(encoding="utf-8")):
            if "umur_jam" in item:  # kasus diputar ulang seolah ditemukan sekian jam lalu
                umur = item.pop("umur_jam")
                item["tanggal_ditemukan"] = (datetime.now(timezone.utc) - timedelta(hours=umur)).isoformat()
            hasil.append(_simpan(repo, item))
    return hasil


def _simpan(repo: Repo, item: dict) -> Klaim:
    k = hitung_prioritas(Klaim.model_validate(item))
    repo.simpan_klaim(k, aktor="seed")
    return k


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