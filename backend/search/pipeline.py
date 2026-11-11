"""Orkestrasi modul pencari: query -> pencarian -> pencocokan frame -> gabung -> peringkat."""

import json
import logging

import config
from schemas import HasilPencarian, Klaim

from . import frames, ranking, web_search
from .models import Temuan
from .queries import buat_query

log = logging.getLogger("netra.search")

MAKS_VIDEO_DICOCOKKAN = 4   # unduh & cocokkan maksimal sekian kandidat video (berat)
DOMAIN_VIDEO = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com", "twitter.com", "facebook.com", "fb.watch")


def _demo(klaim: Klaim) -> list[Temuan] | None:
    """Data kandidat contoh untuk klaim demo (dipakai kalau SERPAPI_KEY kosong)."""
    f = config.DUMMY_DIR / "kandidat.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8")).get(klaim.claim_id)
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


def cari_sumber(klaim: Klaim, url_manual: list[str] | None = None) -> tuple[HasilPencarian, dict]:
    """Kembalikan (hasil, log_proses). log_proses berguna untuk debugging & dashboard."""
    url_manual = url_manual or []
    proses: dict = {"mode": "live" if config.search_aktif() else "demo"}

    temuan: list[Temuan] = []

    if not config.search_aktif() and not url_manual:
        temuan = _demo(klaim) or []

    # 1. Pencarian teks (keyword & kutipan)
    if config.search_aktif():
        q = buat_query(klaim.teks_klaim)
        proses["query"] = q
        for kut in q["kutipan"]:
            temuan += _aman("google kutipan", web_search.cari_google, kut, kutipan=True)
        for kw in q["keyword"]:
            temuan += _aman("google", web_search.cari_google, kw)
        if klaim.jenis_media == "video":
            for kw in q["keyword"][:2]:
                temuan += _aman("youtube", web_search.cari_youtube, kw)

        # 2. Reverse image search (gambar dengan URL publik)
        if klaim.jenis_media == "gambar" and klaim.media_url:
            temuan += _aman("google lens", web_search.reverse_image, str(klaim.media_url))

    # 3. Pencocokan frame & audio untuk video
    if klaim.jenis_media == "video" and klaim.media_url and (config.search_aktif() or url_manual):
        kandidat_video = list(dict.fromkeys(
            url_manual + [t.url for t in sorted(temuan, key=lambda t: -t.kemiripan) if _url_video(t.url)]
        ))[:MAKS_VIDEO_DICOCOKKAN + len(url_manual)]
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

    hasil = ranking.peringkat(ranking.gabung_duplikat(temuan))
    proses["jumlah_temuan"] = len(temuan)
    proses["rincian_skor"] = {t.url: t.rincian_skor for t in hasil}
    return HasilPencarian(claim_id=klaim.claim_id, kandidat=[t.ke_kandidat() for t in hasil]), proses
