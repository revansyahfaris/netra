"""Struktur data internal modul pencari (sebelum diubah jadi KandidatSumber)."""

import re
from dataclasses import dataclass, field
from datetime import datetime

from schemas import KandidatSumber


@dataclass
class Temuan:
    url: str
    metode: str                     # keyword / kutipan / frame_match
    kemiripan: float
    jenis_sumber: str = "pribadi"
    judul: str = ""
    tanggal_unggah: datetime | None = None
    cuplikan: str | None = None
    resolusi: int | None = None
    ada_watermark: bool | None = None
    kecocokan_audio: float | None = None
    uploader: str | None = None
    skor: float | None = None
    rincian_skor: dict = field(default_factory=dict)

    def ke_kandidat(self) -> KandidatSumber:
        return KandidatSumber(
            url=self.url,
            tanggal_unggah=self.tanggal_unggah,
            jenis_sumber=self.jenis_sumber,
            metode=self.metode,
            kemiripan=round(max(0.0, min(self.kemiripan, 1.0)), 2),
            cuplikan=self.cuplikan,
            resolusi=self.resolusi,
            ada_watermark=self.ada_watermark,
            kecocokan_audio=None if self.kecocokan_audio is None else round(self.kecocokan_audio, 2),
            skor=None if self.skor is None else round(self.skor, 2),
            # Dibutuhkan dashboard: tanpa ini kartu kandidat cuma menampilkan URL
            judul=self.judul or None,
            uploader=self.uploader,
            rincian_skor=self.rincian_skor,
        )


def _token(teks: str) -> set[str]:
    return {w for w in re.findall(r"\w+", teks.lower()) if len(w) > 2}


def kemiripan_teks(query: str, teks: str, kutipan: bool = False) -> float:
    """Seberapa cocok hasil pencarian (judul + snippet) dengan query."""
    if not query or not teks:
        return 0.0
    if kutipan:
        norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
        if norm(query) in norm(teks):
            return 0.95
    q = _token(query)
    if not q:
        return 0.0
    overlap = len(q & _token(teks)) / len(q)
    return round(overlap * (0.8 if kutipan else 0.9), 2)
