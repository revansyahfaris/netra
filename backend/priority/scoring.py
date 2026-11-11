"""Skor prioritas klaim.

skor = 0.4*sensitivitas + 0.3*laju_sebar + 0.2*jangkauan + 0.1*kebaruan
Semua komponen dinormalisasi ke 0-1. Bobot & ambang bisa diubah di bawah.
"""

import math
from datetime import datetime, timezone

from schemas import Klaim

from .classifier import HasilKlasifikasi, klasifikasi

BOBOT = {"sensitivitas": 0.4, "laju": 0.3, "jangkauan": 0.2, "kebaruan": 0.1}
AMBANG_TINGGI = 0.65
AMBANG_SEDANG = 0.4

# Titik jenuh normalisasi (nilai di atas ini dianggap maksimal)
LAJU_MAKS = 2000          # share per jam
PENGIKUT_MAKS = 1_000_000
VIEW_MAKS = 1_000_000
PARUH_WAKTU_JAM = 24      # setelah 24 jam, nilai kebaruan tinggal setengah


def _log_norm(x: float, maks: float) -> float:
    """Normalisasi logaritmik: 10 vs 100 share beda jauh, 10.000 vs 11.000 hampir sama."""
    if x <= 0:
        return 0.0
    return min(math.log10(1 + x) / math.log10(1 + maks), 1.0)


def komponen(k: Klaim, sekarang: datetime | None = None) -> dict[str, float]:
    sekarang = sekarang or datetime.now(timezone.utc)
    ditemukan = k.tanggal_ditemukan
    if ditemukan.tzinfo is None:
        ditemukan = ditemukan.replace(tzinfo=timezone.utc)
    umur_jam = max((sekarang - ditemukan).total_seconds() / 3600, 0)

    jangkauan = max(_log_norm(k.pengikut_pengunggah, PENGIKUT_MAKS), _log_norm(k.jumlah_view, VIEW_MAKS))
    return {
        "laju": _log_norm(k.laju_sebar, LAJU_MAKS),
        "jangkauan": jangkauan,
        "kebaruan": 0.5 ** (umur_jam / PARUH_WAKTU_JAM),
    }


def _alasan(kls: HasilKlasifikasi, kom: dict[str, float], k: Klaim) -> str:
    bagian = [f"topik {kls.label_topik}" + (f" ({kls.alasan})" if kls.alasan else "")]
    if kom["laju"] >= 0.7:
        bagian.append(f"menyebar cepat ({k.laju_sebar:.0f} share/jam)")
    if kom["jangkauan"] >= 0.8:
        bagian.append("jangkauan luas")
    if kom["kebaruan"] < 0.25:
        bagian.append("sudah lebih dari 2 hari")
    return "; ".join(bagian)


def hitung_prioritas(k: Klaim, sekarang: datetime | None = None) -> Klaim:
    """Isi skor_prioritas, level, label_topik, dan alasan pada klaim."""
    kls = klasifikasi(k.teks_klaim)
    kom = komponen(k, sekarang)
    skor = (
        BOBOT["sensitivitas"] * kls.sensitivitas
        + BOBOT["laju"] * kom["laju"]
        + BOBOT["jangkauan"] * kom["jangkauan"]
        + BOBOT["kebaruan"] * kom["kebaruan"]
    )
    skor = round(skor, 2)

    return k.model_copy(
        update={
            "skor_prioritas": skor,
            "level": "tinggi" if skor >= AMBANG_TINGGI else "sedang" if skor >= AMBANG_SEDANG else "rendah",
            "label_topik": kls.label_topik,
            "alasan": _alasan(kls, kom, k),
        }
    )
