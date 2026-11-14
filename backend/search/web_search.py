"""Pencarian web lewat SerpAPI: Google (keyword & kutipan), YouTube, dan Google Lens (reverse image)."""

import logging

import httpx

import config

from . import dates, sources
from .models import Temuan, kemiripan_teks

log = logging.getLogger("netra.search")

SERPAPI_URL = "https://serpapi.com/search.json"


class SearchError(Exception):
    pass


def _url_layak(url: str | None) -> bool:
    """Buang tautan redirect/internal mesin pencari (mis. google.com/goto, /url?q=) yang bukan sumber."""
    if not url or not url.startswith("http"):
        return False
    host = sources.domain(url)
    return not (host in {"google.com", "google.co.id", "googleusercontent.com"} or host.endswith(".google.com"))


def _serpapi(params: dict) -> dict:
    if not config.search_aktif():
        raise SearchError("SERPAPI_KEY belum diisi")
    try:
        r = httpx.get(SERPAPI_URL, params={**params, "api_key": config.SERPAPI_KEY}, timeout=config.HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        # Jangan pakai str(e): isinya URL lengkap termasuk api_key
        raise SearchError(type(e).__name__) from None
    try:
        data = r.json()
    except ValueError:
        raise SearchError(f"HTTP {r.status_code}: respons bukan JSON") from None
    if r.status_code != 200:
        raise SearchError(f"HTTP {r.status_code}: {str(data.get('error', ''))[:200]}")
    if "error" in data and not any(k.endswith("results") or k == "visual_matches" for k in data):
        raise SearchError(data["error"])
    return data


def cari_google(query: str, kutipan: bool = False, jumlah: int = 8) -> list[Temuan]:
    q = f'"{query}"' if kutipan else query
    data = _serpapi({"engine": "google", "q": q, "hl": "id", "gl": "id", "num": jumlah})
    hasil = []
    for item in data.get("organic_results", [])[:jumlah]:
        url = item.get("link")
        if not _url_layak(url):
            continue
        judul, snippet = item.get("title", ""), item.get("snippet", "")
        hasil.append(
            Temuan(
                url=url,
                metode="kutipan" if kutipan else "keyword",
                kemiripan=kemiripan_teks(query, f"{judul} {snippet}", kutipan),
                jenis_sumber=sources.jenis_sumber(url),
                judul=judul,
                tanggal_unggah=dates.parse(item.get("date")),
                cuplikan=snippet[:200] or None,
                ada_watermark=sources.perkiraan_watermark(url),
                asal="google",
            )
        )
    return hasil


def cari_youtube(query: str, jumlah: int = 5) -> list[Temuan]:
    data = _serpapi({"engine": "youtube", "search_query": query, "gl": "id", "hl": "id"})
    hasil = []
    for item in data.get("video_results", [])[:jumlah]:
        url = item.get("link")
        if not _url_layak(url):
            continue
        kanal = (item.get("channel") or {}).get("name")
        judul = item.get("title", "")
        hasil.append(
            Temuan(
                url=url,
                metode="keyword",
                kemiripan=kemiripan_teks(query, f"{judul} {item.get('description', '')}"),
                jenis_sumber=sources.jenis_sumber(url, kanal),
                judul=judul,
                tanggal_unggah=dates.parse(item.get("published_date")),
                uploader=kanal,
                ada_watermark=sources.perkiraan_watermark(url),
                asal="youtube",
            )
        )
    return hasil


# Hasil Lens dari keyframe video baru petunjuk visual: dibatasi di bawah ambang frame match kuat (0.75)
# sampai benar-benar lolos pencocokan pHash/audio lokal.
KEMIRIPAN_MAKS_LENS_VIDEO = 0.7


def reverse_image(image_url: str, jumlah: int = 8, untuk_video: bool = False) -> list[Temuan]:
    """Google Lens. Gambar harus bisa diakses publik lewat URL.

    untuk_video=True: gambar adalah keyframe video viral. Hasilnya ditandai `dari_lens` dengan
    metode "keyword" (petunjuk, bukan bukti), supaya routing tidak menganggapnya frame match
    terverifikasi. Kandidat video dari Lens tetap diprioritaskan untuk dicek pHash.
    """
    data = _serpapi({"engine": "google_lens", "url": image_url, "hl": "id", "country": "id"})
    hasil = []
    for i, item in enumerate(data.get("visual_matches", [])[:jumlah]):
        url = item.get("link")
        if not _url_layak(url):
            continue
        # Lens tidak memberi skor; perkirakan dari urutan hasil
        perkiraan = round(max(0.9 - 0.05 * i, 0.5), 2)
        hasil.append(
            Temuan(
                url=url,
                metode="keyword" if untuk_video else "frame_match",
                kemiripan=min(perkiraan, KEMIRIPAN_MAKS_LENS_VIDEO) if untuk_video else perkiraan,
                jenis_sumber=sources.jenis_sumber(url, item.get("source")),
                judul=item.get("title", ""),
                tanggal_unggah=dates.parse(item.get("date")),
                ada_watermark=sources.perkiraan_watermark(url),
                uploader=item.get("source"),
                asal="lens",
                dari_lens=True,
            )
        )
    return hasil
