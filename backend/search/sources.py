"""Mengenali jenis sumber dari URL dan perkiraan watermark."""

from urllib.parse import urlparse

# Tambah/ubah daftar ini sesuai kebutuhan demo
DOMAIN_RESMI = {
    "tniad.mil.id", "tni.mil.id", "kemhan.go.id", "puspen.tni.mil.id",
    "setneg.go.id", "presidenri.go.id", "polri.go.id", "kominfo.go.id", "komdigi.go.id",
}
KANAL_RESMI = {  # nama kanal/akun resmi di platform video (huruf kecil)
    "tni angkatan darat", "dispenad", "tniad_mil_id", "puspen tni", "tni_angkatan_darat",
}
DOMAIN_MEDIA = {
    "kompas.com", "detik.com", "tempo.co", "cnnindonesia.com", "antaranews.com", "liputan6.com",
    "tribunnews.com", "kumparan.com", "republika.co.id", "okezone.com", "sindonews.com",
    "metrotvnews.com", "tvonenews.com", "beritasatu.com", "idntimes.com", "suara.com",
    "cnbcindonesia.com", "jawapos.com", "medcom.id", "inews.id", "turnbackhoax.id", "cekfakta.com",
    "kompas.id", "kompas.tv", "espos.id", "solopos.com", "suarakarya.id", "merdeka.com", "viva.co.id",
    "jpnn.com", "rri.co.id", "tvrinews.com", "bisnis.com", "mediaindonesia.com", "gatra.com", "kontan.co.id",
    "kompasiana.com", "merahputih.com", "harianjogja.com", "pikiran-rakyat.com", "jabarekspres.com", "bbc.com", "reuters.com",
}
KANAL_MEDIA = {"kompastv", "kompas tv", "metro tv", "metrotv", "tvonenews", "cnn indonesia", "berita satu", "inews", "detikcom", "tribunnews"}

# Platform yang biasanya menambahkan watermark/overlay saat video diunggah ulang
PLATFORM_WATERMARK = {"tiktok.com", "instagram.com", "likee.video", "snackvideo.com", "capcut.com"}


def domain(url: str) -> str:
    host = (urlparse(str(url)).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _cocok_domain(host: str, daftar: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in daftar)


def jenis_sumber(url: str, uploader: str | None = None) -> str:
    host = domain(url)
    up = (uploader or "").lower().strip()
    if _cocok_domain(host, DOMAIN_RESMI) or up in KANAL_RESMI:
        return "resmi"
    if _cocok_domain(host, DOMAIN_MEDIA) or up in KANAL_MEDIA:
        return "media"
    return "pribadi"


def perkiraan_watermark(url: str) -> bool | None:
    """True kalau dari platform yang biasa menambah watermark, False kalau sumber resmi, None kalau tidak tahu."""
    host = domain(url)
    if _cocok_domain(host, PLATFORM_WATERMARK):
        return True
    if jenis_sumber(url) == "resmi":
        return False
    return None
