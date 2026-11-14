"""Tahap 4: Cross-Verification (Penalaran Perbandingan Fakta oleh LLM).

Membandingkan sinyal konten viral dari Tahap 1 (`SinyalKonten`) dengan bukti sumber
acuan Tier-1 (`SinyalSumberAcuan` / `KandidatSumber`) dan/atau rujukan korpus resmi
Tier-2 RAG (`HasilCariKorpus`) menggunakan Gemini Multimodal Structured Output.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, ValidationError

import config
import llm
from schemas import (
    Bukti,
    JenisBukti,
    JenisPerubahan,
    KandidatSumber,
    Klaim,
    MetodeVerifikasi,
    StatusVerifikasi,
)

from .ocr import HasilOCR, MAKS_BYTES_GAMBAR
from .rag import HasilCariKorpus
from .routing import HasilTahap2, JalurVerifikasi, SinyalKonten
from .stt import SegmenTranskrip
from .sumber import SinyalSumberAcuan

log = logging.getLogger("netra.ai.verifikasi")

AMBANG_KEYAKINAN_PUTUSAN = 0.60
MAKS_SEGMEN_STT_PROMPT = 20
MAKS_KARAKTER_ISI_SUMBER = 3500
MAKS_KARAKTER_KUTIPAN_RAG = 1200
MAKS_BYTES_VISUAL_KLAIM = min(10 * 1024 * 1024, MAKS_BYTES_GAMBAR)

EKSTENSI_VISUAL_VALID = {".jpg", ".jpeg", ".png", ".webp"}
SumberAnalisis = Literal["gemini_multimodal", "eskalasi_pra_llm", "fallback_error"]

_URL_ADAPTER = TypeAdapter(HttpUrl)


class VerifikasiError(Exception):
    pass


class AnalisisManipulasi(BaseModel):
    dipotong: bool = False
    detail_dipotong: str | None = None
    tanggal_berbeda: bool = False
    detail_tanggal: str | None = None
    kutipan_tidak_ada: bool = False
    detail_kutipan: str | None = None
    konteks_berbeda: bool = False
    detail_konteks: str | None = None
    lainnya: bool = False
    detail_lainnya: str | None = None

    def daftar_perubahan(self) -> list[JenisPerubahan]:
        hasil: list[JenisPerubahan] = []
        pemetaan: tuple[tuple[bool, JenisPerubahan], ...] = (
            (self.dipotong, "dipotong"),
            (self.tanggal_berbeda, "tanggal_berbeda"),
            (self.kutipan_tidak_ada, "kutipan_tidak_ada"),
            (self.konteks_berbeda, "konteks_berbeda"),
            (self.lainnya, "lainnya"),
        )
        for aktif, label in pemetaan:
            if aktif:
                hasil.append(label)
        return hasil


class TemuanBukti(BaseModel):
    jenis: JenisBukti
    url: str
    cuplikan: str | None = None
    teks_viral: str | None = None
    teks_sumber: str | None = None
    catatan: str | None = None


class HasilVerifikasiSilang(BaseModel):
    """Keluaran Tahap 4 (Cross-Verification) yang siap diteruskan ke Tahap 5."""

    claim_id: str
    jalur_tahap2: JalurVerifikasi
    status: StatusVerifikasi
    perlu_eskalasi: bool
    alasan_eskalasi: str | None = None
    konsisten_dengan_sumber: bool = False
    sumber_tertua_meragukan: bool = False
    keyakinan: float = Field(0.0, ge=0.0, le=1.0)
    sumber_utama_url: str | None = None
    sumber_utama_judul: str | None = None
    sumber_utama_tanggal: str | None = None
    perubahan: list[JenisPerubahan] = Field(default_factory=list)
    manipulasi: AnalisisManipulasi = Field(default_factory=AnalisisManipulasi)
    ringkasan: str = ""
    fakta_utama: str = ""
    apa_yang_diubah: str = ""
    bukti: list[TemuanBukti] = Field(default_factory=list)
    metode: list[MetodeVerifikasi] = Field(default_factory=list)
    sumber_analisis: SumberAnalisis = "gemini_multimodal"
    catatan_sistem: str | None = None


SCHEMA_VERIFIKASI_SILANG = {
    "type": "OBJECT",
    "properties": {
        "status": {
            "type": "STRING",
            "enum": ["terbukti_diubah", "tidak_ditemukan", "belum_bisa_diverifikasi"],
        },
        "keyakinan": {"type": "NUMBER"},
        "konsisten_dengan_sumber": {"type": "BOOLEAN"},
        "sumber_tertua_meragukan": {"type": "BOOLEAN"},
        "peristiwa_inti_terjadi": {"type": "BOOLEAN"},
        "bantahan_hanya_pihak_tertuduh": {"type": "BOOLEAN"},
        "sumber_utama_url": {"type": "STRING", "nullable": True},
        "manipulasi": {
            "type": "OBJECT",
            "properties": {
                "dipotong": {"type": "BOOLEAN"},
                "detail_dipotong": {"type": "STRING", "nullable": True},
                "tanggal_berbeda": {"type": "BOOLEAN"},
                "detail_tanggal": {"type": "STRING", "nullable": True},
                "kutipan_tidak_ada": {"type": "BOOLEAN"},
                "detail_kutipan": {"type": "STRING", "nullable": True},
                "konteks_berbeda": {"type": "BOOLEAN"},
                "detail_konteks": {"type": "STRING", "nullable": True},
                "lainnya": {"type": "BOOLEAN"},
                "detail_lainnya": {"type": "STRING", "nullable": True},
            },
            "required": [
                "dipotong",
                "tanggal_berbeda",
                "kutipan_tidak_ada",
                "konteks_berbeda",
                "lainnya",
            ],
        },
        "ringkasan": {"type": "STRING"},
        "fakta_utama": {"type": "STRING"},
        "apa_yang_diubah": {"type": "STRING"},
        "alasan_eskalasi": {"type": "STRING", "nullable": True},
        "bukti": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "jenis": {
                        "type": "STRING",
                        "enum": ["kutipan", "frame", "transkrip", "metadata"],
                    },
                    "url": {"type": "STRING"},
                    "cuplikan": {"type": "STRING", "nullable": True},
                    "teks_viral": {"type": "STRING", "nullable": True},
                    "teks_sumber": {"type": "STRING", "nullable": True},
                    "catatan": {"type": "STRING", "nullable": True},
                },
                "required": ["jenis", "url"],
            },
        },
    },
    "required": [
        "status",
        "keyakinan",
        "konsisten_dengan_sumber",
        "sumber_tertua_meragukan",
        "manipulasi",
        "ringkasan",
        "fakta_utama",
        "apa_yang_diubah",
        "bukti",
    ],
}

SYSTEM_PROMPT_VERIFIKASI = """Kamu adalah auditor verifikasi fakta resmi Dispenad TNI AD.
Tugasmu pada Tahap 4 (Cross-Verification) adalah membandingkan sinyal konten viral (klaim, transkrip STT beserta timestamp, teks layar OCR, dan visual bila dilampirkan) terhadap bukti sumber acuan Tier-1 serta rujukan korpus resmi Tier-2 RAG.

ATURAN KETAT BERBASIS BUKTI:
1. Nilai klaim HANYA berdasarkan bukti yang tertulis/dilampirkan pada pesan pengguna. DILARANG mengarang fakta, angka, tanggal, nama pejabat, kutipan, atau URL di luar data yang diberikan.
2. Setiap `sumber_utama_url` maupun `bukti[].url` WAJIB disalin persis dari daftar `URL sumber yang tersedia` dalam konteks (atau `media_url` klaim saat merujuk konten viral). Jangan membuat URL contoh atau menebak tautan.
3. Bila bukti menyebut alat atau hasil pemeriksaan pihak lain (misalnya artikel cek fakta yang memakai detektor AI), tulis jelas bahwa itu temuan sumber tersebut, contoh "Menurut TurnBackHoax, ...". Jangan menuliskannya seolah Netra yang menjalankan analisis itu.
4. Lacak empat bentuk manipulasi utama (plus `lainnya` bila relevan):
   - `dipotong`: kalimat/adegan dipotong keluar konteks sehingga mengubah makna utuh pernyataan atau peristiwa aslinya (periksa timestamp `[MM:SS - MM:SS]` pada segmen STT dan `cuplikan` sumber).
   - `tanggal_berbeda`: rekaman/foto/berita lama diunggah ulang dengan klaim waktu baru (bandingkan `tanggal_ditemukan` klaim, `tanggal_di_layar` OCR, dan `tanggal_unggah`/`tanggal_terbit` sumber).
   - `kutipan_tidak_ada`: pernyataan yang diklaim dalam narasi/OCR/STT tidak pernah ada di transkrip/rilis resmi/berita acuan, atau dipelintir maknanya.
   - `konteks_berbeda`: visual atau rekaman asli, tetapi diberi narasi lokasi, pelaku, satuan, atau peristiwa yang keliru.
   - `lainnya`: informasi palsu lain yang bertentangan langsung dengan rujukan resmi (misalnya pungutan biaya atau pengumuman fiktif).

PENANGANAN STATUS & ESKALASI (WORST-CASE):
- Pilih `"terbukti_diubah"` HANYA jika terdapat bukti sumber kredibel yang jelas menunjukkan manipulasi atau pertentangan fakta dengan keyakinan memadai (>= 0.60).
- Pilih `"belum_bisa_diverifikasi"` dan isi `alasan_eskalasi` dengan jelas bila:
  - Bukti antar-sumber saling bertentangan, terlalu singkat/tidak konklusif, atau keyakinan rendah (< 0.60).
  - Sumber acuan tertua/utama ikut terindikasi dimanipulasi, meragukan, atau berasal dari akun tidak otentik (`sumber_tertua_meragukan = true`).
  - Klaim terlihat selaras dengan sumber resmi dan tidak ditemukan indikasi manipulasi (`konsisten_dengan_sumber = true`): jangan memaksakan `"terbukti_diubah"`, serahkan ke petugas melalui eskalasi.
- Pilih `"tidak_ditemukan"` bila seluruh bukti pembanding yang tersaji tidak relevan maupun tidak cukup mendukung atau membantah klaim.

PERISTIWA NYATA YANG DIPERDEBATKAN (WAJIB):
- Isi `peristiwa_inti_terjadi = true` bila sumber independen (media atau lembaga yang BUKAN pihak yang dituduh) melaporkan bahwa peristiwa inti dalam klaim memang terjadi, misalnya ada penembakan, korban, atau bentrokan, walaupun detailnya berbeda dari narasi viral.
- Isi `bantahan_hanya_pihak_tertuduh = true` bila satu-satunya bantahan atas klaim berasal dari pihak yang dituduh (misalnya klaim menuduh TNI dan yang membantah hanya TNI).
- Pada kedua kondisi itu, JANGAN pilih `"terbukti_diubah"`. Pilih `"belum_bisa_diverifikasi"`, jelaskan bagian mana yang terkonfirmasi dan bagian mana yang masih diperdebatkan. Bantahan pihak yang dituduh bukan bukti independen.
- Label `dipotong` hanya boleh dipakai bila ada bukti frame atau transkrip yang menunjukkan bagian yang dipotong.

PANDUAN ISI OUTPUT:
- `ringkasan`: 1-3 kalimat ringkas, netral, dan faktual untuk petugas verifikasi.
- `fakta_utama`: inti fakta yang terbukti dari sumber pembanding (kosongkan atau jelaskan keterbatasannya bila tidak ditemukan).
- `apa_yang_diubah`: uraian spesifik bagian mana yang dimanipulasi dibanding sumber asli (kosongkan bila tidak terbukti diubah).
- `bukti`: kutip minimal 1-3 bukti kunci paling menentukan dengan pasangan `teks_viral` vs `teks_sumber` serta `cuplikan` (timestamp/kutipan singkat)."""


def _potong_teks(teks: str | None, maks: int) -> str:
    bersih = " ".join(str(teks or "").split())
    if len(bersih) <= maks:
        return bersih
    return bersih[: maks - 3].rstrip() + "..."


def _format_waktu(detik: float | None) -> str:
    if detik is None or detik < 0:
        return "--:--"
    total = int(round(detik))
    menit, sisa = divmod(total, 60)
    jam, menit = divmod(menit, 60)
    if jam:
        return f"{jam:02d}:{menit:02d}:{sisa:02d}"
    return f"{menit:02d}:{sisa:02d}"


def _format_segmen_stt(segmen: list[SegmenTranskrip], maks: int = MAKS_SEGMEN_STT_PROMPT) -> str:
    if not segmen:
        return ""
    baris: list[str] = []
    for s in segmen[:maks]:
        teks = " ".join(s.text.split())
        if teks:
            baris.append(f"[{_format_waktu(s.start)}-{_format_waktu(s.end)}] {teks}")
    if len(segmen) > maks:
        baris.append(f"... (+{len(segmen) - maks} segmen lagi)")
    return "\n".join(baris)


def _format_ocr(ocr_hasil: HasilOCR) -> list[str]:
    baris: list[str] = []
    if ocr_hasil.items:
        for item in ocr_hasil.items[:15]:
            rentang = ""
            if item.detik_awal is not None or item.detik_akhir is not None:
                rentang = f" ({_format_waktu(item.detik_awal)}-{_format_waktu(item.detik_akhir)})"
            baris.append(f"- [{item.kategori}{rentang}] {item.teks}")
    elif ocr_hasil.teks_unik:
        for teks in ocr_hasil.teks_unik[:15]:
            baris.append(f"- {teks}")
    if ocr_hasil.watermark_terdeteksi:
        baris.append(f"- Watermark terdeteksi: {', '.join(ocr_hasil.watermark_terdeteksi)}")
    if ocr_hasil.tanggal_di_layar:
        baris.append(f"- Tanggal di layar: {ocr_hasil.tanggal_di_layar}")
    return baris


def _blok_klaim_dan_sinyal(klaim: Klaim, sinyal: SinyalKonten) -> str:
    lines = [
        "=== KLAIM VIRAL & SINYAL TAHAP 1 ===",
        f"claim_id: {klaim.claim_id}",
        f"jenis_media: {klaim.jenis_media}",
        f"tanggal_ditemukan: {klaim.tanggal_ditemukan.isoformat()}",
        f"teks_klaim: {klaim.teks_klaim}",
        f"media_url_klaim: {klaim.media_url or '-'}",
        f"audio_tersedia: {'ya' if sinyal.audio_tersedia else 'tidak'} (status_stt: {sinyal.sumber_stt})",
    ]
    if sinyal.stt_teks.strip():
        lines.append(f"transkrip_stt_utuh: {_potong_teks(sinyal.stt_teks, MAKS_KARAKTER_ISI_SUMBER)}")
    segmen_teks = _format_segmen_stt(sinyal.stt_segmen)
    if segmen_teks:
        lines.append("segmen_timestamp_stt:")
        lines.append(segmen_teks)
    ocr_baris = _format_ocr(sinyal.ocr)
    if ocr_baris:
        lines.append(f"ocr_layar (sumber={sinyal.ocr.sumber_ocr}):")
        lines.extend(ocr_baris)
    if sinyal.catatan:
        lines.append(f"catatan_tahap1: {sinyal.catatan}")
    return "\n".join(lines)


def _blok_sumber_tier1(hasil_tahap2: HasilTahap2) -> str:
    lines = ["=== BUKTI SUMBER ACUAN TIER-1 (MODUL PENCARI + EKSTRAKSI TAHAP 2) ==="]
    kandidat_by_url: dict[str, KandidatSumber] = {
        str(k.url): k for k in hasil_tahap2.kandidat_bersih
    }

    if hasil_tahap2.sinyal_sumber:
        urls_tercakup: set[str] = set()
        for idx, s in enumerate(hasil_tahap2.sinyal_sumber, 1):
            urls_tercakup.add(s.url)
            meta = kandidat_by_url.get(s.url)
            lines.append(f"\n[Tier-1 #{idx}] URL: {s.url}")
            lines.append(
                f"judul: {s.judul or (meta.judul if meta else None) or '-'} | "
                f"jenis_sumber: {s.jenis_sumber} | jenis_konten: {s.jenis_konten} | "
                f"tanggal_unggah: {s.tanggal_unggah or '-'}"
            )
            if meta is not None:
                lines.append(
                    f"metode_cari: {meta.metode} | kemiripan: {meta.kemiripan:.2f} | "
                    f"skor_peringkat: {meta.skor if meta.skor is not None else '-'} | "
                    f"cuplikan: {meta.cuplikan or '-'} | "
                    f"kecocokan_audio: {meta.kecocokan_audio if meta.kecocokan_audio is not None else '-'}"
                )
            lines.append(
                f"sumber_ekstraksi: {s.sumber_ekstraksi} | "
                f"ekstraksi_penuh: {'ya' if s.ekstraksi_penuh_berhasil else 'tidak (hanya snippet/fallback)'}"
            )
            if s.jendela_mulai_detik is not None:
                lines.append(
                    f"jendela_video: mulai={_format_waktu(s.jendela_mulai_detik)}, "
                    f"durasi={s.jendela_durasi_detik or 0:.0f}s, "
                    f"titik_cuplikan={_format_waktu(s.detik_cuplikan)}"
                )
            if s.teks_isi.strip():
                lines.append(f"isi_sumber: {_potong_teks(s.teks_isi, MAKS_KARAKTER_ISI_SUMBER)}")
            segmen_sumber = _format_segmen_stt(s.stt_segmen)
            if segmen_sumber:
                lines.append("segmen_timestamp_sumber:")
                lines.append(segmen_sumber)
            ocr_sumber = _format_ocr(s.ocr)
            if ocr_sumber:
                lines.append("ocr_sumber:")
                lines.extend(ocr_sumber)
            if s.catatan:
                lines.append(f"catatan_ekstraksi: {s.catatan}")

        sisa = [k for k in hasil_tahap2.kandidat_bersih if str(k.url) not in urls_tercakup]
        if sisa:
            lines.append("\nKandidat bersih Tier-1 tambahan (metadata):")
            for k in sisa:
                tgl = k.tanggal_unggah.isoformat() if k.tanggal_unggah else "-"
                lines.append(
                    f"- URL: {k.url} | jenis: {k.jenis_sumber} | tgl: {tgl} | "
                    f"skor: {k.skor if k.skor is not None else '-'} | judul: {k.judul or '-'} | cuplikan: {k.cuplikan or '-'}"
                )
    elif hasil_tahap2.kandidat_bersih:
        for idx, k in enumerate(hasil_tahap2.kandidat_bersih, 1):
            tgl = k.tanggal_unggah.isoformat() if k.tanggal_unggah else "-"
            lines.append(
                f"[Tier-1 Meta #{idx}] URL: {k.url} | jenis: {k.jenis_sumber} | tgl: {tgl} | "
                f"kemiripan: {k.kemiripan:.2f} | judul: {k.judul or '-'} | cuplikan: {k.cuplikan or '-'}"
            )
    else:
        lines.append("Tidak ada kandidat sumber bersih Tier-1.")

    if hasil_tahap2.kandidat_ditolak:
        lines.append("\nKandidat Tier-1 yang ditolak (akun pribadi/berwatermark — hanya sebagai peringatan konteks):")
        for k in hasil_tahap2.kandidat_ditolak:
            tgl = k.tanggal_unggah.isoformat() if k.tanggal_unggah else "-"
            lines.append(
                f"- URL: {k.url} | jenis: {k.jenis_sumber} | watermark: {k.ada_watermark} | "
                f"tgl: {tgl} | kemiripan: {k.kemiripan:.2f} | judul: {k.judul or '-'}"
            )
    return "\n".join(lines)


def _blok_rag(hasil_rag: list[HasilCariKorpus]) -> str:
    lines = ["=== RUJUKAN KORPUS RESMI TIER-2 RAG ==="]
    if not hasil_rag:
        lines.append("Tidak ada rujukan korpus resmi dari Tahap 3 RAG.")
        return "\n".join(lines)

    for idx, item in enumerate(hasil_rag, 1):
        rentang = ""
        if item.detik_mulai is not None or item.detik_selesai is not None:
            rentang = f" | segmen_video: {_format_waktu(item.detik_mulai)}-{_format_waktu(item.detik_selesai)}"
        lines.append(
            f"\n[RAG #{idx}] URL: {item.url}\n"
            f"doc_id: {item.doc_id} | judul: {item.judul} | tanggal_terbit: {item.tanggal_terbit or '-'} | "
            f"jenis_sumber: {item.jenis_sumber} | jenis_konten: {item.jenis_konten} | "
            f"skor: {item.skor_kemiripan:.3f} ({item.metode_cari}){rentang}\n"
            f"kutipan_korpus: {_potong_teks(item.kutipan, MAKS_KARAKTER_KUTIPAN_RAG)}"
        )
    return "\n".join(lines)


def _kumpulkan_daftar_url(
    klaim: Klaim,
    hasil_tahap2: HasilTahap2,
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    """Kembalikan peta (url_kredibel_norm -> asli, url_semua_diizinkan_norm -> asli, metadata_url)."""
    kredibel: dict[str, str] = {}
    semua: dict[str, str] = {}
    judul_map: dict[str, str] = {}
    tgl_map: dict[str, str] = {}

    def _norm(u: str) -> str:
        return u.strip().rstrip("/")

    for k in hasil_tahap2.kandidat_bersih:
        u = str(k.url)
        n = _norm(u)
        kredibel.setdefault(n, u)
        semua.setdefault(n, u)
        if k.judul:
            judul_map.setdefault(n, k.judul)
        if k.tanggal_unggah:
            tgl_map.setdefault(n, k.tanggal_unggah.isoformat())

    ditolak_urls = {_norm(str(k.url)) for k in hasil_tahap2.kandidat_ditolak}
    for s in hasil_tahap2.sinyal_sumber:
        n = _norm(s.url)
        semua.setdefault(n, s.url)
        if n not in ditolak_urls:
            kredibel.setdefault(n, s.url)
        if s.judul:
            judul_map.setdefault(n, s.judul)
        if s.tanggal_unggah:
            tgl_map.setdefault(n, s.tanggal_unggah)

    for r in hasil_tahap2.hasil_rag:
        n = _norm(r.url)
        kredibel.setdefault(n, r.url)
        semua.setdefault(n, r.url)
        if r.judul:
            judul_map.setdefault(n, r.judul)
        if r.tanggal_terbit:
            tgl_map.setdefault(n, r.tanggal_terbit)

    for k in hasil_tahap2.kandidat_ditolak:
        u = str(k.url)
        semua.setdefault(_norm(u), u)

    if klaim.media_url:
        u = str(klaim.media_url)
        semua.setdefault(_norm(u), u)

    return kredibel, semua, {"judul": judul_map, "tanggal": tgl_map}


def susun_konteks_verifikasi(klaim: Klaim, hasil_tahap2: HasilTahap2) -> str:
    """Susun prompt teks terstruktur Tahap 4 dari klaim viral dan bukti Tahap 2/3."""
    kredibel, semua, _ = _kumpulkan_daftar_url(klaim, hasil_tahap2)
    daftar_url_baris = [
        f"- {u}" + (" [SUMBER_KREDIBEL]" if k in kredibel else " [KONTEKS_KLAIM/DITOLAK]")
        for k, u in semua.items()
    ]
    header = (
        f"Jalur routing Tahap 2: {hasil_tahap2.jalur}\n"
        f"Alasan routing: {hasil_tahap2.alasan_routing}\n"
        "URL sumber yang tersedia (WAJIB disalin persis):\n"
        + ("\n".join(daftar_url_baris) if daftar_url_baris else "- (tidak ada URL sumber)")
    )
    bagian = [
        header,
        _blok_klaim_dan_sinyal(klaim, hasil_tahap2.sinyal_klaim),
        _blok_sumber_tier1(hasil_tahap2),
        _blok_rag(hasil_tahap2.hasil_rag),
    ]
    return "\n\n".join(bagian)


def _lampiran_visual(sinyal: SinyalKonten) -> list[dict]:
    kandidat_path: list[Path] = []
    if sinyal.jenis_media == "gambar" and sinyal.keyframes_lokal:
        kandidat_path = [Path(p) for p in sinyal.keyframes_lokal[:5]]
    elif sinyal.media_lokal:
        kandidat_path = [Path(sinyal.media_lokal)]

    total_bytes = 0
    terpilih: list[Path] = []
    for path in kandidat_path:
        if not path.is_file() or path.suffix.lower() not in EKSTENSI_VISUAL_VALID:
            continue
        try:
            ukuran = path.stat().st_size
        except OSError:
            continue
        if ukuran <= 0 or total_bytes + ukuran > MAKS_BYTES_VISUAL_KLAIM:
            continue
        total_bytes += ukuran
        terpilih.append(path)

    if not terpilih:
        return []

    label = (
        "Lampiran visual representatif dari konten viral yang sedang diaudit:"
        if len(terpilih) == 1
        else f"Lampiran visual slide 1..{len(terpilih)} dari postingan viral yang sedang diaudit:"
    )
    return [llm.part_teks(label), *(llm.part_file(p) for p in terpilih)]


def susun_parts_verifikasi(
    klaim: Klaim,
    hasil_tahap2: HasilTahap2,
    sertakan_visual: bool = True,
) -> list[dict]:
    """Bangun daftar parts multimodal (teks bukti + opsional frame/gambar klaim) untuk Gemini."""
    parts = [llm.part_teks(susun_konteks_verifikasi(klaim, hasil_tahap2))]
    if sertakan_visual:
        parts.extend(_lampiran_visual(hasil_tahap2.sinyal_klaim))
    return parts


def _url_valid(teks: str | None) -> bool:
    if not teks or not teks.strip():
        return False
    try:
        _URL_ADAPTER.validate_python(teks.strip())
        return True
    except ValidationError:
        return False


def _cari_kecocokan_url(kandidat_url: str | None, peta: dict[str, str]) -> str | None:
    if not kandidat_url:
        return None
    bersih = re.sub(r"[),.;\s]+$", "", kandidat_url.strip())
    norm = bersih.rstrip("/")
    if norm in peta:
        return peta[norm]
    norm_lower = norm.lower()
    for k, asli in peta.items():
        if k.lower() == norm_lower:
            return asli
    return None


def _sumber_kredibel_teratas(hasil_tahap2: HasilTahap2) -> tuple[str | None, str | None, str | None]:
    if hasil_tahap2.kandidat_bersih:
        utama = hasil_tahap2.kandidat_bersih[0]
        tgl = utama.tanggal_unggah.isoformat() if utama.tanggal_unggah else None
        return str(utama.url), utama.judul, tgl
    ditolak = {str(k.url).rstrip("/") for k in hasil_tahap2.kandidat_ditolak}
    for s in hasil_tahap2.sinyal_sumber:
        if s.url.rstrip("/") not in ditolak:
            return s.url, s.judul, s.tanggal_unggah
    if hasil_tahap2.hasil_rag:
        r = hasil_tahap2.hasil_rag[0]
        return r.url, r.judul, r.tanggal_terbit
    return None, None, None


def _bukti_metadata_fallback(hasil_tahap2: HasilTahap2, maksimal: int = 3) -> list[TemuanBukti]:
    bukti: list[TemuanBukti] = []
    for k in hasil_tahap2.kandidat_bersih[:maksimal]:
        tgl = f" diunggah {k.tanggal_unggah:%d %b %Y}" if k.tanggal_unggah else ""
        wm = " dan berwatermark" if k.ada_watermark else ""
        bukti.append(
            TemuanBukti(
                jenis="metadata",
                url=str(k.url),
                cuplikan=k.cuplikan,
                teks_sumber=k.judul or None,
                catatan=f"Kandidat Tier-1 ({k.jenis_sumber}, skor {k.skor or 0:.2f}{tgl}{wm}).",
            )
        )
    if len(bukti) < maksimal:
        for r in hasil_tahap2.hasil_rag[: maksimal - len(bukti)]:
            bukti.append(
                TemuanBukti(
                    jenis="kutipan",
                    url=r.url,
                    cuplikan=r.judul,
                    teks_sumber=_potong_teks(r.kutipan, 400),
                    catatan=f"Rujukan korpus resmi RAG ({r.metode_cari}, skor {r.skor_kemiripan:.2f}).",
                )
            )
    if not bukti:
        for k in hasil_tahap2.kandidat_ditolak[:maksimal]:
            tgl = f" diunggah {k.tanggal_unggah:%d %b %Y}" if k.tanggal_unggah else ""
            wm = " dan berwatermark" if k.ada_watermark else ""
            bukti.append(
                TemuanBukti(
                    jenis="metadata",
                    url=str(k.url),
                    cuplikan=k.cuplikan,
                    teks_sumber=k.judul or None,
                    catatan=f"Kandidat ditolak ({k.jenis_sumber}{tgl}{wm}).",
                )
            )
    return bukti


def _rakit_eskalasi_pra_llm(klaim: Klaim, hasil_tahap2: HasilTahap2) -> HasilVerifikasiSilang:
    status: StatusVerifikasi = hasil_tahap2.status_rekomendasi or (
        "belum_bisa_diverifikasi" if hasil_tahap2.kandidat_ditolak else "tidak_ditemukan"
    )
    sumber_utama_url: str | None = None
    sumber_utama_judul: str | None = None
    sumber_utama_tanggal: str | None = None
    bukti: list[TemuanBukti] = []

    if status == "belum_bisa_diverifikasi" and hasil_tahap2.kandidat_ditolak:
        k0 = hasil_tahap2.kandidat_ditolak[0]
        sumber_utama_url = str(k0.url)
        sumber_utama_judul = k0.judul
        sumber_utama_tanggal = k0.tanggal_unggah.isoformat() if k0.tanggal_unggah else None
        bukti = _bukti_metadata_fallback(hasil_tahap2, maksimal=5)

    return HasilVerifikasiSilang(
        claim_id=klaim.claim_id,
        jalur_tahap2=hasil_tahap2.jalur,
        status=status,
        perlu_eskalasi=True,
        alasan_eskalasi=hasil_tahap2.alasan_routing,
        sumber_tertua_meragukan=(status == "belum_bisa_diverifikasi"),
        keyakinan=0.0,
        sumber_utama_url=sumber_utama_url,
        sumber_utama_judul=sumber_utama_judul,
        sumber_utama_tanggal=sumber_utama_tanggal,
        ringkasan=hasil_tahap2.alasan_routing,
        bukti=bukti,
        metode=list(hasil_tahap2.metode_terpakai),
        sumber_analisis="eskalasi_pra_llm",
    )


def _rakit_fallback_llm(
    klaim: Klaim,
    hasil_tahap2: HasilTahap2,
    alasan_gagal: str,
) -> HasilVerifikasiSilang:
    utama_url, utama_judul, utama_tgl = _sumber_kredibel_teratas(hasil_tahap2)
    alasan_lengkap = (
        f"Audit LLM Tahap 4 tidak dapat dijalankan ({alasan_gagal}); "
        "dieskalasi untuk tinjauan manual petugas."
    )
    return HasilVerifikasiSilang(
        claim_id=klaim.claim_id,
        jalur_tahap2=hasil_tahap2.jalur,
        status="belum_bisa_diverifikasi",
        perlu_eskalasi=True,
        alasan_eskalasi=alasan_lengkap,
        keyakinan=0.0,
        sumber_utama_url=utama_url,
        sumber_utama_judul=utama_judul,
        sumber_utama_tanggal=utama_tgl,
        ringkasan=alasan_lengkap,
        bukti=_bukti_metadata_fallback(hasil_tahap2, maksimal=4),
        metode=list(hasil_tahap2.metode_terpakai),
        sumber_analisis="fallback_error",
        catatan_sistem=alasan_gagal,
    )


_AKTOR_APARAT = re.compile(
    r"\b(tni|tentara|prajurit|militer|aparat|kopassus|kostrad|yonif|kodim|koramil|babinsa|marinir)\b",
    re.IGNORECASE,
)
_KEKERASAN = re.compile(
    r"(tembak|penembakan|bunuh|pembunuhan|tewas|aniaya|penganiayaan|pukul|bantai|pembantaian|siksa|"
    r"penyiksaan|culik|penculikan|perkosa|kekerasan|represif|membabi buta|korban jiwa)",
    re.IGNORECASE,
)
AMBANG_FRAME_KUAT = 0.60
BATAS_KEYAKINAN_TANPA_BUKTI_KERAS = 0.80


def tuduhan_kekerasan_aparat(teks: str | None) -> bool:
    """Klaim menuduh aparat/TNI melakukan kekerasan. Bantahan atas klaim seperti ini rawan konflik kepentingan."""
    teks = teks or ""
    return bool(_AKTOR_APARAT.search(teks) and _KEKERASAN.search(teks))


def _ada_frame_kuat(hasil_tahap2: HasilTahap2) -> bool:
    for k in hasil_tahap2.kandidat_bersih:
        frame = (k.rincian_skor or {}).get("frame")
        if frame is None and k.metode == "frame_match":
            frame = k.kemiripan
        if frame is not None and frame >= AMBANG_FRAME_KUAT:
            return True
    return False


def _ada_sumber_resmi(hasil_tahap2: HasilTahap2) -> bool:
    return bool(hasil_tahap2.hasil_rag) or any(
        k.jenis_sumber == "resmi" for k in hasil_tahap2.kandidat_bersih
    )


def _validasi_output_llm(
    mentah: dict[str, Any],
    klaim: Klaim,
    hasil_tahap2: HasilTahap2,
    ambang_keyakinan: float,
) -> HasilVerifikasiSilang:
    kredibel_map, semua_map, meta_map = _kumpulkan_daftar_url(klaim, hasil_tahap2)
    judul_map = meta_map["judul"]
    tgl_map = meta_map["tanggal"]

    status_awal = str(mentah.get("status") or "belum_bisa_diverifikasi")
    if status_awal not in ("terbukti_diubah", "tidak_ditemukan", "belum_bisa_diverifikasi"):
        status_awal = "belum_bisa_diverifikasi"

    try:
        keyakinan = float(mentah.get("keyakinan", 0.0))
    except (TypeError, ValueError):
        keyakinan = 0.0
    keyakinan = round(min(max(keyakinan, 0.0), 1.0), 4)

    manipulasi = AnalisisManipulasi.model_validate(mentah.get("manipulasi") or {})
    peristiwa_inti_terjadi = bool(mentah.get("peristiwa_inti_terjadi", False))
    bantahan_pihak_tertuduh = bool(mentah.get("bantahan_hanya_pihak_tertuduh", False))
    frame_kuat = _ada_frame_kuat(hasil_tahap2)

    konsisten = bool(mentah.get("konsisten_dengan_sumber", False))
    sumber_meragukan = bool(mentah.get("sumber_tertua_meragukan", False))
    ringkasan = str(mentah.get("ringkasan") or "").strip()
    fakta_utama = str(mentah.get("fakta_utama") or "").strip()
    apa_yang_diubah = str(mentah.get("apa_yang_diubah") or "").strip()
    alasan_eskalasi = str(mentah.get("alasan_eskalasi") or "").strip() or None

    # Normalisasi URL sumber utama agar hanya menunjuk URL nyata dari konteks
    utama_cocok = _cari_kecocokan_url(mentah.get("sumber_utama_url"), kredibel_map)
    if not utama_cocok and status_awal == "terbukti_diubah":
        utama_cocok, _, _ = _sumber_kredibel_teratas(hasil_tahap2)
    if not utama_cocok and status_awal != "terbukti_diubah":
        utama_cocok = _cari_kecocokan_url(mentah.get("sumber_utama_url"), semua_map)

    norm_utama = utama_cocok.rstrip("/") if utama_cocok else None
    utama_judul = judul_map.get(norm_utama) if norm_utama else None
    utama_tgl = tgl_map.get(norm_utama) if norm_utama else None

    # Validasi URL tiap item bukti agar bebas halusinasi
    bukti_valid: list[TemuanBukti] = []
    for raw_b in mentah.get("bukti") or []:
        if not isinstance(raw_b, dict):
            continue
        mentah_url_b = str(raw_b.get("url") or "").strip()
        url_b = _cari_kecocokan_url(mentah_url_b, semua_map)
        if not url_b:
            if mentah_url_b:
                continue
            url_b = utama_cocok or (str(klaim.media_url) if klaim.media_url else None)
        if not url_b or not _url_valid(url_b):
            continue
        jenis_b = raw_b.get("jenis", "kutipan")
        if jenis_b not in ("kutipan", "frame", "transkrip", "metadata"):
            jenis_b = "kutipan"
        bukti_valid.append(
            TemuanBukti(
                jenis=jenis_b,
                url=url_b,
                cuplikan=str(raw_b["cuplikan"]).strip() if raw_b.get("cuplikan") else None,
                teks_viral=str(raw_b["teks_viral"]).strip() if raw_b.get("teks_viral") else None,
                teks_sumber=str(raw_b["teks_sumber"]).strip() if raw_b.get("teks_sumber") else None,
                catatan=str(raw_b["catatan"]).strip() if raw_b.get("catatan") else None,
            )
        )

    # Guardrail eskalasi / worst-case pasca-LLM
    status_final: StatusVerifikasi = status_awal  # type: ignore[assignment]
    catatan_guardrail: list[str] = []

    # Label "dipotong" wajib didukung bukti frame/transkrip, bukan dugaan
    if manipulasi.dipotong and not frame_kuat and not any(
        b.jenis in ("frame", "transkrip") for b in bukti_valid
    ):
        manipulasi.dipotong = False
        manipulasi.detail_dipotong = None
        catatan_guardrail.append("Label 'dipotong' dihapus karena tidak ada bukti frame atau transkrip.")
    perubahan = manipulasi.daftar_perubahan()

    if status_final == "terbukti_diubah":
        if peristiwa_inti_terjadi or bantahan_pihak_tertuduh:
            status_final = "belum_bisa_diverifikasi"
            catatan_guardrail.append(
                "Peristiwa inti dilaporkan sumber independen atau bantahan hanya datang dari pihak yang "
                "dituduh; yang diperdebatkan adalah detailnya, jadi keputusan diserahkan ke petugas."
            )
        elif tuduhan_kekerasan_aparat(klaim.teks_klaim) and not (
            frame_kuat and (manipulasi.tanggal_berbeda or manipulasi.konteks_berbeda)
        ):
            status_final = "belum_bisa_diverifikasi"
            catatan_guardrail.append(
                "Klaim menuduh kekerasan oleh aparat. Netra tidak menyatakan klaim seperti ini keliru "
                "tanpa bukti visual bahwa rekamannya berasal dari peristiwa lain; perlu konfirmasi "
                "independen oleh petugas."
            )
        elif sumber_meragukan:
            status_final = "belum_bisa_diverifikasi"
            catatan_guardrail.append("Sumber acuan tertua ikut meragukan.")
        elif konsisten:
            status_final = "belum_bisa_diverifikasi"
            catatan_guardrail.append("Klaim dinyatakan selaras dengan sumber sehingga memerlukan validasi petugas.")
        elif not kredibel_map or not utama_cocok:
            status_final = "belum_bisa_diverifikasi"
            catatan_guardrail.append("Tidak ada URL sumber kredibel tervalidasi sebagai pembanding utama.")
        elif keyakinan < ambang_keyakinan:
            status_final = "belum_bisa_diverifikasi"
            catatan_guardrail.append(
                f"Skor keyakinan ({keyakinan:.2f}) di bawah ambang batas ({ambang_keyakinan:.2f})."
            )
        elif not perubahan:
            status_final = "belum_bisa_diverifikasi"
            catatan_guardrail.append("Tidak ada jenis manipulasi spesifik yang teridentifikasi.")

    if status_final == "terbukti_diubah" and not frame_kuat and not _ada_sumber_resmi(hasil_tahap2):
        if keyakinan > BATAS_KEYAKINAN_TANPA_BUKTI_KERAS:
            keyakinan = BATAS_KEYAKINAN_TANPA_BUKTI_KERAS
            catatan_guardrail.append(
                "Keyakinan dibatasi karena bukti hanya dari media/akun, tanpa sumber resmi atau kecocokan frame."
            )
    if status_awal == "terbukti_diubah" and status_final != "terbukti_diubah":
        keyakinan = min(keyakinan, 0.5)

    if status_final in ("tidak_ditemukan", "belum_bisa_diverifikasi"):
        perlu_eskalasi = True
        if not alasan_eskalasi:
            alasan_eskalasi = " ".join(catatan_guardrail) or ringkasan or "Perlu tinjauan manual petugas."
        elif catatan_guardrail:
            alasan_eskalasi = f"{' '.join(catatan_guardrail)} {alasan_eskalasi}"
    else:
        perlu_eskalasi = False
        alasan_eskalasi = None
        if not bukti_valid:
            bukti_valid = _bukti_metadata_fallback(hasil_tahap2, maksimal=2)

    if not ringkasan:
        ringkasan = alasan_eskalasi or fakta_utama or "Analisis perbandingan silang selesai."

    return HasilVerifikasiSilang(
        claim_id=klaim.claim_id,
        jalur_tahap2=hasil_tahap2.jalur,
        status=status_final,
        perlu_eskalasi=perlu_eskalasi,
        alasan_eskalasi=alasan_eskalasi,
        konsisten_dengan_sumber=konsisten,
        sumber_tertua_meragukan=sumber_meragukan,
        keyakinan=keyakinan,
        sumber_utama_url=utama_cocok,
        sumber_utama_judul=utama_judul,
        sumber_utama_tanggal=utama_tgl,
        perubahan=perubahan,
        manipulasi=manipulasi,
        ringkasan=ringkasan,
        fakta_utama=fakta_utama,
        apa_yang_diubah=apa_yang_diubah,
        bukti=bukti_valid,
        metode=list(hasil_tahap2.metode_terpakai),
        sumber_analisis="gemini_multimodal",
        catatan_sistem=" ".join(catatan_guardrail) or None,
    )


def konversi_ke_bukti_schema(temuan: list[TemuanBukti]) -> list[Bukti]:
    """Konversi daftar TemuanBukti menjadi model `schemas.Bukti` yang lolos validasi HttpUrl."""
    hasil: list[Bukti] = []
    for item in temuan:
        if not _url_valid(item.url):
            continue
        hasil.append(
            Bukti(
                jenis=item.jenis,
                url=_URL_ADAPTER.validate_python(item.url.strip()),
                cuplikan=item.cuplikan,
                teks_viral=item.teks_viral,
                teks_sumber=item.teks_sumber,
                catatan=item.catatan,
            )
        )
    return hasil


def verifikasi_silang(
    klaim: Klaim,
    hasil_tahap2: HasilTahap2,
    *,
    sertakan_visual: bool = True,
    ambang_keyakinan: float = AMBANG_KEYAKINAN_PUTUSAN,
    model: str | None = None,
    thinking: str | None = None,
    media_resolution: str | None = "MEDIA_RESOLUTION_LOW",
    suhu: float = 0.1,
    timeout: float | None = None,
    fallback_aman: bool = True,
) -> HasilVerifikasiSilang:
    """Jalankan Tahap 4 (Cross-Verification) atas hasil Tahap 2/3 menggunakan Gemini."""
    if not hasil_tahap2.siap_tahap4:
        return _rakit_eskalasi_pra_llm(klaim, hasil_tahap2)

    level_thinking = thinking if thinking is not None else config.GEMINI_THINKING_VERIFIKASI
    parts = susun_parts_verifikasi(klaim, hasil_tahap2, sertakan_visual=sertakan_visual)
    try:
        mentah = llm.tanya_multimodal_json(
            parts,
            suhu=suhu,
            skema=SCHEMA_VERIFIKASI_SILANG,
            timeout=timeout,
            model=model,
            thinking=level_thinking,
            media_resolution=media_resolution,
            instruksi_sistem=SYSTEM_PROMPT_VERIFIKASI,
        )
    except llm.LLMError as e:
        log.warning("Cross-verification Gemini gagal (%s): %s", klaim.claim_id, e)
        if not fallback_aman:
            raise VerifikasiError(f"Cross-verification gagal: {e}") from e
        return _rakit_fallback_llm(klaim, hasil_tahap2, str(e))

    if not isinstance(mentah, dict):
        pesan = "Respons LLM tidak berbentuk objek JSON"
        log.warning("Cross-verification format invalid (%s): %s", klaim.claim_id, type(mentah).__name__)
        if not fallback_aman:
            raise VerifikasiError(pesan)
        return _rakit_fallback_llm(klaim, hasil_tahap2, pesan)

    try:
        return _validasi_output_llm(mentah, klaim, hasil_tahap2, ambang_keyakinan=ambang_keyakinan)
    except ValidationError as e:
        pesan = f"Struktur output LLM tidak valid ({len(e.errors())} kesalahan skema)"
        log.warning("Cross-verification validasi gagal (%s): %s", klaim.claim_id, e)
        if not fallback_aman:
            raise VerifikasiError(pesan) from e
        return _rakit_fallback_llm(klaim, hasil_tahap2, pesan)
