"""Membuat variasi query pencarian dari teks klaim.

- kutipan: kalimat persis yang diklaim diucapkan (dicari dengan tanda kutip)
- keyword: variasi kata kunci, termasuk yang mengarah ke kejadian ASLI
  (misal video lama yang diberi narasi baru)
"""

import logging
import re

import llm

log = logging.getLogger("netra.search")

PROMPT = """Kamu pemeriksa fakta. Dari klaim viral berikut, buat query pencarian untuk menemukan SUMBER ASLI-nya.

Klaim: "{teks}"

Aturan:
- "kutipan": kalimat yang diklaim diucapkan seseorang, persis seperti di klaim (kosongkan kalau tidak ada kutipan).
- "keyword": 3-4 variasi query pendek (maks 8 kata) dalam bahasa Indonesia. Hilangkan klaim waktu/narasi
  yang mungkin dipelintir (misal "minggu ini", "baru saja"), fokus pada peristiwa, tokoh, dan lokasi,
  supaya rekaman/berita aslinya ikut ketemu. Sertakan satu variasi yang memakai nama resmi (misal "TNI AD").

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


def buat_query(teks_klaim: str) -> dict[str, list[str]]:
    try:
        j = llm.tanya_json(PROMPT.format(teks=teks_klaim), suhu=0.4)
        kutipan = [str(q).strip() for q in j.get("kutipan", []) if str(q).strip()]
        keyword = [str(q).strip() for q in j.get("keyword", []) if str(q).strip()][:4]
        if not keyword:
            raise ValueError("LLM tidak memberi keyword")
        return {"kutipan": kutipan[:2], "keyword": keyword}
    except (llm.LLMError, ValueError, AttributeError, TypeError) as e:
        log.info("Query pakai fallback (%s)", e)
        return _fallback(teks_klaim)
