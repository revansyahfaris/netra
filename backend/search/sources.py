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
    "tirto.id", "katadata.co.id", "validnews.id", "narasi.tv", "nu.or.id", "mafindo.or.id",
    "thejakartapost.com", "jakartaglobe.id", "rmol.id", "mongabay.co.id", "kbr.id",
    "investor.id", "hukumonline.com", "suaramerdeka.com", "krjogja.com", "tempo.co.id",
    "voaindonesia.com", "dw.com", "aljazeera.com", "apnews.com", "afp.com", "bbc.co.uk",
    "channelnewsasia.com", "abc.net.au", "benarnews.org", "antarafoto.com",
}
KANAL_MEDIA = {
    "kompastv", "kompas tv", "kompas.com", "kompascom", "metro tv", "metrotv",
    "tvonenews", "cnn indonesia", "berita satu", "beritasatu", "inews", "official inews",
    "inews id", "inews official", "detikcom", "tribunnews", "tempo.co", "tempodotco",
    "majalah tempo", "koran tempo", "antara news", "antaranews", "antaranews official",
    "lkbn antara", "liputan6", "liputan6.com", "republika.co.id", "republika official",
    "republika online", "kumparan", "kumparancom", "cnbc indonesia", "cnbcindonesia",
    "medcom.id", "idn times", "suara.com", "merdeka.com", "merdekadotcom", "viva.co.id",
    "vivacoid", "jpnn.com", "tvri nasional", "tvri news", "rri net official",
    "rri official", "rri.co.id", "narasi", "narasi newsroom", "narasitv", "tirto.id",
    "tirtoid", "nu online", "nu.or.id", "katadata", "katadata.co.id", "the jakarta post",
    "bbc news indonesia", "bbc indonesia", "bbcindonesia", "bbc news", "voa indonesia",
    "dw indonesia", "al jazeera english", "al jazeera", "reuters", "associated press",
    "afp", "channel newsasia", "sctv", "indosiar", "trans7 official", "transtv official",
}

# Platform yang biasanya menambahkan watermark/overlay saat video diunggah ulang
PLATFORM_WATERMARK = {"tiktok.com", "instagram.com", "likee.video", "snackvideo.com", "capcut.com"}


def domain(url: str) -> str:
    host = (urlparse(str(url)).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _cocok_domain(host: str, daftar: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in daftar)


def _kandidat_nama_kanal(uploader: str | None) -> list[str]:
    if not uploader:
        return []
    up = uploader.lower().strip()
    kandidat = [up, up.lstrip("@")]
    for sep in ("·", "|"):
        if sep in up:
            for bagian in up.split(sep):
                b = bagian.strip()
                if b:
                    kandidat.extend((b, b.lstrip("@")))
    return kandidat


def jenis_sumber(url: str, uploader: str | None = None) -> str:
    host = domain(url)
    kandidat = _kandidat_nama_kanal(uploader)
    if _cocok_domain(host, DOMAIN_RESMI) or any(k in KANAL_RESMI for k in kandidat):
        return "resmi"
    if _cocok_domain(host, DOMAIN_MEDIA) or any(k in KANAL_MEDIA for k in kandidat):
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
