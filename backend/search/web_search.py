"""Pencarian web lewat SerpAPI: Google (keyword & kutipan), YouTube, dan Google Lens (reverse image)."""

from concurrent.futures import ThreadPoolExecutor
import html
import logging
import re
from urllib.parse import parse_qs, urlparse

import httpx

import config

from . import dates, sources
from .models import Temuan, kemiripan_teks

log = logging.getLogger("netra.search")

SERPAPI_URL = "https://serpapi.com/search.json"


class SearchError(Exception):
    pass


_POLA_HREF = re.compile(r'<a[^>]+href=["\'](https?://[^"\']+)["\']', re.I)


def _adalah_redirect_google(url: str | None) -> bool:
    if not url or not url.startswith("http"):
        return False
    parsed = urlparse(url)
    host = sources.domain(url)
    is_google = (
        host in {"google.com", "google.co.id"}
        or host.endswith(".google.com")
        or host.endswith(".google.co.id")
    )
    return is_google and parsed.path in ("/goto", "/url")


def _selesaikan_redirect_url(url: str | None) -> str | None:
    """Resolve tautan redirect internal Google (mis. /url?q=... atau /goto?url=CAES...) ke URL tujuan."""
    if not url or not _adalah_redirect_google(url):
        return url

    qs = parse_qs(urlparse(url).query)
    for kunci in ("q", "url"):
        val = (qs.get(kunci) or [None])[0]
        if val and val.startswith(("http://", "https://")) and not _adalah_redirect_google(val):
            return val

    try:
        r = httpx.get(url, follow_redirects=False, timeout=5.0)
    except httpx.HTTPError as e:
        log.debug("Gagal menyelesaikan redirect Google (%s): %s", url[:80], e)
        return url

    lokasi = r.headers.get("location")
    if lokasi and lokasi.startswith(("http://", "https://")):
        return lokasi

    if r.text:
        m = _POLA_HREF.search(r.text)
        if m:
            return html.unescape(m.group(1))
    return url


def _selesaikan_banyak_url(urls: list[str | None]) -> list[str | None]:
    if not any(_adalah_redirect_google(u) for u in urls):
        return urls
    pekerja = min(4, sum(1 for u in urls if _adalah_redirect_google(u)))
    if pekerja <= 1:
        return [_selesaikan_redirect_url(u) for u in urls]
    with ThreadPoolExecutor(max_workers=pekerja) as pool:
        return list(pool.map(_selesaikan_redirect_url, urls))


def _url_layak(url: str | None) -> bool:
    """Buang tautan redirect/internal mesin pencari (mis. google.com/goto, /url?q=) yang bukan sumber."""
    if not url or not url.startswith("http"):
        return False
    host = sources.domain(url)
    return not (
        host in {"google.com", "google.co.id", "googleusercontent.com"}
        or host.endswith(".google.com")
        or host.endswith(".google.co.id")
    )


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
    items = data.get("organic_results", [])[:jumlah]
    urls = _selesaikan_banyak_url([item.get("link") for item in items])
    indeks_fallback = [
        i
        for i, (item, url) in enumerate(zip(items, urls))
        if not _url_layak(url) and item.get("redirect_link")
    ]
    if indeks_fallback:
        fallback_urls = _selesaikan_banyak_url(
            [items[i].get("redirect_link") for i in indeks_fallback]
        )
        for i, url_baru in zip(indeks_fallback, fallback_urls):
            if _url_layak(url_baru):
                urls[i] = url_baru
    hasil = []
    for item, url in zip(items, urls):
        if not _url_layak(url):
            continue
        judul, snippet = item.get("title", ""), item.get("snippet", "")
        kanal = item.get("source")
        hasil.append(
            Temuan(
                url=url,
                metode="kutipan" if kutipan else "keyword",
                kemiripan=kemiripan_teks(query, f"{judul} {snippet}", kutipan),
                jenis_sumber=sources.jenis_sumber(url, kanal),
                judul=judul,
                tanggal_unggah=dates.parse(item.get("date")),
                cuplikan=snippet[:200] or None,
                uploader=kanal,
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
    items = data.get("visual_matches", [])[:jumlah]
    urls = _selesaikan_banyak_url([item.get("link") for item in items])
    hasil = []
    for i, (item, url) in enumerate(zip(items, urls)):
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
