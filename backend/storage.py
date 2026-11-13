"""Penyimpanan data backend.

- DATABASE_URL terisi  -> Postgres (Neon). Data tetap ada walau server restart.
- DATABASE_URL kosong  -> memori (mode demo, hilang saat restart).

Tiap koleksi = satu tabel `netra_<nama>` (claim_id, data JSONB, updated_at).
Prefix `netra_` supaya tidak bentrok dengan tabel lain di database yang sama.
Hanya backend yang boleh menulis ke tabel ini; dashboard lewat API.
"""

import json
import logging
import re
from typing import Generic, Iterator, TypeVar

from pydantic import BaseModel

import config

log = logging.getLogger("netra.storage")

M = TypeVar("M", bound=BaseModel)


class _Memori:
    def __init__(self):
        self.data: dict[str, dict[str, dict]] = {}

    def siapkan(self, koleksi: str):
        self.data.setdefault(koleksi, {})

    def ambil(self, koleksi, cid):
        return self.data[koleksi].get(cid)

    def simpan(self, koleksi, cid, isi):
        self.data[koleksi][cid] = isi

    def semua(self, koleksi):
        return list(self.data[koleksi].items())

    def ada(self, koleksi, cid):
        return cid in self.data[koleksi]


class _Postgres:
    def __init__(self, url: str):
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(url, min_size=1, max_size=4, kwargs={"autocommit": True}, open=True)
        try:
            self.pool.wait(timeout=10)   # pastikan benar-benar bisa konek
        except Exception:
            self.pool.close()
            raise

    @staticmethod
    def _tabel(koleksi: str) -> str:
        if not re.fullmatch(r"[a-z_]+", koleksi):
            raise ValueError("nama koleksi tidak valid")
        return f"netra_{koleksi}"

    def siapkan(self, koleksi):
        with self.pool.connection() as c:
            c.execute(
                f"CREATE TABLE IF NOT EXISTS {self._tabel(koleksi)} ("
                "claim_id TEXT PRIMARY KEY, data JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )

    def ambil(self, koleksi, cid):
        with self.pool.connection() as c:
            row = c.execute(f"SELECT data FROM {self._tabel(koleksi)} WHERE claim_id = %s", (cid,)).fetchone()
        return row[0] if row else None

    def simpan(self, koleksi, cid, isi):
        with self.pool.connection() as c:
            c.execute(
                f"INSERT INTO {self._tabel(koleksi)} (claim_id, data) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (claim_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                (cid, json.dumps(isi)),
            )

    def semua(self, koleksi):
        with self.pool.connection() as c:
            return c.execute(f"SELECT claim_id, data FROM {self._tabel(koleksi)} ORDER BY updated_at").fetchall()

    def ada(self, koleksi, cid):
        with self.pool.connection() as c:
            return c.execute(f"SELECT 1 FROM {self._tabel(koleksi)} WHERE claim_id = %s", (cid,)).fetchone() is not None


def _buat_backend():
    if config.DATABASE_URL:
        try:
            b = _Postgres(config.DATABASE_URL)
            log.info("Penyimpanan: Postgres")
            return b, "postgres"
        except Exception as e:  # koneksi gagal -> tetap jalan pakai memori
            log.error("Gagal konek ke database, pakai memori: %s", e)
    return _Memori(), "memori"


BACKEND, MODE = _buat_backend()


class Koleksi(Generic[M]):
    """Dipakai seperti dict: kol[id], kol[id] = model, id in kol, kol.get(id), kol.values(), kol.items()."""

    def __init__(self, nama: str, model: type[M] | None = None):
        self.nama, self.model = nama, model
        BACKEND.siapkan(nama)

    def _ke_model(self, isi):
        return self.model.model_validate(isi) if self.model else isi

    def __getitem__(self, cid: str) -> M:
        isi = BACKEND.ambil(self.nama, cid)
        if isi is None:
            raise KeyError(cid)
        return self._ke_model(isi)

    def get(self, cid: str, default=None):
        isi = BACKEND.ambil(self.nama, cid)
        return default if isi is None else self._ke_model(isi)

    def __setitem__(self, cid: str, nilai):
        isi = nilai.model_dump(mode="json") if isinstance(nilai, BaseModel) else nilai
        BACKEND.simpan(self.nama, cid, isi)

    def __contains__(self, cid) -> bool:
        return BACKEND.ada(self.nama, cid)

    def items(self) -> list[tuple[str, M]]:
        return [(cid, self._ke_model(isi)) for cid, isi in BACKEND.semua(self.nama)]

    def values(self) -> list[M]:
        return [m for _, m in self.items()]

    def __len__(self) -> int:
        return len(BACKEND.semua(self.nama))

    def __iter__(self) -> Iterator[str]:
        return iter([cid for cid, _ in BACKEND.semua(self.nama)])
