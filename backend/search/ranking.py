"""Skor & peringkat kandidat sumber asli, dengan dedup kanonis dan korroborasi anti-buzzer.

Komponen (0-1) dan bobotnya:
- kemiripan     0.28  seberapa cocok isi kandidat dengan konten viral
- tanggal       0.22  makin awal diunggah makin tinggi (relatif terhadap kandidat lain),
                      tapi hanya dihitung penuh kalau kandidatnya relevan (lihat RELEVAN_PENUH)
- jenis_sumber  0.15  resmi > media > pribadi
- korroborasi   0.10  dukungan lintas penerbit independen (1 penerbit/kanal = 1 suara, pribadi dibatasi)
- resolusi      0.08  makin tajam makin mungkin asli (unggahan ulang biasanya turun kualitas)
- bersih        0.08  tanpa watermark/overlay
- audio         0.09  kecocokan audio (khusus video)
Komponen yang datanya tidak ada dilewati, bobotnya dibagi ulang ke komponen lain.
"""

from datetime import timezone

from url_kanonis import normalisasi_url, penerbit_dari_url

from .models import Temuan

BOBOT = {
    "kemiripan": 0.28,
    "tanggal": 0.22,
    "jenis_sumber": 0.15,
    "korroborasi": 0.10,
    "resolusi": 0.08,
    "bersih": 0.08,
    "audio": 0.09,
}
NILAI_JENIS = {"resmi": 1.0, "media": 0.7, "pribadi": 0.3}
BOBOT_KORROBORASI = {"resmi": 1.0, "media": 0.7, "pribadi": 0.12}
BATAS_KONTRIBUSI_PRIBADI = 0.30   # mencegah puluhan akun buzzer mengalahkan sumber resmi/media
AMBANG_FRAME_KLASTER = 0.50
AMBANG_RELEVAN_KORROBORASI = 0.45
KEMIRIPAN_MIN = 0.35  # kandidat di bawah ini dibuang
RELEVAN_PENUH = 0.7   # kemiripan minimal agar nilai "paling awal" dihitung penuh.
                      # Tanpa ini, hasil lama yang tidak nyambung bisa jadi juara hanya karena tua.


def _utc(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _kunci_url(url: str) -> str:
    return normalisasi_url(url) or url.split("#")[0].rstrip("/")


def _klaster_temuan(t: Temuan) -> str:
    frame = t.kemiripan_frame if t.kemiripan_frame is not None else (
        t.kemiripan if t.metode == "frame_match" and not t.dari_lens else None
    )
    if frame is not None and frame >= AMBANG_FRAME_KLASTER:
        return "footage_cocok"
    if t.dari_lens and t.kemiripan >= AMBANG_FRAME_KLASTER:
        return "visual_lens"
    return "konteks_teks"


def evaluasi_korroborasi(semua: list[Temuan]) -> dict[str, dict]:
    """Hitung skor korroborasi independen & sinyal anti-buzzer per klaster kandidat."""
    per_klaster: dict[str, dict[str, Temuan]] = {}
    for t in semua:
        if t.kemiripan < AMBANG_RELEVAN_KORROBORASI:
            continue
        klaster = _klaster_temuan(t)
        penerbit = penerbit_dari_url(t.url, t.uploader)
        anggota = per_klaster.setdefault(klaster, {})
        lama = anggota.get(penerbit)
        if lama is None or (
            NILAI_JENIS.get(t.jenis_sumber, 0.3),
            t.kemiripan,
        ) > (NILAI_JENIS.get(lama.jenis_sumber, 0.3), lama.kemiripan):
            anggota[penerbit] = t

    ringkasan: dict[str, dict] = {}
    for klaster, peta_penerbit in per_klaster.items():
        resmi = sum(1 for t in peta_penerbit.values() if t.jenis_sumber == "resmi")
        media = sum(1 for t in peta_penerbit.values() if t.jenis_sumber == "media")
        pribadi = sum(1 for t in peta_penerbit.values() if t.jenis_sumber == "pribadi")
        bobot_kredibel = resmi * BOBOT_KORROBORASI["resmi"] + media * BOBOT_KORROBORASI["media"]
        bobot_pribadi_terbatas = min(
            pribadi * BOBOT_KORROBORASI["pribadi"],
            BATAS_KONTRIBUSI_PRIBADI,
        )
        indikasi_buzzer = pribadi >= 3 and (resmi + media) == 0
        if indikasi_buzzer:
            skor_klaster = round(min(0.15, bobot_pribadi_terbatas / 2.0), 3)
        else:
            skor_klaster = round(min(1.0, (bobot_kredibel + bobot_pribadi_terbatas) / 2.0), 3)

        ringkasan[klaster] = {
            "penerbit_unik": len(peta_penerbit),
            "jumlah_resmi": resmi,
            "jumlah_media": media,
            "jumlah_pribadi": pribadi,
            "indikasi_buzzer": indikasi_buzzer,
            "skor_korroborasi": skor_klaster,
        }
    return ringkasan


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


def komponen(
    t: Temuan,
    nilai_tgl: float | None,
    info_korroborasi: dict[str, dict] | None = None,
) -> dict[str, float]:
    k = {"kemiripan": t.kemiripan, "jenis_sumber": NILAI_JENIS.get(t.jenis_sumber, 0.3)}
    if nilai_tgl is not None:
        k["tanggal"] = nilai_tgl * min(1.0, t.kemiripan / RELEVAN_PENUH)
    if info_korroborasi:
        info = info_korroborasi.get(_klaster_temuan(t))
        if info is not None:
            skor_korr = float(info["skor_korroborasi"])
            if t.jenis_sumber == "pribadi" and info.get("indikasi_buzzer"):
                skor_korr = min(skor_korr, 0.15)
            k["korroborasi"] = skor_korr
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
    korr = evaluasi_korroborasi(temuan) if len(temuan) >= 2 else {}
    for i, t in enumerate(temuan):
        k = komponen(t, tgl.get(i), korr)
        total_bobot = sum(BOBOT[n] for n in k)
        t.skor = sum(BOBOT[n] * v for n, v in k.items()) / total_bobot
        rincian = {n: round(v, 2) for n, v in k.items()}
        if t.kemiripan_teks is not None:
            rincian["teks"] = round(t.kemiripan_teks, 2)
        if t.kemiripan_frame is not None:
            rincian["frame"] = round(t.kemiripan_frame, 2)
        t.rincian_skor = rincian
    return sorted(temuan, key=lambda t: t.skor or 0, reverse=True)[:maks]


def _nilai_teks_awal(t: Temuan) -> float | None:
    if t.kemiripan_teks is not None:
        return t.kemiripan_teks
    if t.metode in ("keyword", "kutipan") and not t.dari_lens:
        return t.kemiripan
    return None


def _nilai_frame_awal(t: Temuan) -> float | None:
    if t.kemiripan_frame is not None:
        return t.kemiripan_frame
    if t.metode == "frame_match" and not t.dari_lens:
        return t.kemiripan
    return None


def gabung_duplikat(temuan: list[Temuan]) -> list[Temuan]:
    """URL kanonis sama dari beberapa query digabung tanpa memalsukan label `frame_match`."""
    hasil: dict[str, Temuan] = {}
    for t in temuan:
        kunci = _kunci_url(t.url)
        lama = hasil.get(kunci)
        if lama is None:
            if t.kemiripan_teks is None:
                t.kemiripan_teks = _nilai_teks_awal(t)
            if t.kemiripan_frame is None:
                t.kemiripan_frame = _nilai_frame_awal(t)
            hasil[kunci] = t
            continue

        teks_maks = max(
            [v for v in (_nilai_teks_awal(lama), _nilai_teks_awal(t)) if v is not None],
            default=None,
        )
        frame_maks = max(
            [v for v in (_nilai_frame_awal(lama), _nilai_frame_awal(t)) if v is not None],
            default=None,
        )

        # Utamakan hasil pHash nyata sebagai representasi bila frame match memadai;
        # jika pHash rendah tetapi teks tinggi, pertahankan metode teks agar routing tidak tertipu.
        if frame_maks is not None and (
            frame_maks >= AMBANG_FRAME_KLASTER or frame_maks >= (teks_maks or 0.0)
        ):
            utama, lain = (
                (t, lama)
                if (_nilai_frame_awal(t) or -1.0) >= (_nilai_frame_awal(lama) or -1.0)
                else (lama, t)
            )
            utama.metode = "frame_match"
            utama.kemiripan = frame_maks
        else:
            utama, lain = (t, lama) if t.kemiripan > lama.kemiripan else (lama, t)
            if utama.metode == "frame_match" and teks_maks is not None and not utama.dari_lens:
                utama.metode = lain.metode if lain.metode in ("keyword", "kutipan") else "keyword"
                utama.kemiripan = max(teks_maks, utama.kemiripan)

        for f in ("tanggal_unggah", "resolusi", "ada_watermark", "kecocokan_audio", "cuplikan", "uploader"):
            if getattr(utama, f) is None:
                setattr(utama, f, getattr(lain, f))
        if not utama.judul and lain.judul:
            utama.judul = lain.judul
        if utama.jenis_sumber == "pribadi" and lain.jenis_sumber != "pribadi":
            utama.jenis_sumber = lain.jenis_sumber
        utama.dari_lens = utama.dari_lens or lain.dari_lens
        if lain.asal == "phash" or not utama.asal:
            utama.asal = lain.asal if lain.asal == "phash" else utama.asal
        utama.kemiripan_teks = teks_maks
        utama.kemiripan_frame = frame_maks
        hasil[kunci] = utama
    return list(hasil.values())
