"""Klasifikasi topik & tingkat sensitivitas klaim terhadap TNI AD.

Utama: LLM. Cadangan (kalau LLM mati/error): daftar kata kunci.
"""

import logging
from dataclasses import dataclass

import llm

log = logging.getLogger("netra.priority")

# Sensitivitas dasar per topik (0-1). Disesuaikan bersama tim / hasil validasi Yudhit.
SENSITIVITAS_TOPIK = {
    "pimpinan": 1.0,     # kutipan/pernyataan atas nama pimpinan TNI AD
    "operasi": 0.9,      # operasi militer, wilayah konflik, kekerasan aparat
    "sara": 0.85,        # isu SARA yang menyeret TNI
    "keselamatan": 0.8,  # ancaman, bencana, keselamatan publik
    "umum": 0.4,         # rekrutmen, kegiatan rutin, dll.
}

KATA_KUNCI = {
    "pimpinan": ["kasad", "panglima", "pangdam", "danrem", "dandim", "jenderal", "wakasad", "pangkostrad"],
    "operasi": ["papua", "kkb", "operasi", "bentrok", "tembak", "bubarkan", "membubarkan", "pukul", "aniaya", "senjata"],
    "sara": ["agama", "suku", "ras", "kafir", "pribumi", "aseng", "etnis"],
    "keselamatan": ["bom", "ledakan", "bencana", "gempa", "evakuasi", "ancaman", "darurat"],
}

PROMPT = """Kamu analis Dinas Penerangan TNI AD. Klasifikasikan klaim viral berikut.

Klaim: "{teks}"

Pilih satu label_topik:
- pimpinan: menyebut/mengutip pimpinan TNI AD (Kasad, Pangdam, Danrem, dll.)
- operasi: operasi militer, wilayah konflik, tindakan aparat terhadap warga
- sara: isu suku, agama, ras, antargolongan yang menyeret TNI
- keselamatan: ancaman keamanan, bencana, keselamatan publik
- umum: selain itu (rekrutmen, kegiatan rutin, dll.)

Beri sensitivitas 0-1: seberapa besar kerusakan reputasi/keamanan jika klaim ini salah dan terus menyebar.

Jawab JSON saja: {{"label_topik": "...", "sensitivitas": 0.0, "alasan": "maks 12 kata"}}"""


@dataclass
class HasilKlasifikasi:
    label_topik: str
    sensitivitas: float
    alasan: str
    sumber: str  # "llm" atau "keyword"


def klasifikasi_keyword(teks: str) -> HasilKlasifikasi:
    t = teks.lower()
    cocok = {label: [w for w in kata if w in t] for label, kata in KATA_KUNCI.items()}
    cocok = {k: v for k, v in cocok.items() if v}
    if not cocok:
        return HasilKlasifikasi("umum", SENSITIVITAS_TOPIK["umum"], "tidak ada kata kunci sensitif", "keyword")
    # Ambil topik dengan sensitivitas tertinggi di antara yang cocok
    label = max(cocok, key=lambda k: SENSITIVITAS_TOPIK[k])
    # Tiap kata kunci tambahan menaikkan sedikit sensitivitas
    sens = min(SENSITIVITAS_TOPIK[label] + 0.03 * (sum(map(len, cocok.values())) - 1), 1.0)
    return HasilKlasifikasi(label, round(sens, 2), f"menyebut {', '.join(cocok[label][:2])}", "keyword")


def klasifikasi(teks: str) -> HasilKlasifikasi:
    try:
        j = llm.tanya_json(PROMPT.format(teks=teks))
        label = j.get("label_topik", "umum")
        if label not in SENSITIVITAS_TOPIK:
            label = "umum"
        sens = float(j.get("sensitivitas", SENSITIVITAS_TOPIK[label]))
        return HasilKlasifikasi(label, max(0.0, min(sens, 1.0)), str(j.get("alasan", "")).strip(), "llm")
    except (llm.LLMError, ValueError, TypeError, AttributeError) as e:
        log.info("Klasifikasi pakai keyword (%s)", e)
        return klasifikasi_keyword(teks)
