"""Tahap 2: Ekstraksi sinyal sumber acuan (video, gambar, dan artikel/berita web).

Menjembatani daftar kandidat hasil pencarian modul Faris (`KandidatSumber`)
menjadi teks & sinyal terstruktur yang siap diaudit oleh LLM di Tahap 4.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

import config
from schemas import KandidatSumber

from . import ekstraksi, ocr, stt
from .ocr import HasilOCR
from .stt import HasilSTT, SegmenTranskrip

log = logging.getLogger("netra.ai.sumber")

JenisKontenSumber = Literal["video", "gambar", "artikel"]
SumberEkstraksi = Literal[
    "video_stt_ocr",
    "web_artikel",
    "ocr_gambar",
    "fallback_snippet",
    "gagal",
]

DOMAIN_PLATFORM_VIDEO = {
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "fb.watch",
    "vimeo.com",
}
DOMAIN_SOSIAL_CAMPURAN = {"facebook.com", "instagram.com", "x.com", "twitter.com"}
EKSTENSI_VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".avi")
EKSTENSI_GAMBAR = (".jpg", ".jpeg", ".png", ".webp", ".gif")

MAKS_BYTES_ARTIKEL = 2 * 1024 * 1024
KONTEKS_SEBELUM_DEFAULT = 20.0
DURASI_JENDELA_DEFAULT = 90.0
USER_AGENT = "NetraFactCheckBot/0.3 (+https://github.com/netra)"


class SinyalSumberAcuan(BaseModel):
    url: str
    judul: str | None = None
    jenis_sumber: str = "pribadi"
    jenis_konten: JenisKontenSumber = "artikel"
    tanggal_unggah: str | None = None
    sumber_ekstraksi: SumberEkstraksi = "fallback_snippet"
    ekstraksi_penuh_berhasil: bool = False
    detik_cuplikan: float | None = None
    jendela_mulai_detik: float | None = None
    jendela_durasi_detik: float | None = None
    teks_isi: str = ""
    stt_teks: str = ""
    stt_segmen: list[SegmenTranskrip] = Field(default_factory=list)
    sumber_stt: str = "kosong"
    ocr: HasilOCR = Field(default_factory=HasilOCR)
    keyframes_lokal: list[str] = Field(default_factory=list)
    catatan: str | None = None


def pilih_keyframes_wakilan(keyframes: Sequence[tuple[float, Path]], maks: int = 3) -> list[str]:
    """Ambil maksimal `maks` path keyframe yang tersebar merata (awal-tengah-akhir)."""
    semua = [Path(p) for _, p in keyframes]
    ada = [p for p in semua if p.exists()] or semua
    if not ada or maks <= 0:
        return []
    if len(ada) <= maks:
        return [str(p) for p in ada]
    if maks == 1:
        return [str(ada[len(ada) // 2])]
    indeks: list[int] = []
    for i in range(maks):
        idx = round(i * (len(ada) - 1) / (maks - 1))
        if idx not in indeks:
            indeks.append(idx)
    return [str(ada[i]) for i in indeks]


class _HtmlEkstraktor(HTMLParser):
    """Parser ringan HTML berbasis stdlib untuk mengambil judul, tanggal, dan teks berita."""

    TAG_DIABAIKAN = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "iframe"}
    TAG_BLOK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "br", "div", "section", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._abaikan_depth = 0
        self._utama_depth = 0
        self._dalam_title = False
        self.title_parts: list[str] = []
        self.og_title: str | None = None
        self.deskripsi: str | None = None
        self.tanggal_terbit: str | None = None
        self.teks_utama: list[str] = []
        self.teks_body: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "").strip() for k, v in attrs}

        if t in self.TAG_DIABAIKAN:
            self._abaikan_depth += 1
            return
        if t in ("article", "main"):
            self._utama_depth += 1
        elif t == "title":
            self._dalam_title = True
        elif t == "meta":
            kunci = (attr_map.get("property") or attr_map.get("name") or "").lower()
            isi = attr_map.get("content", "")
            if isi:
                if kunci == "og:title" and not self.og_title:
                    self.og_title = isi
                elif kunci in ("description", "og:description") and not self.deskripsi:
                    self.deskripsi = isi
                elif kunci in ("article:published_time", "pubdate", "publishdate", "date") and not self.tanggal_terbit:
                    self.tanggal_terbit = isi
        elif t == "time" and not self.tanggal_terbit and attr_map.get("datetime"):
            self.tanggal_terbit = attr_map["datetime"]

        if self._abaikan_depth == 0 and t in self.TAG_BLOK:
            self.teks_body.append("\n")
            if self._utama_depth > 0:
                self.teks_utama.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.TAG_DIABAIKAN and self._abaikan_depth > 0:
            self._abaikan_depth -= 1
            return
        if t in ("article", "main") and self._utama_depth > 0:
            self._utama_depth -= 1
        elif t == "title":
            self._dalam_title = False

        if self._abaikan_depth == 0 and t in self.TAG_BLOK:
            self.teks_body.append("\n")
            if self._utama_depth > 0:
                self.teks_utama.append("\n")

    def handle_data(self, data: str) -> None:
        if self._abaikan_depth > 0:
            return
        if self._dalam_title:
            self.title_parts.append(data)
            return
        self.teks_body.append(data)
        if self._utama_depth > 0:
            self.teks_utama.append(data)


def _bersihkan_teks_html(potongan: list[str], batas_karakter: int) -> str:
    gabung = html.unescape("".join(potongan))
    baris = [re.sub(r"[ \t\r\f\v]+", " ", b).strip() for b in gabung.splitlines()]
    baris_valid = [b for b in baris if b]
    teks = "\n".join(baris_valid)
    if len(teks) > batas_karakter:
        return teks[:batas_karakter].rstrip() + "..."
    return teks


def ekstrak_teks_html(html_teks: str, batas_karakter: int = 8000) -> dict[str, str | None]:
    """Ekstrak judul, tanggal terbit, deskripsi, dan isi teks bersih dari HTML artikel."""
    parser = _HtmlEkstraktor()
    parser.feed(html_teks)
    parser.close()

    teks_utama = _bersihkan_teks_html(parser.teks_utama, batas_karakter)
    teks_body = _bersihkan_teks_html(parser.teks_body, batas_karakter)
    isi = teks_utama if len(teks_utama) >= 120 else (teks_body or teks_utama)
    judul = parser.og_title or re.sub(r"\s+", " ", "".join(parser.title_parts)).strip() or None

    return {
        "judul": judul,
        "tanggal_terbit": parser.tanggal_terbit,
        "deskripsi": parser.deskripsi,
        "isi": isi,
    }


def adalah_url_placeholder(url: str) -> bool:
    """Deteksi URL sintetis/contoh (example.com, CONTOH-*) agar mode demo tidak menunggu timeout jaringan."""
    parsed = urlparse(str(url))
    host = (parsed.hostname or "").lower()
    if host in {"example.com", "example.org", "example.net"} or host.endswith(".example.com"):
        return True
    jalur = f"{parsed.path}?{parsed.query}".upper()
    return "CONTOH-" in jalur or "/CONTOH" in jalur


def _adalah_timestamp(cuplikan: str | None) -> bool:
    if not cuplikan:
        return False
    bagian = cuplikan.strip().split(":")
    return len(bagian) in (2, 3) and all(b.isdigit() for b in bagian)


def _host_cocok(host: str, daftar: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in daftar)


def deteksi_jenis_kandidat(kandidat: KandidatSumber) -> JenisKontenSumber:
    """Klasifikasikan kandidat sebagai video, gambar, atau artikel web."""
    parsed = urlparse(str(kandidat.url))
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = parsed.path.lower()

    if path.endswith(EKSTENSI_VIDEO):
        return "video"
    if path.endswith(EKSTENSI_GAMBAR):
        return "gambar"
    if _host_cocok(host, DOMAIN_PLATFORM_VIDEO):
        return "video"
    if _host_cocok(host, DOMAIN_SOSIAL_CAMPURAN):
        if any(seg in path for seg in ("/watch", "/videos/", "/reel/", "/tv/", "/video/")):
            return "video"
        if kandidat.kecocokan_audio is not None or (kandidat.metode == "frame_match" and _adalah_timestamp(kandidat.cuplikan)):
            return "video"
    if kandidat.kecocokan_audio is not None or _adalah_timestamp(kandidat.cuplikan):
        return "video"
    return "artikel"


def hitung_jendela_video(
    cuplikan: str | None,
    durasi_total: float | None = None,
    konteks_sebelum: float = KONTEKS_SEBELUM_DEFAULT,
    durasi_jendela: float = DURASI_JENDELA_DEFAULT,
) -> tuple[float, float, float | None]:
    """Hitung (mulai_detik, durasi_maks, detik_cuplikan) di sekitar penanda `cuplikan`."""
    durasi_maks = min(max(durasi_jendela, 10.0), ekstraksi.MAKS_DETIK_EKSTRAKSI)
    if not _adalah_timestamp(cuplikan):
        return 0.0, durasi_maks, None

    detik_pusat = ekstraksi.detik_dari_cuplikan(cuplikan)
    mulai = max(0.0, detik_pusat - max(0.0, konteks_sebelum))
    if durasi_total is not None and durasi_total > 0 and mulai >= durasi_total:
        mulai = max(0.0, durasi_total - min(durasi_maks, durasi_total))
    return round(mulai, 2), round(durasi_maks, 2), detik_pusat


def transkrip_audio_aman(audio_path: Path | None, bahasa: str | None = "id") -> HasilSTT:
    """Jalankan STT faster-whisper (Docker). Jika layanan mati/error, tandai 'tidak_aktif' tanpa fallback Gemini."""
    if audio_path is None:
        return HasilSTT(teks="", segmen=[], sumber_stt="kosong")

    if not config.stt_aktif():
        log.info("Layanan STT (faster-whisper) sedang tidak aktif (STT_BASE_URL kosong).")
        return HasilSTT(teks="", segmen=[], sumber_stt="tidak_aktif")

    try:
        return stt.transkrip_audio(audio_path, bahasa=bahasa)
    except stt.STTError as e:
        log.warning("Layanan STT (faster-whisper) sedang tidak aktif atau gagal dihubungi: %s", e)
        return HasilSTT(teks="", segmen=[], sumber_stt="tidak_aktif")


def _gabung_snippet(kandidat: KandidatSumber) -> str:
    bagian = [t.strip() for t in (kandidat.judul, kandidat.cuplikan) if t and str(t).strip()]
    return " — ".join(bagian)


def _fallback_kandidat(
    kandidat: KandidatSumber,
    jenis: JenisKontenSumber,
    catatan: str,
    detik_cuplikan: float | None = None,
    keyframes_lokal: list[str] | None = None,
) -> SinyalSumberAcuan:
    tgl = kandidat.tanggal_unggah.isoformat() if kandidat.tanggal_unggah else None
    return SinyalSumberAcuan(
        url=str(kandidat.url),
        judul=kandidat.judul,
        jenis_sumber=kandidat.jenis_sumber,
        jenis_konten=jenis,
        tanggal_unggah=tgl,
        sumber_ekstraksi="fallback_snippet",
        ekstraksi_penuh_berhasil=False,
        detik_cuplikan=detik_cuplikan,
        teks_isi=_gabung_snippet(kandidat),
        keyframes_lokal=keyframes_lokal or [],
        catatan=catatan,
    )


def _gabung_teks_video(judul: str | None, stt_teks: str, ocr_hasil: HasilOCR) -> str:
    bagian: list[str] = []
    if judul:
        bagian.append(f"Judul: {judul}")
    if stt_teks.strip():
        bagian.append(f"Transkrip ucapan: {stt_teks.strip()}")
    if ocr_hasil.teks_unik:
        bagian.append("Teks layar (OCR): " + " | ".join(ocr_hasil.teks_unik))
    return "\n".join(bagian)


def _ekstrak_kandidat_video(
    kandidat: KandidatSumber,
    konteks_sebelum: float,
    durasi_jendela: float,
) -> SinyalSumberAcuan:
    url_str = str(kandidat.url)
    detik_awal_perkiraan = ekstraksi.detik_dari_cuplikan(kandidat.cuplikan) if _adalah_timestamp(kandidat.cuplikan) else None

    try:
        video_path = ekstraksi._siapkan_video(url_str)
        durasi_total = ekstraksi.durasi_video(video_path)
        mulai, durasi, detik_pusat = hitung_jendela_video(
            kandidat.cuplikan,
            durasi_total=durasi_total,
            konteks_sebelum=konteks_sebelum,
            durasi_jendela=durasi_jendela,
        )
        folder = ekstraksi._folder_kerja(f"{url_str}@{int(mulai)}")
        audio = ekstraksi.ekstrak_audio(
            video_path,
            mulai_detik=mulai,
            durasi_maks=durasi,
            output=folder / "audio_16k.wav",
        )
        keyframes = ekstraksi.ekstrak_keyframes(
            video_path,
            mulai_detik=mulai,
            durasi_maks=durasi,
            output_dir=folder / "keyframes_ocr",
        )
    except ekstraksi.EkstraksiError as e:
        log.warning("Ekstraksi video sumber acuan gagal (%s): %s", url_str, e)
        return _fallback_kandidat(
            kandidat,
            "video",
            catatan=f"Gagal mengekstrak video penuh ({e}); memakai judul & cuplikan pencarian.",
            detik_cuplikan=detik_awal_perkiraan,
        )

    hasil_stt = transkrip_audio_aman(audio)
    hasil_ocr = ocr.ocr_keyframes(keyframes, fallback_aman=True)
    teks_isi = _gabung_teks_video(kandidat.judul, hasil_stt.teks, hasil_ocr) or _gabung_snippet(kandidat)
    berhasil = bool(hasil_stt.teks.strip() or hasil_ocr.teks_unik)

    tgl = kandidat.tanggal_unggah.isoformat() if kandidat.tanggal_unggah else None
    catatan_bagian: list[str] = []
    if hasil_stt.sumber_stt == "tidak_aktif":
        catatan_bagian.append("STT (faster-whisper) sedang tidak aktif.")
    if not berhasil:
        catatan_bagian.append("Audio/OCR tidak menghasilkan teks baru; dilengkapi judul/cuplikan.")
    catatan = " ".join(catatan_bagian) or None

    return SinyalSumberAcuan(
        url=url_str,
        judul=kandidat.judul,
        jenis_sumber=kandidat.jenis_sumber,
        jenis_konten="video",
        tanggal_unggah=tgl,
        sumber_ekstraksi="video_stt_ocr" if berhasil else "fallback_snippet",
        ekstraksi_penuh_berhasil=berhasil,
        detik_cuplikan=detik_pusat,
        jendela_mulai_detik=mulai,
        jendela_durasi_detik=durasi,
        teks_isi=teks_isi,
        stt_teks=hasil_stt.teks,
        stt_segmen=hasil_stt.segmen,
        sumber_stt=hasil_stt.sumber_stt,
        ocr=hasil_ocr,
        keyframes_lokal=pilih_keyframes_wakilan(keyframes, maks=3),
        catatan=catatan,
    )


def _resolve_semua_lokal_gambar(url_gambar: str | None) -> list[Path]:
    if not url_gambar:
        return []
    if url_gambar.startswith(("http://", "https://")):
        return ocr.daftar_cache_gambar(url_gambar)
    kandidat_path = Path(url_gambar)
    return [kandidat_path] if kandidat_path.exists() else []


def _bangun_sinyal_gambar(
    kandidat: KandidatSumber,
    hasil_ocr: HasilOCR,
    *,
    lokal: Path | None = None,
    url_gambar_dipakai: str | None = None,
    deskripsi_html: str | None = None,
) -> SinyalSumberAcuan:
    url_str = str(kandidat.url)
    tgl = kandidat.tanggal_unggah.isoformat() if kandidat.tanggal_unggah else None
    daftar_lokal = (
        [lokal]
        if lokal and lokal.exists()
        else _resolve_semua_lokal_gambar(url_gambar_dipakai or url_str)
    )
    keyframes = [str(p) for p in daftar_lokal if p.exists()]

    bagian_meta: list[str] = []
    if kandidat.judul:
        bagian_meta.append(kandidat.judul.strip())
    if deskripsi_html and deskripsi_html.strip() and deskripsi_html.strip() not in bagian_meta:
        bagian_meta.append(deskripsi_html.strip())

    if hasil_ocr.sumber_ocr == "gemini" and hasil_ocr.teks_unik:
        teks_ocr = " | ".join(hasil_ocr.teks_unik)
        bagian_meta.append(f"Teks gambar (OCR): {teks_ocr}")
        return SinyalSumberAcuan(
            url=url_str,
            judul=kandidat.judul,
            jenis_sumber=kandidat.jenis_sumber,
            jenis_konten="gambar",
            tanggal_unggah=tgl,
            sumber_ekstraksi="ocr_gambar",
            ekstraksi_penuh_berhasil=True,
            teks_isi="\n".join(bagian_meta),
            ocr=hasil_ocr,
            keyframes_lokal=keyframes,
        )

    if keyframes and hasil_ocr.sumber_ocr == "gemini":
        teks_isi = "\n".join(bagian_meta) if bagian_meta else _gabung_snippet(kandidat)
        return SinyalSumberAcuan(
            url=url_str,
            judul=kandidat.judul,
            jenis_sumber=kandidat.jenis_sumber,
            jenis_konten="gambar",
            tanggal_unggah=tgl,
            sumber_ekstraksi="ocr_gambar",
            ekstraksi_penuh_berhasil=True,
            teks_isi=teks_isi,
            ocr=hasil_ocr,
            keyframes_lokal=keyframes,
            catatan="Gambar berhasil diunduh (tidak ada teks overlay di gambar).",
        )

    return _fallback_kandidat(
        kandidat,
        "gambar",
        catatan=hasil_ocr.catatan or "OCR gambar tidak menghasilkan teks; memakai judul & cuplikan.",
        keyframes_lokal=keyframes,
    )


def _ekstrak_kandidat_gambar(kandidat: KandidatSumber) -> SinyalSumberAcuan:
    url_str = str(kandidat.url)
    hasil_ocr = ocr.ocr_gambar(url_str, fallback_aman=True)
    return _bangun_sinyal_gambar(kandidat, hasil_ocr, url_gambar_dipakai=url_str)


def _simpan_gambar_sementara(url: str, data: bytes, ct: str) -> Path:
    folder = ocr.folder_cache_gambar(url)
    folder.mkdir(parents=True, exist_ok=True)
    for lama in folder.glob("gambar*"):
        lama.unlink(missing_ok=True)
    ext = ocr._ekstensi_gambar(ct, data) or ".jpg"
    target = folder / f"gambar{ext}"
    target.write_bytes(data)
    return target


def _ekstrak_kandidat_artikel(kandidat: KandidatSumber) -> SinyalSumberAcuan:
    url_str = str(kandidat.url)
    tgl = kandidat.tanggal_unggah.isoformat() if kandidat.tanggal_unggah else None

    try:
        r = httpx.get(
            url_str,
            follow_redirects=True,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Fetch artikel sumber gagal (%s): %s", url_str, e)
        return _fallback_kandidat(
            kandidat,
            "artikel",
            catatan=f"Gagal mengambil halaman sumber ({type(e).__name__}); memakai judul & cuplikan.",
        )

    if len(r.content) > MAKS_BYTES_ARTIKEL:
        return _fallback_kandidat(
            kandidat,
            "artikel",
            catatan="Ukuran halaman melebihi batas 2 MB; memakai judul & cuplikan.",
        )

    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ct.startswith("image/"):
        lokal = _simpan_gambar_sementara(url_str, r.content, ct)
        hasil_ocr = ocr.ocr_keyframes([(0.0, lokal)], fallback_aman=True)
        return _bangun_sinyal_gambar(kandidat, hasil_ocr, lokal=lokal)

    if ct and not any(t in ct for t in ("text/html", "application/xhtml", "text/plain")):
        return _fallback_kandidat(
            kandidat,
            "artikel",
            catatan=f"Format konten tidak didukung untuk fetch teks ({ct}); memakai judul & cuplikan.",
        )

    parsed = ekstrak_teks_html(r.text)
    isi = (parsed.get("isi") or "").strip()
    if len(isi) < 40:
        if ocr._shortcode_instagram(url_str):
            hasil_ocr = ocr.ocr_gambar(url_str, fallback_aman=True)
            return _bangun_sinyal_gambar(
                kandidat,
                hasil_ocr,
                url_gambar_dipakai=url_str,
                deskripsi_html=parsed.get("deskripsi"),
            )
        base_url = str(r.url) if getattr(r, "url", None) else url_str
        url_preview = ocr.ekstrak_url_gambar_html(r.text, base_url)
        if url_preview:
            hasil_ocr = ocr.ocr_gambar(url_preview, fallback_aman=True)
            return _bangun_sinyal_gambar(
                kandidat,
                hasil_ocr,
                url_gambar_dipakai=url_preview,
                deskripsi_html=parsed.get("deskripsi"),
            )
        return _fallback_kandidat(
            kandidat,
            "artikel",
            catatan="Teks artikel terlalu pendek atau terhalang JS/paywall; memakai judul & cuplikan.",
        )

    judul_final = kandidat.judul or parsed.get("judul")
    tgl_final = tgl or parsed.get("tanggal_terbit")
    teks_isi = f"Judul: {judul_final}\n\n{isi}" if judul_final else isi

    return SinyalSumberAcuan(
        url=url_str,
        judul=judul_final,
        jenis_sumber=kandidat.jenis_sumber,
        jenis_konten="artikel",
        tanggal_unggah=tgl_final,
        sumber_ekstraksi="web_artikel",
        ekstraksi_penuh_berhasil=True,
        teks_isi=teks_isi,
    )


def ekstrak_sinyal_kandidat(
    kandidat: KandidatSumber,
    ambil_konten_eksternal: bool = True,
    konteks_sebelum: float = KONTEKS_SEBELUM_DEFAULT,
    durasi_jendela: float = DURASI_JENDELA_DEFAULT,
) -> SinyalSumberAcuan:
    """Ekstrak isi teks/sinyal dari satu kandidat sumber (video, gambar, atau artikel web)."""
    url_str = str(kandidat.url)
    jenis = deteksi_jenis_kandidat(kandidat)

    if not ambil_konten_eksternal or adalah_url_placeholder(url_str):
        detik = ekstraksi.detik_dari_cuplikan(kandidat.cuplikan) if jenis == "video" and _adalah_timestamp(kandidat.cuplikan) else None
        return _fallback_kandidat(
            kandidat,
            jenis,
            catatan="Mode demo/placeholder: memakai judul & cuplikan kandidat tanpa unduhan eksternal.",
            detik_cuplikan=detik,
        )

    if jenis == "video":
        return _ekstrak_kandidat_video(kandidat, konteks_sebelum=konteks_sebelum, durasi_jendela=durasi_jendela)
    if jenis == "gambar":
        return _ekstrak_kandidat_gambar(kandidat)
    return _ekstrak_kandidat_artikel(kandidat)

