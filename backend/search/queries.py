"""Membuat variasi query pencarian dari teks klaim.

- kutipan: kalimat persis yang diklaim diucapkan (dicari dengan tanda kutip)
- keyword: variasi kata kunci, termasuk yang mengarah ke kejadian ASLI
  (misal video lama yang diberi narasi baru)
"""

import logging
import re

import llm

from .models import KonteksSinyal

log = logging.getLogger("netra.search")

PROMPT = """Kamu pemeriksa fakta. Dari klaim viral berikut, buat query pencarian untuk menemukan SUMBER ASLI-nya.

Klaim: "{teks}"

Aturan:
- "kutipan": HANYA frasa ucapan langsung yang persis diapit tanda kutip ("..." atau '...') di teks klaim. Isi [] jika klaim hanya berupa parafrase tidak langsung atau tidak mencantumkan ucapan bertanda kutip (jangan masukkan kalimat seperti "Si A berkomentar bahwa..." ke kutipan).
- "keyword": 3-4 variasi query pendek (maks 8 kata) dalam bahasa Indonesia. Hilangkan klaim waktu/narasi
  yang mungkin dipelintir (misal "minggu ini", "baru saja"), fokus pada peristiwa, tokoh, dan lokasi,
  supaya rekaman/berita aslinya ikut ketemu. Jangan membatasi "keyword" ke instansi tertentu kecuali memang relevan dengan tokoh/peristiwa di klaim.

Jawab JSON saja: {{"kutipan": ["..."], "keyword": ["...", "..."]}}"""

STOPWORDS = set(
    "yang dan di ke dari ini itu untuk dengan pada adalah akan sudah telah disebut diklaim katanya "
    "viral beredar video foto gambar minggu hari tadi baru saja sedang lagi oleh sebagai juga bahwa "
    "dalam atau tidak bukan ada para sang si terjadi kejadian menyatakan mengatakan bilang".split()
)

POLA_KUTIPAN = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{8,200})[\"“”'‘’]")


def _fallback(teks: str) -> dict[str, list[str]]:
    kutipan = [m.strip() for m in POLA_KUTIPAN.findall(teks)]
    tanpa_kutipan = POLA_KUTIPAN.sub(" ", teks)
    kata = [w for w in re.findall(r"[\w-]+", tanpa_kutipan.lower()) if w not in STOPWORDS and len(w) > 2]
    inti = " ".join(kata[:8])
    keyword = [inti] if inti else []
    if inti and "tni" not in inti:
        keyword.append(f"TNI AD {' '.join(kata[:5])}")
    if kutipan:
        # cari juga pernyataan asli tokoh tersebut di sekitar topik kutipan
        kata_kutipan = [w for w in re.findall(r"[\w-]+", kutipan[0].lower()) if w not in STOPWORDS and len(w) > 2]
        keyword.append(" ".join(kata[:3] + kata_kutipan[:4]))
    return {"kutipan": kutipan, "keyword": keyword}


def _ringkas_kata(teks: str, maks_kata: int) -> str:
    kata = [w for w in re.findall(r"[\w-]+", teks.lower()) if w not in STOPWORDS and len(w) > 2]
    return " ".join(kata[:maks_kata])


def query_peristiwa(konteks: KonteksSinyal | None, maks: int = 3) -> list[str]:
    """Query berbasis apa yang TAMPAK/TERDENGAR di video (OCR, watermark, STT), bukan narasi klaim.

    Narasi klaim sering dipelintir; teks lower-third, nama kanal berita, dan ucapan asli lebih
    sering mengarah ke rekaman/berita sumbernya.
    """
    if konteks is None:
        return []
    hasil: list[str] = []
    for teks in konteks.ocr_teks[:4]:
        q = _ringkas_kata(teks, 8)
        if len(q.split()) >= 2:
            hasil.append(q)
    if konteks.stt_teks.strip():
        q = _ringkas_kata(konteks.stt_teks, 8)
        if len(q.split()) >= 3:
            hasil.append(q)
    if konteks.watermark and hasil:
        # Nama kanal/media dari watermark mempersempit ke unggahan media tersebut
        hasil.append(f"{konteks.watermark[0]} {hasil[0]}".strip())
    unik = list(dict.fromkeys(q for q in hasil if q))
    return unik[:maks]


def _blok_konteks(konteks: KonteksSinyal | None) -> str:
    if konteks is None:
        return ""
    bagian = []
    if konteks.stt_teks.strip():
        bagian.append(f"Transkrip ucapan di video: \"{konteks.stt_teks.strip()[:600]}\"")
    if konteks.ocr_teks:
        bagian.append("Teks di layar video: " + " | ".join(konteks.ocr_teks[:6])[:600])
    if konteks.watermark:
        bagian.append("Watermark/logo kanal: " + ", ".join(konteks.watermark[:3]))
    if not bagian:
        return ""
    return (
        "\n\nSinyal dari video (lebih bisa dipercaya daripada narasi klaim):\n"
        + "\n".join(bagian)
        + "\nPakai sinyal ini untuk membuat query yang menemukan rekaman/berita aslinya."
    )


def _kutipan_valid(teks_klaim: str, kandidat: list[str]) -> list[str]:
    """Hanya pakai query exact-match kutipan bila klaim memang memuat petikan langsung."""
    ada_tanda_kutip = any(t in teks_klaim for t in ('"', "'", "“", "”", "‘", "’"))
    if not ada_tanda_kutip:
        return []
    klaim_lower = teks_klaim.strip().lower()
    hasil: list[str] = []
    for k in kandidat:
        bersih = k.strip().strip('"\'“”‘’').strip()
        if not bersih:
            continue
        # Hindari memasukkan ulang kalimat parafrase penuh sebagai kutipan exact match
        if bersih.lower() == klaim_lower and not POLA_KUTIPAN.search(teks_klaim):
            continue
        hasil.append(bersih)
    return hasil[:2]


def buat_query(teks_klaim: str, konteks: KonteksSinyal | None = None) -> dict[str, list[str]]:
    peristiwa = query_peristiwa(konteks)
    try:
        j = llm.tanya_json(PROMPT.format(teks=teks_klaim) + _blok_konteks(konteks), suhu=0.4)
        kutipan = _kutipan_valid(teks_klaim, [str(q) for q in j.get("kutipan", []) if str(q).strip()])
        keyword = [str(q).strip() for q in j.get("keyword", []) if str(q).strip()][:4]
        if not keyword:
            raise ValueError("LLM tidak memberi keyword")
        return {"kutipan": kutipan, "keyword": keyword, "peristiwa": peristiwa}
    except (llm.LLMError, ValueError, AttributeError, TypeError) as e:
        log.info("Query pakai fallback (%s)", e)
        hasil = _fallback(teks_klaim)
        hasil["peristiwa"] = peristiwa
        return hasil
