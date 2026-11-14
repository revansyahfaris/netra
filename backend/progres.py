"""Pelaporan tahap pipeline yang sedang berjalan, untuk tampilan progres di dashboard.

Modul pencarian dan AI cukup memanggil `lapor("nama_tahap")`. Kalau tidak ada job yang
memantau (mis. dipanggil dari tes atau skrip), panggilan ini tidak melakukan apa-apa.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Callable

_pelapor: ContextVar[Callable[[str], None] | None] = ContextVar("netra_pelapor_tahap", default=None)


def pasang(fn: Callable[[str], None] | None):
    """Pasang pelapor untuk konteks saat ini; kembalikan token untuk dilepas."""
    return _pelapor.set(fn)


def lepas(token) -> None:
    _pelapor.reset(token)


def lapor(tahap: str) -> None:
    fn = _pelapor.get()
    if fn is not None:
        try:
            fn(tahap)
        except Exception:  # pelaporan progres tidak boleh menggagalkan pipeline
            pass
