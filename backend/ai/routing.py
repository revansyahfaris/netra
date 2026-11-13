"""Tahap 2: Jembatan data Tier-1 (modul pencari Faris), sinyal Tahap 1, dan routing ke Tahap 3/4.

Mengimplementasikan logika percabangan sesuai AI Blueprint:
- Tier-1 memiliki kandidat bersih & memadai -> ekstrak sinyal sumber acuan -> Tahap 4
  (diperkaya Tahap 3 RAG jika perlu rujukan resmi tambahan).
- Tier-1 kosong, hanya kandidat pribadi/berwatermark, atau skor di bawah ambang ->
  teruskan ke Tahap 3 (RAG Korpus Resmi).
- Jika Tier-1 & Tier-2 RAG sama-sama tidak memberi sumber bersih yang memadai ->
  siapkan keputusan eskalasi (`belum_bisa_diverifikasi` / `tidak_ditemukan`).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

import config
from schemas import (
    HasilPencarian,
    JenisMedia,
    KandidatSumber,
    Klaim,
    MetodeVerifikasi,
    StatusVerifikasi,
)

from . import ekstraksi, ocr, rag, sumber
from .ocr import HasilOCR
from .rag import HasilCariKorpus
from .sumber import SinyalSumberAcuan, adalah_url_placeholder, transkrip_audio_aman
from .stt import SegmenTranskrip

log = logging.getLogger("netra.ai.routing")

AMBANG_KEMIRIPAN_MEMADAI = 0.50
AMBANG_SKOR_MEMADAI = 0.45
AMBANG_FRAME_MATCH_KUAT = 0.75
AMBANG_RAG_VECTOR_RELEVAN = 0.55

JalurVerifikasi = Literal[
    "tier1_ke_tahap4",
    "tier1_dan_rag_ke_tahap4",
    "tier2_rag_ke_tahap4",
    "eskalasi_worst_case",
    "eskalasi_tidak_ditemukan",
]


class SinyalKonten(BaseModel):
    """Payload terpadu hasil Tahap 1 untuk satu klaim viral."""

    claim_id: str
    teks_klaim: str
    jenis_media: JenisMedia
    media_url: str | None = None
    audio_tersedia: bool = False
    stt_teks: str = ""
    stt_segmen: list[SegmenTranskrip] = Field(default_factory=list)
    sumber_stt: str = "kosong"
    ocr: HasilOCR = Field(default_factory=HasilOCR)
    media_lokal: str | None = None
    catatan: str | None = None

    def query_rag(self, maks_karakter: int = 1500) -> str:
        """Susun teks query gabungan (klaim + transkrip STT + OCR unik) untuk retriever Tahap 3."""
        bagian: list[str] = []
        terlihat: set[str] = set()
        kandidat_teks = [self.teks_klaim, self.stt_teks, *self.ocr.teks_unik]
        for mentah in kandidat_teks:
            bersih = " ".join(str(mentah).split())
            kunci = bersih.lower()
            if bersih and kunci not in terlihat:
                terlihat.add(kunci)
                bagian.append(bersih)
        gabung = "\n".join(bagian)
        if len(gabung) > maks_karakter:
            return gabung[:maks_karakter].rstrip()
        return gabung


class KeputusanRouting(BaseModel):
    """Hasil evaluasi kesiapan kandidat Tier-1 sebelum ekstraksi penuh."""

    kandidat_bersih: list[KandidatSumber] = Field(default_factory=list)
    kandidat_memadai: list[KandidatSumber] = Field(default_factory=list)
    kandidat_ditolak: list[KandidatSumber] = Field(default_factory=list)
    tier1_memadai: bool = False
    perlu_rag: bool = True
    alasan: str


class HasilTahap2(BaseModel):
    """Keluaran Tahap 2 yang siap dikonsumsi Tahap 4 (atau langsung dieskalasi di Tahap 5)."""

    claim_id: str
    jalur: JalurVerifikasi
    siap_tahap4: bool
    status_rekomendasi: StatusVerifikasi | None = None
    perlu_eskalasi: bool = False
    alasan_routing: str
    sinyal_klaim: SinyalKonten
    kandidat_bersih: list[KandidatSumber] = Field(default_factory=list)
    kandidat_ditolak: list[KandidatSumber] = Field(default_factory=list)
    sinyal_sumber: list[SinyalSumberAcuan] = Field(default_factory=list)
    hasil_rag: list[HasilCariKorpus] = Field(default_factory=list)
    metode_terpakai: list[MetodeVerifikasi] = Field(default_factory=list)


def ekstrak_sinyal_klaim(
    klaim: Klaim,
    ambil_konten_eksternal: bool = True,
) -> SinyalKonten:
    """Jalankan Tahap 1 pada klaim viral (teks, gambar, atau video)."""
    media_str = str(klaim.media_url) if klaim.media_url else None

    if klaim.jenis_media == "teks" or not media_str:
        return SinyalKonten(
            claim_id=klaim.claim_id,
            teks_klaim=klaim.teks_klaim,
            jenis_media=klaim.jenis_media,
            media_url=media_str,
        )

    if not ambil_konten_eksternal or adalah_url_placeholder(media_str):
        return SinyalKonten(
            claim_id=klaim.claim_id,
            teks_klaim=klaim.teks_klaim,
            jenis_media=klaim.jenis_media,
            media_url=media_str,
            catatan="Mode demo/placeholder: ekstraksi media klaim dilewati.",
        )

    if klaim.jenis_media == "gambar":
        hasil_ocr = ocr.ocr_gambar(media_str, fallback_aman=True)
        path_lokal: Path | None = None
        if media_str.startswith(("http://", "https://")):
            folder_cache = config.WORK_DIR / f"ai_img_{hashlib.md5(media_str.encode()).hexdigest()[:12]}"
            kandidat_file = sorted(folder_cache.glob("gambar.*")) if folder_cache.exists() else []
            path_lokal = kandidat_file[0] if kandidat_file else None
        else:
            kandidat_path = Path(media_str)
            if kandidat_path.exists():
                path_lokal = kandidat_path

        return SinyalKonten(
            claim_id=klaim.claim_id,
            teks_klaim=klaim.teks_klaim,
            jenis_media=klaim.jenis_media,
            media_url=media_str,
            ocr=hasil_ocr,
            media_lokal=str(path_lokal) if path_lokal else None,
            catatan=hasil_ocr.catatan if hasil_ocr.sumber_ocr == "gagal" else None,
        )

    # klaim.jenis_media == "video"
    try:
        hasil_media = ekstraksi.ekstrak_sinyal_media(media_str)
    except ekstraksi.EkstraksiError as e:
        log.warning("Ekstraksi video klaim gagal (%s): %s", klaim.claim_id, e)
        return SinyalKonten(
            claim_id=klaim.claim_id,
            teks_klaim=klaim.teks_klaim,
            jenis_media=klaim.jenis_media,
            media_url=media_str,
            catatan=f"Gagal mengekstrak video klaim ({e}); lanjut memakai teks klaim.",
        )

    hasil_stt = transkrip_audio_aman(hasil_media.audio_path)
    hasil_ocr = ocr.ocr_keyframes(hasil_media.keyframes, fallback_aman=True)
    keyframe_wakilan = (
        str(hasil_media.keyframes[len(hasil_media.keyframes) // 2][1])
        if hasil_media.keyframes
        else None
    )
    catatan_klaim = (
        "STT (faster-whisper) sedang tidak aktif; verifikasi dilanjutkan memakai OCR dan teks klaim."
        if hasil_stt.sumber_stt == "tidak_aktif"
        else None
    )

    return SinyalKonten(
        claim_id=klaim.claim_id,
        teks_klaim=klaim.teks_klaim,
        jenis_media=klaim.jenis_media,
        media_url=media_str,
        audio_tersedia=hasil_media.audio_path is not None,
        stt_teks=hasil_stt.teks,
        stt_segmen=hasil_stt.segmen,
        sumber_stt=hasil_stt.sumber_stt,
        ocr=hasil_ocr,
        media_lokal=keyframe_wakilan,
        catatan=catatan_klaim,
    )


def _kandidat_memadai(
    k: KandidatSumber,
    ambang_kemiripan: float = AMBANG_KEMIRIPAN_MEMADAI,
    ambang_skor: float = AMBANG_SKOR_MEMADAI,
) -> bool:
    if k.kemiripan < ambang_kemiripan:
        return False
    if k.skor is not None and k.skor < ambang_skor:
        return False
    return True


def _perlu_pengayaan_rag(klaim: Klaim, kandidat_memadai: list[KandidatSumber]) -> bool:
    if not kandidat_memadai:
        return True
    utama = kandidat_memadai[0]
    if klaim.jenis_media != "video":
        return True
    if utama.metode != "frame_match" or utama.kemiripan < AMBANG_FRAME_MATCH_KUAT:
        return True
    if utama.jenis_sumber == "resmi":
        return True
    if any(tanda in klaim.teks_klaim for tanda in ('"', "'", "“", "”")):
        return True
    return False


def evaluasi_kandidat(
    klaim: Klaim,
    pencarian: HasilPencarian,
    ambang_kemiripan: float = AMBANG_KEMIRIPAN_MEMADAI,
    ambang_skor: float = AMBANG_SKOR_MEMADAI,
) -> KeputusanRouting:
    """Evaluasi kandidat Tier-1 untuk menentukan apakah layak ke Tahap 4 atau turun ke Tahap 3 RAG."""
    kandidat = pencarian.kandidat
    if not kandidat:
        return KeputusanRouting(
            tier1_memadai=False,
            perlu_rag=True,
            alasan="Tier-1 Search tidak menemukan kandidat sumber; lanjut ke Tahap 3 (RAG korpus resmi).",
        )

    bersih = [k for k in kandidat if k.jenis_sumber != "pribadi" and not k.ada_watermark]
    ditolak = [k for k in kandidat if k.jenis_sumber == "pribadi" or bool(k.ada_watermark)]

    if not bersih:
        return KeputusanRouting(
            kandidat_bersih=[],
            kandidat_memadai=[],
            kandidat_ditolak=ditolak,
            tier1_memadai=False,
            perlu_rag=True,
            alasan=(
                "Semua kandidat Tier-1 berasal dari akun pribadi dan/atau berwatermark; "
                "periksa Tahap 3 (RAG korpus resmi) sebelum eskalasi worst-case."
            ),
        )

    memadai = [
        k for k in bersih if _kandidat_memadai(k, ambang_kemiripan=ambang_kemiripan, ambang_skor=ambang_skor)
    ]
    if not memadai:
        return KeputusanRouting(
            kandidat_bersih=bersih,
            kandidat_memadai=[],
            kandidat_ditolak=ditolak,
            tier1_memadai=False,
            perlu_rag=True,
            alasan=(
                "Kandidat bersih Tier-1 memiliki kemiripan/skor di bawah ambang memadai; "
                "teruskan ke Tahap 3 (RAG korpus resmi)."
            ),
        )

    pengayaan = _perlu_pengayaan_rag(klaim, memadai)
    alasan = (
        "Kandidat bersih Tier-1 memadai; ekstrak sinyal sumber acuan dan perkaya dengan Tahap 3 RAG."
        if pengayaan
        else "Kandidat bersih Tier-1 kuat (frame match / kemiripan tinggi); arahkan langsung ke Tahap 4."
    )
    return KeputusanRouting(
        kandidat_bersih=bersih,
        kandidat_memadai=memadai,
        kandidat_ditolak=ditolak,
        tier1_memadai=True,
        perlu_rag=pengayaan,
        alasan=alasan,
    )


def _cari_korpus_relevan(
    sinyal: SinyalKonten,
    batas: int = 5,
    ambang_vector: float = AMBANG_RAG_VECTOR_RELEVAN,
) -> list[HasilCariKorpus]:
    query = sinyal.query_rag()
    media_path = Path(sinyal.media_lokal) if sinyal.media_lokal else None
    if media_path is not None and not media_path.exists():
        media_path = None
    if not query and media_path is None:
        return []

    mentah = rag.cari_korpus(
        query_teks=query,
        media_path=media_path,
        batas=batas,
        ambang_skor=ambang_vector,
        fallback_aman=True,
    )
    return [
        item
        for item in mentah
        if (item.metode_cari == "keyword" and item.skor_kemiripan > 0.0)
        or (item.metode_cari == "vector" and item.skor_kemiripan >= ambang_vector)
    ]


def _kumpulkan_metode(
    klaim: Klaim,
    sinyal_klaim: SinyalKonten,
    kandidat_dipakai: list[KandidatSumber],
    sinyal_sumber: list[SinyalSumberAcuan],
    hasil_rag: list[HasilCariKorpus],
    jalur: JalurVerifikasi,
) -> list[MetodeVerifikasi]:
    metode: list[MetodeVerifikasi] = []

    def _tambah(m: MetodeVerifikasi) -> None:
        if m not in metode:
            metode.append(m)

    if any(k.metode == "frame_match" for k in kandidat_dipakai) or (
        klaim.jenis_media == "video" and bool(kandidat_dipakai)
    ):
        _tambah("frame_match")
    if hasil_rag or jalur in ("tier1_dan_rag_ke_tahap4", "tier2_rag_ke_tahap4"):
        _tambah("rag")
    stt_tidak_aktif = ("kosong", "tidak_aktif", "gagal")
    if sinyal_klaim.sumber_stt not in stt_tidak_aktif or any(
        s.sumber_stt not in stt_tidak_aktif for s in sinyal_sumber
    ):
        _tambah("asr")
    if sinyal_klaim.ocr.sumber_ocr == "gemini" or any(
        s.ocr.sumber_ocr == "gemini" for s in sinyal_sumber
    ):
        _tambah("ocr")
    if not metode:
        _tambah("manual")
    return metode


def jalankan_tahap2(
    klaim: Klaim,
    pencarian: HasilPencarian,
    maks_kandidat: int = 2,
    batas_rag: int = 5,
    ambil_konten_eksternal: bool = True,
    ambang_kemiripan: float = AMBANG_KEMIRIPAN_MEMADAI,
    ambang_skor: float = AMBANG_SKOR_MEMADAI,
    ambang_rag_vector: float = AMBANG_RAG_VECTOR_RELEVAN,
) -> HasilTahap2:
    """Orkestrasi Tahap 2: sinyal klaim -> evaluasi Tier-1 -> ekstraksi sumber / fallback RAG -> routing."""
    sinyal_klaim = ekstrak_sinyal_klaim(klaim, ambil_konten_eksternal=ambil_konten_eksternal)
    keputusan = evaluasi_kandidat(
        klaim,
        pencarian,
        ambang_kemiripan=ambang_kemiripan,
        ambang_skor=ambang_skor,
    )

    if keputusan.tier1_memadai:
        target_kandidat = keputusan.kandidat_memadai[: max(1, maks_kandidat)]
        sinyal_sumber = [
            sumber.ekstrak_sinyal_kandidat(k, ambil_konten_eksternal=ambil_konten_eksternal)
            for k in target_kandidat
        ]

        semua_gagal_penuh = all(not s.ekstraksi_penuh_berhasil for s in sinyal_sumber)
        hasil_rag: list[HasilCariKorpus] = []
        if keputusan.perlu_rag or semua_gagal_penuh:
            hasil_rag = _cari_korpus_relevan(
                sinyal_klaim,
                batas=batas_rag,
                ambang_vector=ambang_rag_vector,
            )

        jalur: JalurVerifikasi = "tier1_dan_rag_ke_tahap4" if hasil_rag else "tier1_ke_tahap4"
        alasan = keputusan.alasan
        if semua_gagal_penuh and hasil_rag and not keputusan.perlu_rag:
            alasan += " Konten penuh Tier-1 tidak dapat diambil; diperkaya konteks Tahap 3 RAG."

        return HasilTahap2(
            claim_id=klaim.claim_id,
            jalur=jalur,
            siap_tahap4=True,
            status_rekomendasi=None,
            perlu_eskalasi=False,
            alasan_routing=alasan,
            sinyal_klaim=sinyal_klaim,
            kandidat_bersih=keputusan.kandidat_bersih,
            kandidat_ditolak=keputusan.kandidat_ditolak,
            sinyal_sumber=sinyal_sumber,
            hasil_rag=hasil_rag,
            metode_terpakai=_kumpulkan_metode(
                klaim,
                sinyal_klaim,
                target_kandidat,
                sinyal_sumber,
                hasil_rag,
                jalur,
            ),
        )

    # Jalur 2: Tier-1 tidak menemukan kandidat bersih yang meyakinkan -> Tahap 3 RAG
    hasil_rag = _cari_korpus_relevan(
        sinyal_klaim,
        batas=batas_rag,
        ambang_vector=ambang_rag_vector,
    )
    if hasil_rag:
        return HasilTahap2(
            claim_id=klaim.claim_id,
            jalur="tier2_rag_ke_tahap4",
            siap_tahap4=True,
            status_rekomendasi=None,
            perlu_eskalasi=False,
            alasan_routing=f"{keputusan.alasan} Ditemukan {len(hasil_rag)} rujukan resmi di Tahap 3 RAG.",
            sinyal_klaim=sinyal_klaim,
            kandidat_bersih=keputusan.kandidat_bersih,
            kandidat_ditolak=keputusan.kandidat_ditolak,
            sinyal_sumber=[],
            hasil_rag=hasil_rag,
            metode_terpakai=_kumpulkan_metode(
                klaim,
                sinyal_klaim,
                pencarian.kandidat,
                [],
                hasil_rag,
                "tier2_rag_ke_tahap4",
            ),
        )

    # Worst-case / tidak ditemukan: baik Tier-1 maupun Tier-2 RAG tidak menyediakan sumber bersih
    ada_kandidat_mentah = bool(pencarian.kandidat)
    jalur_eskalasi: JalurVerifikasi = (
        "eskalasi_worst_case" if ada_kandidat_mentah else "eskalasi_tidak_ditemukan"
    )
    status_eskalasi: StatusVerifikasi = (
        "belum_bisa_diverifikasi" if ada_kandidat_mentah else "tidak_ditemukan"
    )
    alasan_eskalasi = (
        f"{keputusan.alasan} Pencarian Tahap 3 RAG juga tidak menemukan sumber resmi yang relevan."
    )

    return HasilTahap2(
        claim_id=klaim.claim_id,
        jalur=jalur_eskalasi,
        siap_tahap4=False,
        status_rekomendasi=status_eskalasi,
        perlu_eskalasi=True,
        alasan_routing=alasan_eskalasi,
        sinyal_klaim=sinyal_klaim,
        kandidat_bersih=keputusan.kandidat_bersih,
        kandidat_ditolak=keputusan.kandidat_ditolak,
        sinyal_sumber=[],
        hasil_rag=[],
        metode_terpakai=_kumpulkan_metode(
            klaim,
            sinyal_klaim,
            pencarian.kandidat,
            [],
            [],
            jalur_eskalasi,
        ),
    )
