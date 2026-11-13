"""Modul OCR & deduplikasi teks layar menggunakan Gemini Multimodal Structured Output.

Menggantikan OCR lokal + filter deduplikasi manual: Gemini langsung membaca teks
overlay, judul berita, lower-third, watermark, dan tanggal di layar dari rangkaian
keyframes sekaligus mendeduplikasi teks yang tampil berulang antar-frame.
"""

import hashlib
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

import config
import llm

log = logging.getLogger("netra.ai.ocr")

KategoriTeksOCR = Literal[
    "overlay",
    "judul_berita",
    "lower_third",
    "watermark",
    "tanggal_layar",
    "lainnya",
]

AMBANG_DEDUP_FALLBACK = 0.85
MAKS_BYTES_GAMBAR = 15 * 1024 * 1024


class OCRError(Exception):
    pass


class ItemTeksOCR(BaseModel):
    teks: str
    kategori: KategoriTeksOCR = "overlay"
    detik_awal: float | None = None
    detik_akhir: float | None = None


class HasilOCR(BaseModel):
    items: list[ItemTeksOCR] = []
    teks_unik: list[str] = []
    watermark_terdeteksi: list[str] = []
    tanggal_di_layar: str | None = None
    sumber_ocr: str = "gemini"  # "gemini", "kosong", atau "gagal"
    catatan: str | None = None


SCHEMA_OCR = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "teks": {"type": "STRING"},
                    "kategori": {
                        "type": "STRING",
                        "enum": [
                            "overlay",
                            "judul_berita",
                            "lower_third",
                            "watermark",
                            "tanggal_layar",
                            "lainnya",
                        ],
                    },
                    "detik_awal": {"type": "NUMBER"},
                    "detik_akhir": {"type": "NUMBER"},
                },
                "required": ["teks", "kategori"],
            },
        },
        "watermark_terdeteksi": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "tanggal_di_layar": {
            "type": "STRING",
            "nullable": True,
        },
    },
    "required": ["items", "watermark_terdeteksi"],
}

PROMPT_OCR = """Kamu analis visual pemeriksa fakta TNI AD.
Baca semua teks yang terlihat pada rangkaian gambar/keyframe berurutan di bawah ini.

Aturan ketat:
1. Ekstrak hanya teks yang benar-benar terlihat di gambar (teks overlay/caption, judul berita, lower-third TV, watermark/nama akun, dan tanggal/waktu di layar). Jangan mengarang teks.
2. DEDUPLIKASI: Jika teks yang sama (atau hampir identik) muncul berulang di beberapa frame berurutan, gabungkan menjadi SATU item saja, lalu isi `detik_awal` (kemunculan pertama) dan `detik_akhir` (kemunculan terakhir) berdasarkan label `Frame @ XX.XXs`.
3. Isi `watermark_terdeteksi` dengan nama platform/akun/logo media yang terlihat (mis. "@akun", "TikTok", "KompasTV"), kosongkan array jika tidak ada.
4. Isi `tanggal_di_layar` jika ada tanggal/tahun kejadian yang tercetak di gambar atau video, atau null jika tidak ada."""


def _normalisasi_teks(teks: str) -> str:
    return re.sub(r"\s+", " ", teks).strip()


def _kunci_mirip(teks: str) -> str:
    return re.sub(r"[^\w\s]", "", teks.lower()).strip()


def _gabung_rentang(awal_a: float | None, awal_b: float | None, fungsi) -> float | None:
    kandidat = [v for v in (awal_a, awal_b) if v is not None]
    return fungsi(kandidat) if kandidat else None


def deduplikasi_item(items: list[ItemTeksOCR], ambang: float = AMBANG_DEDUP_FALLBACK) -> list[ItemTeksOCR]:
    """Pengaman deduplikasi teks antar-frame jika LLM masih menyisakan entri mirip (>85%)."""
    hasil: list[ItemTeksOCR] = []
    for item in items:
        teks_bersih = _normalisasi_teks(item.teks)
        if not teks_bersih:
            continue
        kunci_baru = _kunci_mirip(teks_bersih)
        kandidat = item.model_copy(update={"teks": teks_bersih})

        cocok_idx = None
        for idx, ada in enumerate(hasil):
            kunci_ada = _kunci_mirip(ada.teks)
            if not kunci_baru or not kunci_ada:
                continue
            rasio = SequenceMatcher(None, kunci_ada, kunci_baru).ratio()
            if rasio >= ambang and ada.kategori == kandidat.kategori:
                cocok_idx = idx
                break

        if cocok_idx is None:
            hasil.append(kandidat)
            continue

        lama = hasil[cocok_idx]
        teks_terbaik = kandidat.teks if len(kandidat.teks) > len(lama.teks) else lama.teks
        hasil[cocok_idx] = ItemTeksOCR(
            teks=teks_terbaik,
            kategori=lama.kategori,
            detik_awal=_gabung_rentang(lama.detik_awal, kandidat.detik_awal, min),
            detik_akhir=_gabung_rentang(lama.detik_akhir, kandidat.detik_akhir, max),
        )
    return hasil


def _dedup_string(daftar: list[str]) -> list[str]:
    unik: list[str] = []
    terlihat: set[str] = set()
    for raw in daftar:
        bersih = _normalisasi_teks(str(raw))
        kunci = bersih.lower()
        if bersih and kunci not in terlihat:
            terlihat.add(kunci)
            unik.append(bersih)
    return unik


def ocr_keyframes(keyframes: list[tuple[float, Path]], fallback_aman: bool = True) -> HasilOCR:
    """Baca dan deduplikasi teks dari daftar (detik, path_gambar) memakai Gemini structured output."""
    valid = [(detik, path) for detik, path in keyframes if path.exists()]
    if not valid:
        return HasilOCR(sumber_ocr="kosong")

    parts = [llm.part_teks(PROMPT_OCR)]
    for detik, path in valid:
        parts.append(llm.part_teks(f"Frame @ {detik:.2f}s"))
        parts.append(llm.part_file(path))

    try:
        mentah = llm.tanya_multimodal_json(parts, suhu=0.1, skema=SCHEMA_OCR)
        if not isinstance(mentah, dict):
            raise ValueError("Respons OCR bukan JSON object")
        parsed = HasilOCR.model_validate(mentah)
    except (llm.LLMError, ValidationError, ValueError, TypeError) as e:
        log.warning("OCR Gemini gagal: %s", e)
        if not fallback_aman:
            raise OCRError(str(e)) from e
        return HasilOCR(sumber_ocr="gagal", catatan=str(e))

    items = deduplikasi_item(parsed.items)
    watermark = _dedup_string(parsed.watermark_terdeteksi)
    tanggal = _normalisasi_teks(parsed.tanggal_di_layar) if parsed.tanggal_di_layar else None
    teks_unik = _dedup_string([item.teks for item in items])

    return HasilOCR(
        items=items,
        teks_unik=teks_unik,
        watermark_terdeteksi=watermark,
        tanggal_di_layar=tanggal or None,
        sumber_ocr="gemini",
    )


def _unduh_gambar(url: str) -> Path:
    folder = config.WORK_DIR / f"ai_img_{hashlib.md5(url.encode()).hexdigest()[:12]}"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        r = httpx.get(url, follow_redirects=True, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise OCRError(f"Gagal mengunduh gambar: {e}") from e

    if len(r.content) > MAKS_BYTES_GAMBAR:
        raise OCRError("Ukuran gambar melebihi batas 15 MB")

    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg"}.get(ct, ".jpg")
    target = folder / f"gambar{ext}"
    target.write_bytes(r.content)
    return target


def ocr_gambar(sumber: str | Path, fallback_aman: bool = True) -> HasilOCR:
    """Jalankan OCR terstruktur pada satu gambar (path lokal atau URL publik)."""
    if isinstance(sumber, Path) or not str(sumber).startswith(("http://", "https://")):
        return ocr_keyframes([(0.0, Path(sumber))], fallback_aman=fallback_aman)

    try:
        lokal = _unduh_gambar(str(sumber))
    except OCRError as e:
        if not fallback_aman:
            raise
        return HasilOCR(sumber_ocr="gagal", catatan=str(e))
    return ocr_keyframes([(0.0, lokal)], fallback_aman=fallback_aman)

