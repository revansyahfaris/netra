"""Modul OCR & deduplikasi teks layar menggunakan Gemini Multimodal Structured Output.

Menggantikan OCR lokal + filter deduplikasi manual: Gemini langsung membaca teks
overlay, judul berita, lower-third, watermark, dan tanggal di layar dari rangkaian
keyframes sekaligus mendeduplikasi teks yang tampil berulang antar-frame.
"""

import hashlib
from html.parser import HTMLParser
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ValidationError

import config
import llm
from search import instagram

log = logging.getLogger("netra.ai.ocr")

KategoriTeksOCR = Literal[
    "overlay",
    "judul_berita",
    "lower_third",
    "watermark",
    "tanggal_layar",
    "lainnya",
]

AMBANG_DEDUP_FALLBACK = 0.85
MAKS_BYTES_GAMBAR = 15 * 1024 * 1024
MAKS_SLIDE_GAMBAR = 10


class OCRError(Exception):
    pass


class ItemTeksOCR(BaseModel):
    teks: str
    kategori: KategoriTeksOCR = "overlay"
    detik_awal: float | None = None
    detik_akhir: float | None = None


class HasilOCR(BaseModel):
    items: list[ItemTeksOCR] = []
    teks_unik: list[str] = []
    watermark_terdeteksi: list[str] = []
    tanggal_di_layar: str | None = None
    sumber_ocr: str = "gemini"  # "gemini", "kosong", atau "gagal"
    catatan: str | None = None


SCHEMA_OCR = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "teks": {"type": "STRING"},
                    "kategori": {
                        "type": "STRING",
                        "enum": [
                            "overlay",
                            "judul_berita",
                            "lower_third",
                            "watermark",
                            "tanggal_layar",
                            "lainnya",
                        ],
                    },
                    "detik_awal": {"type": "NUMBER"},
                    "detik_akhir": {"type": "NUMBER"},
                },
                "required": ["teks", "kategori"],
            },
        },
        "watermark_terdeteksi": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "tanggal_di_layar": {
            "type": "STRING",
            "nullable": True,
        },
    },
    "required": ["items", "watermark_terdeteksi"],
}

PROMPT_OCR = """Kamu analis visual pemeriksa fakta TNI AD.
Baca semua teks yang terlihat pada rangkaian gambar/keyframe berurutan atau slide carousel di bawah ini.

Aturan ketat:
1. Ekstrak hanya teks yang benar-benar terlihat di gambar (teks overlay/caption, judul berita, lower-third TV, watermark/nama akun, dan tanggal/waktu di layar). Jangan mengarang teks.
2. DEDUPLIKASI: Jika teks yang sama (atau hampir identik) muncul berulang di beberapa frame berurutan, gabungkan menjadi SATU item saja, lalu isi `detik_awal` (kemunculan pertama) dan `detik_akhir` (kemunculan terakhir) berdasarkan label `Frame @ XX.XXs`.
3. Isi `watermark_terdeteksi` dengan nama platform/akun/logo media yang terlihat (mis. "@akun", "TikTok", "KompasTV"), kosongkan array jika tidak ada.
4. Isi `tanggal_di_layar` jika ada tanggal/tahun kejadian yang tercetak di gambar atau video, atau null jika tidak ada."""


def _normalisasi_teks(teks: str) -> str:
    return re.sub(r"\s+", " ", teks).strip()


def _kunci_mirip(teks: str) -> str:
    return re.sub(r"[^\w\s]", "", teks.lower()).strip()


def _gabung_rentang(awal_a: float | None, awal_b: float | None, fungsi) -> float | None:
    kandidat = [v for v in (awal_a, awal_b) if v is not None]
    return fungsi(kandidat) if kandidat else None


def deduplikasi_item(items: list[ItemTeksOCR], ambang: float = AMBANG_DEDUP_FALLBACK) -> list[ItemTeksOCR]:
    """Pengaman deduplikasi teks antar-frame jika LLM masih menyisakan entri mirip (>85%)."""
    hasil: list[ItemTeksOCR] = []
    for item in items:
        teks_bersih = _normalisasi_teks(item.teks)
        if not teks_bersih:
            continue
        kunci_baru = _kunci_mirip(teks_bersih)
        kandidat = item.model_copy(update={"teks": teks_bersih})

        cocok_idx = None
        for idx, ada in enumerate(hasil):
            kunci_ada = _kunci_mirip(ada.teks)
            if not kunci_baru or not kunci_ada:
                continue
            rasio = SequenceMatcher(None, kunci_ada, kunci_baru).ratio()
            if rasio >= ambang and ada.kategori == kandidat.kategori:
                cocok_idx = idx
                break

        if cocok_idx is None:
            hasil.append(kandidat)
            continue

        lama = hasil[cocok_idx]
        teks_terbaik = kandidat.teks if len(kandidat.teks) > len(lama.teks) else lama.teks
        hasil[cocok_idx] = ItemTeksOCR(
            teks=teks_terbaik,
            kategori=lama.kategori,
            detik_awal=_gabung_rentang(lama.detik_awal, kandidat.detik_awal, min),
            detik_akhir=_gabung_rentang(lama.detik_akhir, kandidat.detik_akhir, max),
        )
    return hasil


def _dedup_string(daftar: list[str]) -> list[str]:
    unik: list[str] = []
    terlihat: set[str] = set()
    for raw in daftar:
        bersih = _normalisasi_teks(str(raw))
        kunci = bersih.lower()
        if bersih and kunci not in terlihat:
            terlihat.add(kunci)
            unik.append(bersih)
    return unik


def ocr_keyframes(
    keyframes: list[tuple[float, Path]],
    fallback_aman: bool = True,
    media_resolution: str | None = "MEDIA_RESOLUTION_MEDIUM",
) -> HasilOCR:
    """Baca dan deduplikasi teks dari daftar (detik, path_gambar) memakai Gemini structured output."""
    valid = [(detik, path) for detik, path in keyframes if path.exists()]
    if not valid:
        return HasilOCR(sumber_ocr="kosong")

    parts = [llm.part_teks(PROMPT_OCR)]
    for detik, path in valid:
        parts.append(llm.part_teks(f"Frame @ {detik:.2f}s"))
        parts.append(llm.part_file(path))

    try:
        mentah = llm.tanya_multimodal_json(
            parts,
            suhu=0.1,
            skema=SCHEMA_OCR,
            thinking="low",
            media_resolution=media_resolution,
        )
        if not isinstance(mentah, dict):
            raise ValueError("Respons OCR bukan JSON object")
        parsed = HasilOCR.model_validate(mentah)
    except (llm.LLMError, ValidationError, ValueError, TypeError) as e:
        log.warning("OCR Gemini gagal: %s", e)
        if not fallback_aman:
            raise OCRError(str(e)) from e
        return HasilOCR(sumber_ocr="gagal", catatan=str(e))

    items = deduplikasi_item(parsed.items)
    watermark = _dedup_string(parsed.watermark_terdeteksi)
    tanggal = _normalisasi_teks(parsed.tanggal_di_layar) if parsed.tanggal_di_layar else None
    teks_unik = _dedup_string([item.teks for item in items])

    return HasilOCR(
        items=items,
        teks_unik=teks_unik,
        watermark_terdeteksi=watermark,
        tanggal_di_layar=tanggal or None,
        sumber_ocr="gemini",
    )


_USER_AGENT_GAMBAR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_USER_AGENT_CRAWLER = "facebookexternalhit/1.1"

_EXT_GAMBAR = {
    "image/png": ".png",
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


class _MetaGambarParser(HTMLParser):
    """Ambil kandidat URL gambar preview (og:image / twitter:image / image_src) dari HTML."""

    _PRIORITAS = ("og:image:secure_url", "og:image", "twitter:image:src", "twitter:image", "image_src")

    def __init__(self) -> None:
        super().__init__()
        self.kandidat: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        nama = tag.lower()
        peta = {k.lower(): (v or "").strip() for k, v in attrs}
        if nama == "meta":
            kunci = (peta.get("property") or peta.get("name") or "").lower()
            nilai = peta.get("content", "")
            if kunci in self._PRIORITAS and nilai and kunci not in self.kandidat:
                self.kandidat[kunci] = nilai
        elif nama == "link":
            rel = {r.lower() for r in peta.get("rel", "").split()}
            href = peta.get("href", "")
            if "image_src" in rel and href and "image_src" not in self.kandidat:
                self.kandidat["image_src"] = href

    def pilih_terbaik(self, base_url: str) -> str | None:
        for kunci in self._PRIORITAS:
            mentah = self.kandidat.get(kunci)
            if not mentah:
                continue
            absolut = urljoin(base_url, mentah)
            if absolut.startswith(("http://", "https://")):
                return absolut
        return None


def folder_cache_gambar(url: str) -> Path:
    return config.WORK_DIR / f"ai_img_{hashlib.md5(url.encode()).hexdigest()[:12]}"


def daftar_cache_gambar(url: str) -> list[Path]:
    """Kembalikan seluruh file slide/gambar lokal di cache sesuai urutan slide (gambar, gambar_02, ...)."""
    folder = folder_cache_gambar(url)
    if not folder.exists():
        return []
    return sorted(p for p in folder.glob("gambar*") if p.is_file())


def path_cache_gambar(url: str) -> Path | None:
    """Kembalikan path file gambar utama (slide 1) di cache untuk URL ini bila ada."""
    daftar = daftar_cache_gambar(url)
    return daftar[0] if daftar else None


def ekstrak_url_gambar_html(html_teks: str, base_url: str) -> str | None:
    parser = _MetaGambarParser()
    parser.feed(html_teks)
    parser.close()
    return parser.pilih_terbaik(base_url)


def _shortcode_instagram(url: str) -> str | None:
    return instagram.shortcode_instagram(url)


def ekstrak_slides_instagram_embed(html_teks: str) -> list[str]:
    """Ekstrak daftar URL slide gambar berurutan dari contextJSON halaman embed Instagram."""
    info = instagram.ekstrak_info_instagram_embed(html_teks)
    return info.display_urls if info else []


def _terlihat_html(data: bytes, ct: str) -> bool:
    if ct in ("text/html", "application/xhtml+xml") or ct.startswith("text/"):
        return True
    awal = data[:512].lstrip().lower()
    return awal.startswith((b"<!doctype html", b"<html", b"<head", b"<meta"))


def _ekstensi_gambar(ct: str, data: bytes) -> str | None:
    if ct == "image/svg+xml":
        return None
    if ct in _EXT_GAMBAR:
        return _EXT_GAMBAR[ct]
    if ct.startswith("image/"):
        return ".jpg"
    if ct and ct not in ("application/octet-stream", "binary/octet-stream"):
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return None


def _http_get_aman(url: str, *, user_agent: str | None = None) -> httpx.Response:
    if not user_agent:
        return httpx.get(url, follow_redirects=True, timeout=config.HTTP_TIMEOUT)
    try:
        return httpx.get(
            url,
            follow_redirects=True,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": user_agent},
        )
    except TypeError:
        return httpx.get(url, follow_redirects=True, timeout=config.HTTP_TIMEOUT)


def _unduh_dengan_fallback_ua(url: str) -> httpx.Response:
    r = _http_get_aman(url)
    if r.status_code in (401, 403, 406):
        r = _http_get_aman(url, user_agent=_USER_AGENT_GAMBAR)
    r.raise_for_status()
    return r


def _validasi_bytes_gambar(r: httpx.Response) -> tuple[bytes, str]:
    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if len(r.content) > MAKS_BYTES_GAMBAR:
        raise OCRError("Ukuran gambar melebihi batas 15 MB")
    ext = None if _terlihat_html(r.content, ct) else _ekstensi_gambar(ct, r.content)
    if ext is None:
        raise OCRError(f"Konten URL bukan gambar yang valid (content-type: {ct or 'tidak diketahui'})")
    return r.content, ext


def _ambil_urls_instagram_embed(url: str) -> list[str]:
    info = instagram.ambil_info_instagram_embed(url, getter=_http_get_aman)
    return info.display_urls if info else []


def _simpan_semua_slide(url: str, daftar_slide: list[tuple[bytes, str]]) -> list[Path]:
    folder = folder_cache_gambar(url)
    folder.mkdir(parents=True, exist_ok=True)
    for lama in folder.glob("gambar*"):
        lama.unlink(missing_ok=True)

    paths: list[Path] = []
    for i, (data, ext) in enumerate(daftar_slide):
        nama = f"gambar{ext}" if i == 0 else f"gambar_{i + 1:02d}{ext}"
        target = folder / nama
        target.write_bytes(data)
        paths.append(target)
    return paths


def _unduh_banyak_gambar(url: str, maks: int = MAKS_SLIDE_GAMBAR) -> list[Path]:
    batas = max(1, maks)
    slides_embed = _ambil_urls_instagram_embed(url)[:batas]
    if slides_embed:
        terunduh: list[tuple[bytes, str]] = []
        for u_slide in slides_embed:
            try:
                r_slide = _unduh_dengan_fallback_ua(u_slide)
                terunduh.append(_validasi_bytes_gambar(r_slide))
            except (httpx.HTTPError, OCRError) as e:
                log.debug("Unduh salah satu slide carousel gagal (%s): %s", u_slide[:60], e)
        if terunduh:
            return _simpan_semua_slide(url, terunduh)

    try:
        r = _unduh_dengan_fallback_ua(url)
    except httpx.HTTPError as e:
        raise OCRError(f"Gagal mengunduh gambar: {e}") from e

    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if _terlihat_html(r.content, ct):
        base = str(r.url) if getattr(r, "url", None) else url
        url_preview = ekstrak_url_gambar_html(r.content.decode("utf-8", errors="ignore"), base)
        if not url_preview:
            try:
                r_bot = _http_get_aman(url, user_agent=_USER_AGENT_CRAWLER)
                if r_bot.is_success:
                    base_bot = str(r_bot.url) if getattr(r_bot, "url", None) else url
                    url_preview = ekstrak_url_gambar_html(
                        r_bot.content.decode("utf-8", errors="ignore"),
                        base_bot,
                    )
            except httpx.HTTPError:
                pass
        if not url_preview:
            raise OCRError("URL mengarah ke halaman HTML tanpa gambar preview (og:image)")
        try:
            r = _unduh_dengan_fallback_ua(url_preview)
        except httpx.HTTPError as e:
            raise OCRError(f"Gagal mengunduh gambar preview: {e}") from e

    data, ext = _validasi_bytes_gambar(r)
    return _simpan_semua_slide(url, [(data, ext)])


def _unduh_gambar(url: str) -> Path:
    return _unduh_banyak_gambar(url, maks=1)[0]


def ocr_gambar(
    sumber: str | Path,
    fallback_aman: bool = True,
    maks_slide: int = MAKS_SLIDE_GAMBAR,
) -> HasilOCR:
    """Jalankan OCR terstruktur pada gambar atau postingan carousel (path lokal atau URL publik)."""
    if isinstance(sumber, Path) or not str(sumber).startswith(("http://", "https://")):
        return ocr_keyframes([(0.0, Path(sumber))], fallback_aman=fallback_aman)

    try:
        daftar = _unduh_banyak_gambar(str(sumber), maks=maks_slide)
    except OCRError as e:
        if not fallback_aman:
            raise
        return HasilOCR(sumber_ocr="gagal", catatan=str(e))

    if len(daftar) == 1:
        return ocr_keyframes([(0.0, daftar[0])], fallback_aman=fallback_aman)
    keyframes = [(float(i + 1), p) for i, p in enumerate(daftar)]
    return ocr_keyframes(keyframes, fallback_aman=fallback_aman)

