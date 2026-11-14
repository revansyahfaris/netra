"""Kanonisasi URL dan identitas dokumen deterministik.

Dipakai bersama oleh modul pencari (`search/`), lapisan AI (`ai/`), dan penyimpanan (`store/`)
supaya satu video/artikel yang sama selalu dikenali sebagai satu entitas, walau tautannya
berbeda (youtu.be vs youtube.com/watch, parameter pelacak, www/m, dan sebagainya).
Modul ini sengaja tidak mengimpor `ai` maupun `search` agar bebas impor melingkar.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

PREFIX_SUBDOMAIN_UMUM = ("www.", "m.", "mobile.", "web.")
PARAMETER_TRACKING = frozenset({
    "fbclid",
    "gclid",
    "dclid",
    "yclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "igsh",
    "si",
    "feature",
    "pp",
    "ab_channel",
    "ref_src",
    "ref_url",
    "is_from_webapp",
    "sender_device",
    "sender_web_id",
    "_r",
    "_t",
    "share_id",
    "share_url",
    "mibextid",
    "rdid",
    "tt_from",
    "u_code",
    "share_app_id",
    "share_item_id",
    "checksum",
    "sec_uid",
})


def _strip_prefix_host(host: str) -> str:
    h = host.lower().rstrip(".")
    berubah = True
    while berubah and h.count(".") >= 2:
        berubah = False
        for pref in PREFIX_SUBDOMAIN_UMUM:
            if h.startswith(pref):
                h = h[len(pref):]
                berubah = True
                break
    return h


def _adalah_host_lokal(host: str) -> bool:
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _ekstrak_video_id_youtube(host: str, path: str, query_items: list[tuple[str, str]]) -> str | None:
    if host == "youtu.be":
        seg = [s for s in path.split("/") if s]
        return seg[0] if seg else None
    if path == "/watch":
        for k, v in query_items:
            if k == "v" and v:
                return v.strip("/") or None
        return None
    for pref in ("/shorts/", "/embed/", "/live/", "/v/"):
        if path.startswith(pref):
            sisa = path[len(pref):].lstrip("/")
            vid = sisa.split("/", 1)[0]
            return vid or None
    return None


def _kanonisasi_platform(
    host: str,
    path: str,
    query_items: list[tuple[str, str]],
) -> tuple[str, str, list[tuple[str, str]]]:
    if host in {"youtube.com", "youtu.be", "youtube-nocookie.com"}:
        vid = _ekstrak_video_id_youtube(host, path, query_items)
        if vid:
            return "youtube.com", "/watch", [("v", vid)]
        dibuang = {"t", "si", "pp", "feature", "ab_channel"}
        return host, path, [(k, v) for k, v in query_items if k.lower() not in dibuang]

    if host == "tiktok.com":
        if re.match(r"^/@[^/]+/(video|photo)/\d+$", path):
            return "tiktok.com", path, []
        return host, path, query_items

    if host == "instagram.com":
        path_ig = "/reel/" + path[len("/reels/"):] if path.startswith("/reels/") else path
        if any(path_ig.startswith(p) for p in ("/p/", "/reel/", "/tv/", "/stories/")):
            return "instagram.com", path_ig, []
        return "instagram.com", path_ig, query_items

    if host in {"twitter.com", "x.com"}:
        dibuang_x = {"s", "t", "ref", "ref_src", "ref_url"}
        if re.search(r"/status/\d+$", path):
            return "x.com", path, []
        return "x.com", path, [(k, v) for k, v in query_items if k.lower() not in dibuang_x]

    if host == "facebook.com":
        bersih = [
            (k, v)
            for k, v in query_items
            if k.lower() not in {"ref", "__tn__"} and not k.lower().startswith("__cft__")
        ]
        if path == "/watch":
            v_param = [(k, v) for k, v in bersih if k == "v" and v]
            if v_param:
                return "facebook.com", "/watch", v_param
        return "facebook.com", path, bersih

    return host, path, query_items


def normalisasi_url(url: str) -> str:
    """Kanonisasi URL sebelum di-hash menjadi `doc_id` agar variasi URL yang sama tidak menduplikasi dokumen."""
    mentah = str(url or "").strip()
    if not mentah:
        return ""

    parsed = urlsplit(mentah)
    if not parsed.scheme or not parsed.netloc:
        if re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/.*)?$", mentah):
            parsed = urlsplit(f"https://{mentah}")
        else:
            return mentah.replace("\\", "/")

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return mentah

    host_awal = (parsed.hostname or "").lower().rstrip(".")
    if not host_awal:
        return mentah

    try:
        port = parsed.port
    except ValueError:
        port = None

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    lokal = _adalah_host_lokal(host_awal)
    if scheme == "http" and not lokal and port is None:
        scheme = "https"

    host = host_awal if lokal else _strip_prefix_host(host_awal)
    path_raw = re.sub(r"/+", "/", parsed.path or "")
    path = quote(unquote(path_raw), safe="/:@!$&'()*+,;=-._~").rstrip("/")

    query_bersih = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in PARAMETER_TRACKING
    ]

    host, path, query_final = _kanonisasi_platform(host, path, query_bersih)
    host_netloc = f"[{host}]" if ":" in host else host
    netloc = f"{host_netloc}:{port}" if port is not None else host_netloc
    query_str = urlencode(sorted(query_final), doseq=True)
    return urlunsplit((scheme, netloc, path, query_str, ""))


def doc_id_dari_url(url: str, panjang: int = 24) -> str:
    """Hasilkan `doc_id` deterministik dari hash SHA-256 URL yang telah dinormalisasi."""
    kanonis = normalisasi_url(url)
    if not kanonis:
        raise ValueError("URL tidak boleh kosong untuk membentuk doc_id")
    digest = hashlib.sha256(kanonis.encode("utf-8")).hexdigest()[:panjang]
    return f"doc_{digest}"


def penerbit_dari_url(url: str, uploader: str | None = None) -> str:
    """Identitas penerbit untuk korroborasi: satu penerbit = satu suara.

    Platform video/sosial memakai nama kanal/akun (karena domainnya sama untuk semua pengunggah);
    situs biasa memakai domain kanonis.
    """
    kanonis = normalisasi_url(url)
    host = (urlsplit(kanonis).hostname or "").lower() if kanonis.startswith("http") else ""
    nama = " ".join((uploader or "").lower().split())
    platform = {"youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com", "facebook.com", "fb.watch"}
    if host in platform:
        if nama:
            return f"{host}/{nama}"
        path = urlsplit(kanonis).path
        akun = re.match(r"^/(@[^/]+|[^/]+)/(video|photo|status|reel|p)/", path)
        if akun:
            return f"{host}/{akun.group(1).lower()}"
        return f"{host}/?{kanonis}"   # akun tak diketahui: anggap penerbit unik per URL
    return host or kanonis
