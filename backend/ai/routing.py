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
from typing import Any, Literal

from pydantic import BaseModel, Field

import config
import url_kanonis
from schemas import (
    HasilPencarian,
    JenisMedia,
    KandidatSumber,
    Klaim,
    MetodeVerifikasi,
    StatusVerifikasi,
)

from . import ekstraksi, embedding, ocr, rag, sumber
from .ocr import HasilOCR
from .rag import CakupanKorpus, HasilCariKorpus
from .sumber import SinyalSumberAcuan, adalah_url_placeholder, transkrip_audio_aman
from .stt import SegmenTranskrip

log = logging.getLogger("netra.ai.routing")

AMBANG_KEMIRIPAN_MEMADAI = 0.50
AMBANG_SKOR_MEMADAI = 0.45
AMBANG_FRAME_MATCH_KUAT = 0.75
AMBANG_TOPIK_TIER2 = 0.45
AMBANG_RAG_VECTOR_RELEVAN = 0.55
MAKS_KEYFRAME_RAG = 3
MAKS_KANDIDAT_JIT = 5

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
    keyframes_lokal: list[str] = Field(default_factory=list)
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
    """Hasil evaluasi kesiapan kandidat Tier-1 dan kelayakan Tier-2 sebelum ekstraksi penuh."""

    kandidat_bersih: list[KandidatSumber] = Field(default_factory=list)
    kandidat_memadai: list[KandidatSumber] = Field(default_factory=list)
    kandidat_ditolak: list[KandidatSumber] = Field(default_factory=list)
    kandidat_tier2: list[KandidatSumber] = Field(default_factory=list)
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
    jit_diindeks: list[str] = Field(default_factory=list)
    jit_cache_hit: list[str] = Field(default_factory=list)
    indikasi_buzzer: bool = False


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
            keyframes_lokal=[str(path_lokal)] if path_lokal else [],
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
    keyframes_lokal = sumber.pilih_keyframes_wakilan(
        hasil_media.keyframes, maks=MAKS_KEYFRAME_RAG
    )
    keyframe_wakilan = (
        keyframes_lokal[len(keyframes_lokal) // 2]
        if keyframes_lokal
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
        keyframes_lokal=keyframes_lokal,
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


def _layak_tier2_topik(
    k: KandidatSumber,
    ambang_skor: float = AMBANG_SKOR_MEMADAI,
) -> bool:
    """Sumbu B: kandidat resmi/media tanpa watermark yang relevan topiknya untuk JIT Tier-2."""
    if k.jenis_sumber not in ("resmi", "media") or k.ada_watermark:
        return False
    skor_efektif = k.skor if k.skor is not None else k.kemiripan
    return k.kemiripan >= AMBANG_TOPIK_TIER2 or skor_efektif >= ambang_skor


def _kandidat_tier1_valid(
    klaim: Klaim,
    k: KandidatSumber,
    ambang_kemiripan: float = AMBANG_KEMIRIPAN_MEMADAI,
    ambang_skor: float = AMBANG_SKOR_MEMADAI,
) -> bool:
    """Sumbu A: kandidat bersih layak Tier-1 (video wajib punya frame_match memadai)."""
    if not _kandidat_memadai(k, ambang_kemiripan=ambang_kemiripan, ambang_skor=ambang_skor):
        return False
    if klaim.jenis_media == "video":
        return k.metode == "frame_match"
    return True


def evaluasi_kandidat(
    klaim: Klaim,
    pencarian: HasilPencarian,
    ambang_kemiripan: float = AMBANG_KEMIRIPAN_MEMADAI,
    ambang_skor: float = AMBANG_SKOR_MEMADAI,
) -> KeputusanRouting:
    """Evaluasi 2 sumbu: kecocokan footage (Tier-1) vs relevansi topik kredibel (Tier-2 JIT)."""
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
            kandidat_tier2=[],
            tier1_memadai=False,
            perlu_rag=True,
            alasan=(
                "Semua kandidat Tier-1 berasal dari akun pribadi dan/atau berwatermark; "
                "periksa Tahap 3 (RAG korpus resmi) sebelum eskalasi worst-case."
            ),
        )

    memadai = [
        k
        for k in bersih
        if _kandidat_tier1_valid(
            klaim, k, ambang_kemiripan=ambang_kemiripan, ambang_skor=ambang_skor
        )
    ]
    kandidat_tier2 = [
        k for k in bersih if k not in memadai and _layak_tier2_topik(k, ambang_skor=ambang_skor)
    ]

    if not memadai:
        alasan_turun = (
            "Kecocokan footage Tier-1 rendah/tidak ada; teruskan kandidat topik kredibel ke Tier-2 JIT & Tahap 3 RAG."
            if kandidat_tier2
            else (
                "Kandidat bersih Tier-1 memiliki kemiripan/skor di bawah ambang memadai; "
                "teruskan ke Tahap 3 (RAG korpus resmi)."
            )
        )
        return KeputusanRouting(
            kandidat_bersih=bersih,
            kandidat_memadai=[],
            kandidat_ditolak=ditolak,
            kandidat_tier2=kandidat_tier2,
            tier1_memadai=False,
            perlu_rag=True,
            alasan=alasan_turun,
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
        kandidat_tier2=kandidat_tier2 if pengayaan else [],
        tier1_memadai=True,
        perlu_rag=pengayaan,
        alasan=alasan,
    )


def _cari_korpus_relevan(
    sinyal: SinyalKonten,
    batas: int = 5,
    ambang_vector: float = AMBANG_RAG_VECTOR_RELEVAN,
    cakupan: CakupanKorpus | list[CakupanKorpus] | None = None,
) -> list[HasilCariKorpus]:
    query = sinyal.query_rag()
    daftar_media = [
        Path(p) for p in sinyal.keyframes_lokal if Path(p).exists()
    ][:MAKS_KEYFRAME_RAG]
    if not daftar_media and sinyal.media_lokal:
        kandidat_lokal = Path(sinyal.media_lokal)
        if kandidat_lokal.exists():
            daftar_media = [kandidat_lokal]
    media_utama = daftar_media[0] if daftar_media else None
    if not query and not daftar_media:
        return []

    mentah = rag.cari_korpus(
        query_teks=query,
        media_path=media_utama,
        media_paths=daftar_media or None,
        batas=batas,
        ambang_skor=ambang_vector,
        fallback_aman=True,
        cakupan=cakupan,
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


def _deteksi_indikasi_buzzer(
    pencarian: HasilPencarian,
    korroborasi: dict[str, Any] | None = None,
) -> bool:
    if korroborasi is not None:
        if "indikasi_buzzer" in korroborasi:
            return bool(korroborasi["indikasi_buzzer"])
        klaster_vals = [v for v in korroborasi.values() if isinstance(v, dict)]
        if klaster_vals:
            kredibel_klaster = sum(
                int(v.get("jumlah_resmi", 0)) + int(v.get("jumlah_media", 0))
                for v in klaster_vals
            )
            return kredibel_klaster == 0 and any(
                bool(v.get("indikasi_buzzer")) for v in klaster_vals
            )
    if any(k.jenis_sumber in ("resmi", "media") for k in pencarian.kandidat):
        return False
    penerbit_pribadi = {
        url_kanonis.penerbit_dari_url(str(k.url), k.uploader)
        for k in pencarian.kandidat
        if k.jenis_sumber == "pribadi"
    }
    return len(penerbit_pribadi) >= 3


def _indeks_jit_tier2(
    kandidat_tier2: list[KandidatSumber],
    *,
    ambil_konten_eksternal: bool,
    maks_jit: int = MAKS_KANDIDAT_JIT,
) -> tuple[list[str], list[str]]:
    """Indeks kandidat Tier-2 relevan (beda angle / berita) ke pgvector cakupan 'temuan'."""
    diindeks: list[str] = []
    cache_hit: list[str] = []

    for k in kandidat_tier2[: max(1, maks_jit)]:
        url_str = str(k.url)
        if adalah_url_placeholder(url_str):
            continue
        doc_id = url_kanonis.doc_id_dari_url(url_str)
        try:
            if rag.dokumen_masih_aktif(doc_id):
                cache_hit.append(url_str)
                continue
        except Exception as e:
            log.debug("Pengecekan cache JIT dilewati (%s): %s", url_str, e)

        try:
            sig = sumber.ekstrak_sinyal_kandidat(
                k, ambil_konten_eksternal=ambil_konten_eksternal
            )
            if not sig.teks_isi.strip() and not sig.keyframes_lokal:
                continue
            jenis_media: JenisMedia = (
                "video"
                if sig.jenis_konten == "video"
                else ("gambar" if sig.jenis_konten == "gambar" else "teks")
            )
            jenis_sumber: Literal["resmi", "media", "pribadi"] = (
                "resmi" if k.jenis_sumber == "resmi" else "media"
            )
            dok = rag.DokumenKorpus(
                doc_id=doc_id,
                judul=sig.judul or k.judul or url_str,
                url=url_str,
                jenis_sumber=jenis_sumber,
                jenis_media=jenis_media,
                tanggal_terbit=sig.tanggal_unggah,
                cakupan="temuan",
            )
            if sig.keyframes_lokal:
                selesai = (
                    sig.jendela_mulai_detik + sig.jendela_durasi_detik
                    if sig.jendela_mulai_detik is not None and sig.jendela_durasi_detik is not None
                    else None
                )
                rag.indeks_media_korpus(
                    dok,
                    media_paths=[Path(p) for p in sig.keyframes_lokal[:MAKS_KEYFRAME_RAG]],
                    teks_pendamping=sig.teks_isi,
                    detik_mulai=sig.jendela_mulai_detik,
                    detik_selesai=selesai,
                )
            else:
                rag.indeks_dokumen_teks(dok, sig.teks_isi)
            diindeks.append(url_str)
        except (rag.RAGError, embedding.EmbeddingError, Exception) as e:
            log.warning("Indeks JIT Tier-2 dilewati (%s): %s", url_str, e)
            continue

    return diindeks, cache_hit


def jalankan_tahap2(
    klaim: Klaim,
    pencarian: HasilPencarian,
    maks_kandidat: int = 2,
    batas_rag: int = 5,
    ambil_konten_eksternal: bool = True,
    ambang_kemiripan: float = AMBANG_KEMIRIPAN_MEMADAI,
    ambang_skor: float = AMBANG_SKOR_MEMADAI,
    ambang_rag_vector: float = AMBANG_RAG_VECTOR_RELEVAN,
    sinyal_klaim_awal: SinyalKonten | None = None,
    jit_tier2: bool | None = None,
    maks_jit: int = MAKS_KANDIDAT_JIT,
    korroborasi: dict[str, Any] | None = None,
) -> HasilTahap2:
    """Orkestrasi Tahap 2: sinyal klaim -> evaluasi 2 sumbu -> Tier-1 / JIT Tier-2 / RAG -> routing."""
    sinyal_klaim = (
        sinyal_klaim_awal
        if sinyal_klaim_awal is not None
        else ekstrak_sinyal_klaim(klaim, ambil_konten_eksternal=ambil_konten_eksternal)
    )
    keputusan = evaluasi_kandidat(
        klaim,
        pencarian,
        ambang_kemiripan=ambang_kemiripan,
        ambang_skor=ambang_skor,
    )
    jit_aktif = config.JIT_TIER2 if jit_tier2 is None else jit_tier2
    indikasi_buzzer = _deteksi_indikasi_buzzer(pencarian, korroborasi)
    jit_diindeks: list[str] = []
    jit_cache_hit: list[str] = []

    if keputusan.tier1_memadai:
        target_kandidat = keputusan.kandidat_memadai[: max(1, maks_kandidat)]
        sinyal_sumber = [
            sumber.ekstrak_sinyal_kandidat(k, ambil_konten_eksternal=ambil_konten_eksternal)
            for k in target_kandidat
        ]

        semua_gagal_penuh = all(not s.ekstraksi_penuh_berhasil for s in sinyal_sumber)
        hasil_rag: list[HasilCariKorpus] = []
        if keputusan.perlu_rag or semua_gagal_penuh:
            if jit_aktif and ambil_konten_eksternal and keputusan.kandidat_tier2:
                jit_diindeks, jit_cache_hit = _indeks_jit_tier2(
                    keputusan.kandidat_tier2,
                    ambil_konten_eksternal=ambil_konten_eksternal,
                    maks_jit=maks_jit,
                )
            cakupan_cari: CakupanKorpus | list[CakupanKorpus] = (
                ["resmi", "temuan"] if keputusan.kandidat_tier2 else "resmi"
            )
            hasil_rag = _cari_korpus_relevan(
                sinyal_klaim,
                batas=batas_rag,
                ambang_vector=ambang_rag_vector,
                cakupan=cakupan_cari,
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
            jit_diindeks=jit_diindeks,
            jit_cache_hit=jit_cache_hit,
            indikasi_buzzer=indikasi_buzzer,
        )

    # Jalur 2: Tier-1 tidak menemukan kecocokan footage/sumber meyakinkan -> JIT Tier-2 (bila ada) & Tahap 3 RAG
    if jit_aktif and ambil_konten_eksternal and keputusan.kandidat_tier2:
        jit_diindeks, jit_cache_hit = _indeks_jit_tier2(
            keputusan.kandidat_tier2,
            ambil_konten_eksternal=ambil_konten_eksternal,
            maks_jit=maks_jit,
        )
    cakupan_tier2: CakupanKorpus | list[CakupanKorpus] = (
        ["resmi", "temuan"] if keputusan.kandidat_tier2 else "resmi"
    )
    hasil_rag = _cari_korpus_relevan(
        sinyal_klaim,
        batas=batas_rag,
        ambang_vector=ambang_rag_vector,
        cakupan=cakupan_tier2,
    )
    if hasil_rag:
        info_jit = (
            f" ({len(jit_diindeks)} sumber baru diindeks JIT, {len(jit_cache_hit)} dari cache)"
            if (jit_diindeks or jit_cache_hit)
            else ""
        )
        return HasilTahap2(
            claim_id=klaim.claim_id,
            jalur="tier2_rag_ke_tahap4",
            siap_tahap4=True,
            status_rekomendasi=None,
            perlu_eskalasi=False,
            alasan_routing=f"{keputusan.alasan} Ditemukan {len(hasil_rag)} rujukan di Tahap 3 RAG{info_jit}.",
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
            jit_diindeks=jit_diindeks,
            jit_cache_hit=jit_cache_hit,
            indikasi_buzzer=indikasi_buzzer,
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
        f"{keputusan.alasan} Pencarian Tahap 3 RAG juga tidak menemukan sumber yang relevan."
    )
    if indikasi_buzzer:
        alasan_eskalasi += " Terdeteksi pola unggahan akun pribadi berulang tanpa rujukan resmi/media."

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
        jit_diindeks=jit_diindeks,
        jit_cache_hit=jit_cache_hit,
        indikasi_buzzer=indikasi_buzzer,
    )
