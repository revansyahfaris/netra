"""Orkestrasi modul pencari: query -> pencarian -> pencocokan frame -> gabung -> peringkat."""

import json
import logging

import config
from schemas import HasilPencarian, Klaim

from url_kanonis import normalisasi_url

from . import frames, ranking, web_search
from .models import KonteksSinyal, Temuan
from .queries import buat_query

log = logging.getLogger("netra.search")

MAKS_VIDEO_DICOCOKKAN = 8   # unduh & cocokkan maksimal sekian kandidat video (cukup untuk korroborasi)
DOMAIN_VIDEO = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com", "twitter.com", "facebook.com", "fb.watch")


def _demo(klaim: Klaim) -> list[Temuan] | None:
    """Data kandidat contoh untuk klaim demo (dipakai kalau SERPAPI_KEY kosong)."""
    data = None
    for f in (config.DUMMY_DIR / "kandidat.json", config.KASUS_NYATA_DIR / "kandidat.json"):
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8")).get(klaim.claim_id) or data
    if not data:
        return None
    from . import dates
    return [Temuan(**{**d, "tanggal_unggah": dates.parse(d.get("tanggal_unggah"))}) for d in data]


def _aman(nama, fungsi, *args, **kwargs) -> list[Temuan]:
    """Jalankan satu sumber pencarian; kalau gagal, catat dan lanjut ke sumber lain."""
    try:
        return fungsi(*args, **kwargs)
    except (web_search.SearchError, frames.VideoError) as e:
        log.warning("%s gagal: %s", nama, e)
        return []


def _url_video(url: str) -> bool:
    return any(d in url for d in DOMAIN_VIDEO)


def _prioritas_video(temuan: Temuan) -> tuple[int, int, float]:
    """Urutkan kandidat video: hasil Lens visual dan sumber kredibel diutamakan."""
    bobot_sumber = 0 if temuan.jenis_sumber == "resmi" else (1 if temuan.jenis_sumber == "media" else 2)
    return (0 if temuan.dari_lens else 1, bobot_sumber, -temuan.kemiripan)


def _pilih_kandidat_video(url_manual: list[str], temuan: list[Temuan], maks: int) -> list[str]:
    """Pilih kandidat video unik berdasarkan URL kanonis."""
    terlihat: set[str] = set()
    hasil: list[str] = []

    def _tambah(url: str) -> None:
        kanon = normalisasi_url(url)
        if not kanon or kanon in terlihat:
            return
        terlihat.add(kanon)
        hasil.append(url)

    for url in url_manual:
        _tambah(url)

    kandidat = [t for t in temuan if _url_video(t.url)]
    for t in sorted(kandidat, key=_prioritas_video):
        if len(hasil) >= maks:
            break
        _tambah(t.url)

    return hasil


def cari_sumber(
    klaim: Klaim,
    url_manual: list[str] | None = None,
    konteks: KonteksSinyal | None = None,
) -> tuple[HasilPencarian, dict]:
    """Kembalikan (hasil, log_proses). log_proses berguna untuk debugging & dashboard."""
    url_manual = url_manual or []
    proses: dict = {"mode": "live" if config.search_aktif() else "demo"}

    temuan: list[Temuan] = []

    if not config.search_aktif() and not url_manual:
        temuan = _demo(klaim) or []

    # 1. Pencarian teks (kutipan, keyword, dan konteks peristiwa STT/OCR)
    if config.search_aktif():
        q = buat_query(klaim.teks_klaim, konteks=konteks)
        proses["query"] = q
        for kut in q["kutipan"]:
            temuan += _aman("google kutipan", web_search.cari_google, kut, kutipan=True)
        for kw in q["keyword"]:
            temuan += _aman("google", web_search.cari_google, kw)
        for p in q.get("peristiwa", []):
            temuan += _aman("google peristiwa", web_search.cari_google, p)
        if klaim.jenis_media == "video":
            for kw in q["keyword"][:2]:
                temuan += _aman("youtube", web_search.cari_youtube, kw)
            for p in q.get("peristiwa", [])[:2]:
                temuan += _aman("youtube peristiwa", web_search.cari_youtube, p)

        # 2. Reverse image search (gambar maupun keyframe video via URL publik sementara)
        if klaim.jenis_media == "gambar" and klaim.media_url:
            temuan += _aman("google lens", web_search.reverse_image, str(klaim.media_url))
        elif klaim.jenis_media == "video" and konteks and konteks.keyframe_urls:
            for kf_url in konteks.keyframe_urls[:3]:
                temuan += _aman(
                    "google lens video",
                    lambda u: web_search.reverse_image(u, untuk_video=True),
                    kf_url,
                )

    # 3. Pencocokan frame & audio untuk video
    if klaim.jenis_media == "video" and klaim.media_url and (config.search_aktif() or url_manual):
        kandidat_video = _pilih_kandidat_video(
            url_manual, temuan, MAKS_VIDEO_DICOCOKKAN + len(url_manual)
        )
        proses["video_dicocokkan"] = kandidat_video
        cache: dict = {}
        for src in kandidat_video:
            hasil = _aman(f"frame {src}", lambda s: [frames.temuan_dari_video(str(klaim.media_url), s, cache)], src)
            temuan += hasil
    elif url_manual:
        # Kandidat manual non-video: tetap dimasukkan dengan kemiripan default untuk dinilai petugas
        from . import sources
        for u in url_manual:
            temuan.append(Temuan(url=u, metode="keyword", kemiripan=0.5, jenis_sumber=sources.jenis_sumber(u),
                                 ada_watermark=sources.perkiraan_watermark(u)))

    digabung = ranking.gabung_duplikat(temuan)
    hasil = ranking.peringkat(digabung)
    proses["jumlah_temuan"] = len(temuan)
    proses["rincian_skor"] = {t.url: t.rincian_skor for t in hasil}
    proses["korroborasi"] = ranking.evaluasi_korroborasi(digabung)
    return HasilPencarian(claim_id=klaim.claim_id, kandidat=[t.ke_kandidat() for t in hasil]), proses
