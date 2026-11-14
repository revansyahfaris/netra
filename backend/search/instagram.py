"""Ekstraksi media dan metadata postingan Instagram lewat halaman /embed/captioned/.

Digunakan sebagai fallback yt-dlp untuk video tunggal maupun carousel campuran
(slide campuran foto + video) serta pengunduhan slide gambar OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from urllib.parse import urlparse

import httpx

import config

log = logging.getLogger("netra.search.instagram")

_HOST_INSTAGRAM = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am"}
_POLA_IG_POST = re.compile(r"^/+(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)
_POLA_CONTEXT_JSON = re.compile(r'"contextJSON"\s*:\s*"((?:\\.|[^"\\])*)"')
_USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MAKS_BYTES_VIDEO = 150 * 1024 * 1024


@dataclass
class InfoEmbedInstagram:
    shortcode: str
    url_embed: str
    display_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)
    caption: str = ""
    uploader: str | None = None
    tanggal_unggah: datetime | None = None


def shortcode_instagram(url: str) -> str | None:
    """Kembalikan shortcode postingan Instagram (/p/, /reel/, /reels/, /tv/) jika valid."""
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in _HOST_INSTAGRAM:
        return None
    m = _POLA_IG_POST.match(parsed.path)
    return m.group(1) if m else None


def _url_http_valid(val: object) -> str | None:
    if isinstance(val, str) and val.startswith(("http://", "https://")):
        return val
    return None


def ekstrak_info_instagram_embed(
    html_teks: str,
    shortcode: str = "",
    url_embed: str = "",
) -> InfoEmbedInstagram | None:
    """Ekstrak URL gambar, URL video, dan metadata dari contextJSON /embed/captioned/."""
    m = _POLA_CONTEXT_JSON.search(html_teks)
    if not m:
        return None
    try:
        raw_str = json.loads(f'"{m.group(1)}"')
        ctx = json.loads(raw_str)
    except (ValueError, TypeError):
        return None
    if not isinstance(ctx, dict):
        return None

    sm = (ctx.get("gql_data") or {}).get("shortcode_media") or ctx.get("shortcode_media") or {}
    if not isinstance(sm, dict) or not sm:
        return None

    display_urls: list[str] = []
    video_urls: list[str] = []

    edges = (sm.get("edge_sidecar_to_children") or {}).get("edges") or []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        if not isinstance(node, dict):
            continue
        if u_img := _url_http_valid(node.get("display_url")):
            display_urls.append(u_img)
        if u_vid := _url_http_valid(node.get("video_url")):
            video_urls.append(u_vid)

    if not display_urls:
        if u_img := _url_http_valid(sm.get("display_url")):
            display_urls.append(u_img)
    if u_vid := _url_http_valid(sm.get("video_url")):
        video_urls.append(u_vid)

    owner = sm.get("owner") or {}
    uploader = None
    if isinstance(owner, dict):
        uploader = (owner.get("username") or owner.get("full_name") or "").strip() or None

    caption = ""
    cap_edges = (sm.get("edge_media_to_caption") or {}).get("edges") or []
    if cap_edges and isinstance(cap_edges[0], dict):
        node_cap = cap_edges[0].get("node") or {}
        if isinstance(node_cap, dict):
            caption = str(node_cap.get("text") or "").strip()

    tanggal_unggah = None
    ts = sm.get("taken_at_timestamp")
    if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0:
        tanggal_unggah = datetime.fromtimestamp(float(ts), tz=timezone.utc)

    return InfoEmbedInstagram(
        shortcode=shortcode or str(sm.get("shortcode") or ""),
        url_embed=url_embed,
        display_urls=list(dict.fromkeys(display_urls)),
        video_urls=list(dict.fromkeys(video_urls)),
        caption=caption,
        uploader=uploader,
        tanggal_unggah=tanggal_unggah,
    )


def ambil_info_instagram_embed(url: str, *, getter=None) -> InfoEmbedInstagram | None:
    """Ambil InfoEmbedInstagram dari /p/{shortcode}/embed/captioned/ jika postingan IG publik."""
    sc = shortcode_instagram(url)
    if not sc:
        return None
    embed_url = f"https://www.instagram.com/p/{sc}/embed/captioned/"

    def _panggil(headers: dict[str, str] | None = None) -> httpx.Response:
        if getter is not None:
            return getter(embed_url) if headers is None else getter(embed_url, user_agent=headers.get("User-Agent"))
        if headers is None:
            return httpx.get(embed_url, follow_redirects=True, timeout=config.HTTP_TIMEOUT)
        try:
            return httpx.get(embed_url, follow_redirects=True, timeout=config.HTTP_TIMEOUT, headers=headers)
        except TypeError:
            return httpx.get(embed_url, follow_redirects=True, timeout=config.HTTP_TIMEOUT)

    try:
        r = _panggil()
        if r.status_code in (401, 403, 406) or (
            r.is_success and "login" in str(getattr(r, "url", "")).lower() and not _POLA_CONTEXT_JSON.search(r.text)
        ):
            r = _panggil({"User-Agent": _USER_AGENT_BROWSER})
        if not r.is_success:
            return None
        return ekstrak_info_instagram_embed(r.text, shortcode=sc, url_embed=embed_url)
    except httpx.HTTPError as e:
        log.debug("Gagal mengambil embed Instagram (%s): %s", sc, e)
        return None


def unduh_video_url(video_url: str, dest: Path, maks_bytes: int = MAKS_BYTES_VIDEO) -> Path:
    """Unduh stream MP4 langsung dari CDN ke file lokal dengan batas ukuran aman."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(".part")
    timeout = max(float(config.HTTP_TIMEOUT), 60.0)
    try:
        with httpx.stream(
            "GET",
            video_url,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT_BROWSER},
        ) as r:
            r.raise_for_status()
            ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if ct and (
                ct.startswith(("text/", "image/"))
                or ct in ("application/xhtml+xml", "application/json")
            ):
                raise ValueError(f"Respons bukan file video (content-type: {ct})")
            panjang_hdr = r.headers.get("content-length")
            if panjang_hdr and panjang_hdr.isdigit() and int(panjang_hdr) > maks_bytes:
                raise ValueError("Ukuran video melebihi batas maksimal")

            total = 0
            kepala = bytearray()
            with tmp_path.open("wb") as f:
                for chunk in r.iter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > maks_bytes:
                        raise ValueError("Ukuran video melebihi batas maksimal")
                    if len(kepala) < 512:
                        kepala.extend(chunk[: 512 - len(kepala)])
                    f.write(chunk)

        if total == 0:
            raise ValueError("File video kosong")
        awal = bytes(kepala).lstrip().lower()
        if awal.startswith((b"<!doctype html", b"<html", b"<head", b"<meta")):
            raise ValueError("Konten video ternyata halaman HTML")
        tmp_path.replace(dest)
        return dest
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
