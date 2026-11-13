"""Koneksi database Netra.

DATABASE_URL kosong -> SQLite lokal (backend/data/netra.db), supaya prototipe tetap jalan
tanpa setup. Isi DATABASE_URL (Neon/Postgres) untuk penyimpanan bersama.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import config
from .models import Base

log = logging.getLogger("netra.store")

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_paksa_sqlite = False   # True kalau Postgres gagal dihubungi saat start


def _normalisasi(url: str) -> str:
    """Neon memberi 'postgresql://'; SQLAlchemy butuh driver eksplisit."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _url_sqlite() -> str:
    return f"sqlite:///{config.DATA_DIR / 'netra.db'}"


def database_url() -> str:
    if config.DATABASE_URL and not _paksa_sqlite:
        return _normalisasi(config.DATABASE_URL)
    return _url_sqlite()


def mode() -> str:
    return "sqlite" if database_url().startswith("sqlite") else "postgres"


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        url = database_url()
        opsi: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            opsi["connect_args"] = {"check_same_thread": False}
        else:
            # connect_timeout: Neon gratis bisa butuh beberapa detik untuk "bangun"
            opsi.update(pool_size=2, max_overflow=2, pool_recycle=300, connect_args={"connect_timeout": 15})
        _engine = create_engine(url, **opsi)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
        log.info("Database: %s", url.split("@")[-1] if "@" in url else url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def init_db() -> None:
    """Buat tabel kalau belum ada. Aman dipanggil berulang.

    Kalau Postgres tidak bisa dihubungi (DNS putus, Neon tidur terlalu lama), coba sekali lagi,
    lalu pindah ke SQLite lokal supaya API tetap jalan saat demo.
    """
    global _paksa_sqlite
    from sqlalchemy.exc import OperationalError

    for percobaan in (1, 2):
        try:
            Base.metadata.create_all(get_engine())
            return
        except OperationalError as e:
            if mode() != "postgres":
                raise
            log.error("Gagal konek ke Postgres (percobaan %d): %s", percobaan, str(e.orig).split("\n")[0])
            reset_engine()
            if percobaan == 1:
                time.sleep(3)
    log.error("Pakai SQLite lokal sebagai cadangan; data tidak tersimpan di Neon")
    _paksa_sqlite = True
    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Dipakai tes untuk mengganti DATABASE_URL."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None