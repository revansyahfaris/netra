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


def _serpapi(params: dict) -> dict:
    if not config.search_aktif():
        raise SearchError("SERPAPI_KEY belum diisi")
    try:
        r = httpx.get(SERPAPI_URL, params={**params, "api_key": config.SERPAPI_KEY}, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SearchError(str(e)) from e
    if "error" in data and not any(k.endswith("results") or k == "visual_matches" for k in data):
        raise SearchError(data["error"])
    return data


def cari_google(query: str, kutipan: bool = False, jumlah: int = 8) -> list[Temuan]:
    q = f'"{query}"' if kutipan else query
    data = _serpapi({"engine": "google", "q": q, "hl": "id", "gl": "id", "num": jumlah})
    hasil = []
    for item in data.get("organic_results", [])[:jumlah]:
        url = item.get("link")
        if not url:
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
            )
        )
    return hasil


def cari_youtube(query: str, jumlah: int = 5) -> list[Temuan]:
    data = _serpapi({"engine": "youtube", "search_query": query, "gl": "id", "hl": "id"})
    hasil = []
    for item in data.get("video_results", [])[:jumlah]:
        url = item.get("link")
        if not url:
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
            )
        )
    return hasil


def reverse_image(image_url: str, jumlah: int = 8) -> list[Temuan]:
    """Google Lens. Gambar harus bisa diakses publik lewat URL."""
    data = _serpapi({"engine": "google_lens", "url": image_url, "hl": "id", "country": "id"})
    hasil = []
    for i, item in enumerate(data.get("visual_matches", [])[:jumlah]):
        url = item.get("link")
        if not url:
            continue
        hasil.append(
            Temuan(
                url=url,
                metode="frame_match",
                # Lens tidak memberi skor; perkirakan dari urutan hasil
                kemiripan=round(max(0.9 - 0.05 * i, 0.5), 2),
                jenis_sumber=sources.jenis_sumber(url, item.get("source")),
                judul=item.get("title", ""),
                tanggal_unggah=dates.parse(item.get("date")),
                ada_watermark=sources.perkiraan_watermark(url),
            )
        )
    return hasil
