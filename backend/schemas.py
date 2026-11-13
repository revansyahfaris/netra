"""Kontrak data antar modul Netra.

Alur: Klaim -> (prioritas) -> HasilPencarian berisi KandidatSumber -> (lapisan AI) -> HasilVerifikasi
Ubah file ini hanya setelah disepakati tim, karena semua modul bergantung padanya.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

# ---------- Nilai pilihan ----------

JenisMedia = Literal["video", "gambar", "teks"]
LevelPrioritas = Literal["tinggi", "sedang", "rendah"]
LabelTopik = Literal["pimpinan", "operasi", "sara", "keselamatan", "umum"]
JenisSumber = Literal["resmi", "media", "pribadi"]
MetodePencarian = Literal["keyword", "kutipan", "frame_match"]
StatusVerifikasi = Literal["terbukti_diubah", "tidak_ditemukan", "belum_bisa_diverifikasi"]
JenisPerubahan = Literal["dipotong", "tanggal_berbeda", "kutipan_tidak_ada", "konteks_berbeda", "lainnya"]


# ---------- Klaim (input pipeline + hasil modul prioritas) ----------

class Klaim(BaseModel):
    claim_id: str
    teks_klaim: str
    media_url: Optional[HttpUrl] = None
    jenis_media: JenisMedia
    tanggal_ditemukan: datetime

    # Sinyal penyebaran (dari sistem deteksi yang sudah ada)
    jumlah_share: int = Field(0, ge=0)
    jumlah_view: int = Field(0, ge=0)
    laju_sebar: float = Field(0, ge=0, description="Kenaikan share per jam")
    pengikut_pengunggah: int = Field(0, ge=0)

    # Diisi oleh modul prioritas
    skor_prioritas: Optional[float] = Field(None, ge=0, le=1)
    level: Optional[LevelPrioritas] = None
    label_topik: Optional[LabelTopik] = None
    alasan: Optional[str] = None


# ---------- Kandidat sumber (output modul pencari) ----------

class KandidatSumber(BaseModel):
    url: HttpUrl
    tanggal_unggah: Optional[datetime] = None
    jenis_sumber: JenisSumber
    metode: MetodePencarian
    kemiripan: float = Field(..., ge=0, le=1)
    cuplikan: Optional[str] = Field(None, description="Potongan teks atau timestamp, mis. '01:12'")
    resolusi: Optional[int] = Field(None, ge=0, description="Tinggi video/gambar dalam piksel, mis. 1080")
    ada_watermark: Optional[bool] = None
    kecocokan_audio: Optional[float] = Field(None, ge=0, le=1)
    skor: Optional[float] = Field(None, ge=0, le=1, description="Skor peringkat sumber asli")


class HasilPencarian(BaseModel):
    claim_id: str
    kandidat: list[KandidatSumber] = []


# ---------- Hasil verifikasi (output lapisan AI) ----------

class DrafKlarifikasi(BaseModel):
    kartu: str
    pendek: str
    whatsapp: str


class HasilVerifikasi(BaseModel):
    claim_id: str
    status: StatusVerifikasi
    sumber_utama: Optional[HttpUrl] = None
    perubahan: list[JenisPerubahan] = []
    draf_klarifikasi: Optional[DrafKlarifikasi] = None
    perlu_eskalasi: bool = False


# ---------- Persetujuan petugas & bukti publik ----------

StatusPersetujuan = Literal["menunggu", "disetujui", "ditolak"]


class KeputusanPetugas(BaseModel):
    """Body dari dashboard saat petugas memutuskan."""
    keputusan: Literal["disetujui", "ditolak"]
    petugas: str
    catatan: Optional[str] = None
    draf_final: Optional[DrafKlarifikasi] = Field(None, description="Isi kalau petugas mengedit draf; kosong = pakai draf AI")


class Persetujuan(BaseModel):
    claim_id: str
    status: StatusPersetujuan = "menunggu"
    petugas: Optional[str] = None
    catatan: Optional[str] = None
    draf_final: Optional[DrafKlarifikasi] = None
    waktu_keputusan: Optional[datetime] = None


class BuktiPublik(BaseModel):
    """Ringkasan yang aman ditampilkan ke publik (hanya untuk klaim yang sudah disetujui)."""
    claim_id: str
    teks_klaim: str
    status: StatusVerifikasi
    perubahan: list[JenisPerubahan] = []
    sumber_utama: Optional[HttpUrl] = None
    sumber_pendukung: list[KandidatSumber] = []
    klarifikasi: DrafKlarifikasi
    disetujui_pada: datetime
