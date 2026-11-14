"""Tahap 5: Scoring akhir, perakitan paket verifikasi, dan draf klarifikasi multi-format.

Mengonversi keluaran penalaran Tahap 4 (`HasilVerifikasiSilang`) beserta konteks
Tahap 2/3 (`HasilTahap2`) menjadi kontrak API `schemas.HasilVerifikasi`, menyusun
3 format draf klarifikasi (kartu, pendek, whatsapp), dan mengekstrak tautan relasional
untuk tabel `netra_klaim_bukti`.
"""

from __future__ import annotations

import logging
from typing import Iterable

from pydantic import HttpUrl, TypeAdapter, ValidationError

import config
import llm
import url_kanonis
from schemas import DrafKlarifikasi, HasilPencarian, HasilVerifikasi, Klaim
from store import TautanBukti, tautan_dari_hasil_rag, tautan_dari_kandidat

from .routing import HasilTahap2
from .verifikasi import (
    AMBANG_KEYAKINAN_PUTUSAN,
    HasilVerifikasiSilang,
    konversi_ke_bukti_schema,
)

log = logging.getLogger("netra.ai.klarifikasi")

_URL_ADAPTER = TypeAdapter(HttpUrl)

SYSTEM_PROMPT_KLARIFIKASI = """Anda adalah editor klarifikasi cek fakta TNI AD (Bahasa Indonesia baku, netral, tegas, tanpa opini pribadi atau serangan personal).
Tugas: susun 3 format draf klarifikasi publik berdasarkan HANYA fakta yang diberikan pada data input.
Larangan keras:
1. Jangan mengarang tanggal, lokasi, nama tokoh, atau tautan URL yang tidak ada di input.
2. Jangan menyertakan jargon internal (tier, RAG, score, frame_match) di teks publik.
3. Pertahankan akurasi fakta dan rujukan sumber resmi/media yang tersedia."""

SCHEMA_DRAF_KLARIFIKASI = {
    "type": "OBJECT",
    "properties": {
        "kartu": {
            "type": "STRING",
            "description": "Teks sangat ringkas 1-2 kalimat (<= 220 karakter) untuk kartu grafis/banner klarifikasi.",
        },
        "pendek": {
            "type": "STRING",
            "description": "Ringkasan caption/tanggapan singkat 1-2 paragraf untuk media sosial.",
        },
        "whatsapp": {
            "type": "STRING",
            "description": "Pesan berantai klarifikasi terstruktur untuk WhatsApp (klaim beredar, fakta sebenarnya, tautan rujukan).",
        },
    },
    "required": ["kartu", "pendek", "whatsapp"],
}

LABEL_PERUBAHAN: dict[str, str] = {
    "tanggal_berbeda": "rekaman/informasi lama dari tanggal berbeda",
    "dipotong": "cuplikan dipotong dari konteks utuhnya",
    "kutipan_tidak_ada": "kutipan/pernyataan tidak ditemukan pada sumber resmi",
    "konteks_berbeda": "narasi yang beredar berbeda dari konteks aslinya",
    "lainnya": "terdapat ketidaksesuaian informasi dengan sumber rujukan",
}


def _url_valid(url: str | None) -> HttpUrl | None:
    if not url or not url.strip():
        return None
    try:
        return _URL_ADAPTER.validate_python(url.strip())
    except ValidationError:
        return None


def _potong(teks: str, maks: int) -> str:
    bersih = " ".join(teks.split())
    if len(bersih) <= maks:
        return bersih
    potongan = bersih[: max(1, maks - 3)].rsplit(" ", 1)[0].rstrip(",;:")
    return (potongan or bersih[: maks - 3]) + "..."


def _rakit_draf_deterministik(klaim: Klaim, hasil_v4: HasilVerifikasiSilang) -> DrafKlarifikasi:
    fakta = hasil_v4.fakta_utama.strip() or hasil_v4.ringkasan.strip()
    diubah = hasil_v4.apa_yang_diubah.strip()
    label_perubahan = ", ".join(
        LABEL_PERUBAHAN.get(p, p) for p in hasil_v4.perubahan
    ) or "tidak sesuai konteks aslinya"
    rujukan_judul = hasil_v4.sumber_utama_judul or "sumber rujukan terverifikasi"
    rujukan_tgl = f" ({hasil_v4.sumber_utama_tanggal})" if hasil_v4.sumber_utama_tanggal else ""
    rujukan_url = hasil_v4.sumber_utama_url or ""

    inti_kartu = diubah or fakta or f"Klaim ini {label_perubahan}."
    kartu = _potong(f"KLARIFIKASI: {inti_kartu}", 220)

    kalimat_pendek = [f"Informasi yang beredar perlu diluruskan ({label_perubahan})."]
    if fakta:
        kalimat_pendek.append(fakta)
    if diubah and diubah.lower() not in fakta.lower():
        kalimat_pendek.append(diubah)
    if rujukan_url:
        kalimat_pendek.append(f"Rujukan: {rujukan_judul}{rujukan_tgl} ({rujukan_url}).")
    pendek = " ".join(kalimat_pendek)

    baris_wa = [
        "*[KLARIFIKASI CEK FAKTA]*",
        "",
        f"*Klaim beredar:* {_potong(klaim.teks_klaim, 200)}",
    ]
    if diubah:
        baris_wa.append(f"*Hasil pemeriksaan:* {diubah}")
    else:
        baris_wa.append(f"*Hasil pemeriksaan:* Terdeteksi {label_perubahan}.")
    if fakta:
        baris_wa.append(f"*Fakta rujukan:* {fakta}")
    if rujukan_url:
        baris_wa.append(f"*Sumber rujukan ({rujukan_judul}{rujukan_tgl}):* {rujukan_url}")
    elif hasil_v4.bukti:
        baris_wa.append(f"*Sumber rujukan:* {hasil_v4.bukti[0].url}")
    baris_wa.append("")
    baris_wa.append("Mohon tidak menyebarkan kembali informasi tanpa memeriksa konteks aslinya.")

    return DrafKlarifikasi(
        kartu=kartu,
        pendek=pendek,
        whatsapp="\n".join(baris_wa),
    )


def _prompt_draf(klaim: Klaim, hasil_v4: HasilVerifikasiSilang) -> str:
    label_perubahan = ", ".join(hasil_v4.perubahan) or "konteks_berbeda"
    bukti_teks = "\n".join(
        f"- [{b.jenis}] {b.url}"
        + (f" ({b.cuplikan})" if b.cuplikan else "")
        + (f": {b.catatan}" if b.catatan else "")
        for b in hasil_v4.bukti[:4]
    )
    return "\n".join(
        [
            f"Klaim beredar: {klaim.teks_klaim}",
            f"Jenis perubahan: {label_perubahan}",
            f"Ringkasan Tahap 4: {hasil_v4.ringkasan or '-'}",
            f"Fakta sumber asli: {hasil_v4.fakta_utama or '-'}",
            f"Apa yang diubah: {hasil_v4.apa_yang_diubah or '-'}",
            f"Sumber utama URL: {hasil_v4.sumber_utama_url or '-'}",
            f"Sumber utama judul: {hasil_v4.sumber_utama_judul or '-'}",
            f"Sumber utama tanggal: {hasil_v4.sumber_utama_tanggal or '-'}",
            "Daftar bukti terverifikasi:",
            bukti_teks or "- (tidak ada)",
        ]
    )


def buat_draf_klarifikasi(
    klaim: Klaim,
    hasil_v4: HasilVerifikasiSilang,
    *,
    pakai_llm: bool = True,
    model: str | None = None,
    timeout: float | None = None,
) -> DrafKlarifikasi:
    """Bangun 3 format draf klarifikasi (LLM dengan fallback deterministik berbasis fakta Tahap 4)."""
    if not pakai_llm or not config.llm_aktif():
        return _rakit_draf_deterministik(klaim, hasil_v4)

    try:
        mentah = llm.tanya_json(
            _prompt_draf(klaim, hasil_v4),
            suhu=0.2,
            model=model or config.GEMINI_MODEL,
            thinking="low",
            skema=SCHEMA_DRAF_KLARIFIKASI,
            timeout=timeout,
            instruksi_sistem=SYSTEM_PROMPT_KLARIFIKASI,
        )
        if isinstance(mentah, dict):
            return DrafKlarifikasi.model_validate(mentah)
    except (llm.LLMError, ValidationError, ValueError, TypeError) as e:
        log.warning("Pembuatan draf klarifikasi LLM gagal (%s), pakai template faktual: %s", klaim.claim_id, e)

    return _rakit_draf_deterministik(klaim, hasil_v4)


def susun_hasil_verifikasi(
    klaim: Klaim,
    hasil_tahap2: HasilTahap2,
    hasil_v4: HasilVerifikasiSilang,
    *,
    waktu_proses_detik: float | None = None,
    buat_draf_llm: bool = True,
    ambang_keyakinan: float = AMBANG_KEYAKINAN_PUTUSAN,
) -> HasilVerifikasi:
    """Konversi hasil Tahap 2/3/4 menjadi `schemas.HasilVerifikasi` siap simpan/tampil."""
    keyakinan = round(max(0.0, min(float(hasil_v4.keyakinan), 1.0)), 4)
    status = hasil_v4.status
    perlu_eskalasi = hasil_v4.perlu_eskalasi
    perubahan = list(hasil_v4.perubahan)

    if status == "terbukti_diubah" and (
        keyakinan < ambang_keyakinan or not perubahan or perlu_eskalasi
    ):
        status = "belum_bisa_diverifikasi"
        perlu_eskalasi = True

    if status != "terbukti_diubah":
        perlu_eskalasi = True
        draf: DrafKlarifikasi | None = None
    else:
        perlu_eskalasi = False
        draf = buat_draf_klarifikasi(klaim, hasil_v4, pakai_llm=buat_draf_llm)

    ringkasan = (hasil_v4.ringkasan or "").strip()
    if not ringkasan:
        ringkasan = (hasil_v4.alasan_eskalasi or hasil_v4.fakta_utama or hasil_tahap2.alasan_routing).strip()
    if perlu_eskalasi and hasil_tahap2.indikasi_buzzer and "akun pribadi" not in ringkasan.lower():
        ringkasan = f"{ringkasan} Terdeteksi unggahan berulang dari akun pribadi tanpa sumber resmi/media.".strip()

    sumber_utama = _url_valid(hasil_v4.sumber_utama_url)
    bukti = konversi_ke_bukti_schema(hasil_v4.bukti)
    metode = list(hasil_v4.metode or hasil_tahap2.metode_terpakai)

    return HasilVerifikasi(
        claim_id=klaim.claim_id,
        status=status,
        sumber_utama=sumber_utama,
        perubahan=perubahan,
        draf_klarifikasi=draf,
        perlu_eskalasi=perlu_eskalasi,
        ringkasan=ringkasan,
        bukti=bukti,
        keyakinan=keyakinan,
        metode=metode,
        waktu_proses_detik=waktu_proses_detik,
    )


def _tambah_unik(daftar: list[TautanBukti], terlihat: set[tuple], item: TautanBukti) -> None:
    kunci = (item.chunk_id, item.doc_id, item.tier)
    if kunci in terlihat:
        return
    terlihat.add(kunci)
    daftar.append(item)


def kumpulkan_tautan_bukti(
    klaim: Klaim,
    hasil_tahap2: HasilTahap2,
    hasil_v4: HasilVerifikasiSilang,
    hasil_pencarian: HasilPencarian | None = None,
) -> list[TautanBukti]:
    """Kumpulkan relasi dokumen/chunk bukti untuk disimpan ke `netra_klaim_bukti`."""
    keluar: list[TautanBukti] = []
    terlihat: set[tuple] = set()
    kanon_klaim = url_kanonis.normalisasi_url(str(klaim.media_url)) if klaim.media_url else ""
    kanon_utama = (
        url_kanonis.normalisasi_url(hasil_v4.sumber_utama_url)
        if hasil_v4.sumber_utama_url
        else ""
    )

    # 1. Chunk RAG yang benar-benar menjadi rujukan (mempertahankan doc_id + chunk_id)
    for item in hasil_tahap2.hasil_rag:
        kanon = url_kanonis.normalisasi_url(item.url)
        peran = "acuan_utama" if (kanon_utama and kanon == kanon_utama) else "pembanding"
        try:
            _tambah_unik(keluar, terlihat, tautan_dari_hasil_rag(item, peran=peran))
        except ValueError:
            continue

    # 2. Kandidat bersih Tier-1 yang dievaluasi
    sudah_kandidat: set[str] = set()
    sumber_kandidat: Iterable = (
        list(hasil_tahap2.kandidat_bersih)
        + (list(hasil_pencarian.kandidat) if hasil_pencarian else [])
    )
    for k in sumber_kandidat:
        url_str = str(k.url)
        kanon = url_kanonis.normalisasi_url(url_str)
        if not kanon or kanon == kanon_klaim or kanon in sudah_kandidat:
            continue
        if k.jenis_sumber == "pribadi" and not hasil_tahap2.perlu_eskalasi:
            continue
        sudah_kandidat.add(kanon)
        peran = (
            "acuan_utama"
            if (kanon_utama and kanon == kanon_utama)
            else ("korroborasi" if k.jenis_sumber in ("resmi", "media") else "pembanding")
        )
        try:
            _tambah_unik(keluar, terlihat, tautan_dari_kandidat(k, peran=peran))
        except ValueError:
            continue

    # 3. URL bukti tambahan dari Tahap 4 (jika belum tercakup dari RAG/kandidat)
    for b in hasil_v4.bukti:
        kanon = url_kanonis.normalisasi_url(b.url)
        if not kanon or kanon == kanon_klaim:
            continue
        peran = "acuan_utama" if (kanon_utama and kanon == kanon_utama) else "pembanding"
        tier_val = "tier2_rag" if "rag" in hasil_v4.metode else "tier1"
        try:
            _tambah_unik(
                keluar,
                terlihat,
                TautanBukti(
                    tier=tier_val,
                    metode=hasil_v4.metode[0] if hasil_v4.metode else "rag",
                    peran=peran,
                    skor=hasil_v4.keyakinan,
                    url=b.url,
                    cuplikan=b.cuplikan,
                    catatan=b.catatan,
                ),
            )
        except ValueError:
            continue

    return keluar
