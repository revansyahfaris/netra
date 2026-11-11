"""Parser tanggal sederhana untuk hasil pencarian (Inggris & Indonesia, absolut & relatif)."""

import re
from datetime import datetime, timedelta, timezone

BULAN = {
    "jan": 1, "januari": 1, "january": 1,
    "feb": 2, "februari": 2, "february": 2, "peb": 2,
    "mar": 3, "maret": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5, "mei": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "agu": 8, "agt": 8, "agustus": 8, "august": 8, "ags": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "okt": 10, "oktober": 10, "october": 10,
    "nov": 11, "november": 11, "nop": 11,
    "dec": 12, "des": 12, "desember": 12, "december": 12,
}
SATUAN = {
    "minute": 1 / 1440, "menit": 1 / 1440, "hour": 1 / 24, "jam": 1 / 24,
    "day": 1, "hari": 1, "week": 7, "minggu": 7, "month": 30, "bulan": 30, "year": 365, "tahun": 365,
}


def parse(teks: str | None, sekarang: datetime | None = None) -> datetime | None:
    if not teks:
        return None
    t = str(teks).lower().strip()
    sekarang = sekarang or datetime.now(timezone.utc)

    # 20190821 (format yt-dlp)
    if re.fullmatch(r"\d{8}", t):
        return datetime.strptime(t, "%Y%m%d").replace(tzinfo=timezone.utc)
    # 2019-08-21...
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return datetime(*map(int, m.groups()), tzinfo=timezone.utc)
    # "5 years ago" / "3 hari yang lalu" / "streamed 2 weeks ago"
    m = re.search(r"(\d+)\s+(minute|menit|hour|jam|day|hari|week|minggu|month|bulan|year|tahun)", t)
    if m and ("ago" in t or "lalu" in t):
        return sekarang - timedelta(days=int(m.group(1)) * SATUAN[m.group(2)])
    # "21 Agu 2019" / "21 agustus 2019"
    m = re.search(r"(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})", t)
    if m and m.group(2) in BULAN:
        return datetime(int(m.group(3)), BULAN[m.group(2)], int(m.group(1)), tzinfo=timezone.utc)
    # "Aug 21, 2019"
    m = re.search(r"([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1) in BULAN:
        return datetime(int(m.group(3)), BULAN[m.group(1)], int(m.group(2)), tzinfo=timezone.utc)
    return None
