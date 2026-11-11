"""Skor & peringkat kandidat sumber asli.

Komponen (0-1) dan bobotnya:
- kemiripan     0.30  seberapa cocok isi kandidat dengan konten viral
- tanggal       0.25  makin awal diunggah makin tinggi (relatif terhadap kandidat lain)
- jenis_sumber  0.15  resmi > media > pribadi
- resolusi      0.10  makin tajam makin mungkin asli (unggahan ulang biasanya turun kualitas)
- bersih        0.10  tanpa watermark/overlay
- audio         0.10  kecocokan audio (khusus video)
Komponen yang datanya tidak ada dilewati, bobotnya dibagi ulang ke komponen lain.
"""

from datetime import timezone

from .models import Temuan

BOBOT = {"kemiripan": 0.30, "tanggal": 0.25, "jenis_sumber": 0.15, "resolusi": 0.10, "bersih": 0.10, "audio": 0.10}
NILAI_JENIS = {"resmi": 1.0, "media": 0.7, "pribadi": 0.3}
KEMIRIPAN_MIN = 0.3   # kandidat di bawah ini dibuang


def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def nilai_tanggal(semua: list[Temuan]) -> dict[int, float]:
    """Kandidat tertua = 1, terbaru = 0, sisanya proporsional menurut waktu."""
    bertanggal = [(i, _utc(t.tanggal_unggah)) for i, t in enumerate(semua) if t.tanggal_unggah]
    if not bertanggal:
        return {}
    waktu = [d.timestamp() for _, d in bertanggal]
    tua, muda = min(waktu), max(waktu)
    if muda == tua:
        return {i: 1.0 for i, _ in bertanggal}
    return {i: 1 - (d.timestamp() - tua) / (muda - tua) for i, d in bertanggal}


def komponen(t: Temuan, nilai_tgl: float | None) -> dict[str, float]:
    k = {"kemiripan": t.kemiripan, "jenis_sumber": NILAI_JENIS.get(t.jenis_sumber, 0.3)}
    if nilai_tgl is not None:
        k["tanggal"] = nilai_tgl
    if t.resolusi:
        k["resolusi"] = min(t.resolusi / 1080, 1.0)
    if t.ada_watermark is not None:
        k["bersih"] = 0.2 if t.ada_watermark else 1.0
    if t.kecocokan_audio is not None:
        k["audio"] = t.kecocokan_audio
    return k


def peringkat(temuan: list[Temuan], maks: int = 10) -> list[Temuan]:
    temuan = [t for t in temuan if t.kemiripan >= KEMIRIPAN_MIN]
    tgl = nilai_tanggal(temuan)
    for i, t in enumerate(temuan):
        k = komponen(t, tgl.get(i))
        total_bobot = sum(BOBOT[n] for n in k)
        t.skor = sum(BOBOT[n] * v for n, v in k.items()) / total_bobot
        t.rincian_skor = {n: round(v, 2) for n, v in k.items()}
    return sorted(temuan, key=lambda t: t.skor or 0, reverse=True)[:maks]


def gabung_duplikat(temuan: list[Temuan]) -> list[Temuan]:
    """URL sama dari beberapa query digabung: ambil kemiripan tertinggi & lengkapi data yang kosong."""
    hasil: dict[str, Temuan] = {}
    for t in temuan:
        kunci = t.url.split("#")[0].rstrip("/")
        lama = hasil.get(kunci)
        if lama is None:
            hasil[kunci] = t
            continue
        utama, lain = (t, lama) if t.kemiripan > lama.kemiripan else (lama, t)
        for f in ("tanggal_unggah", "resolusi", "ada_watermark", "kecocokan_audio", "cuplikan", "uploader"):
            if getattr(utama, f) is None:
                setattr(utama, f, getattr(lain, f))
        if lain.metode == "frame_match":   # frame match adalah bukti terkuat
            utama.metode = "frame_match"
        hasil[kunci] = utama
    return list(hasil.values())
