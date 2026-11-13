"""Kontrak data antar modul Netra.

Alur: Klaim -> (prioritas) -> HasilPencarian berisi KandidatSumber -> (lapisan AI) -> HasilVerifikasi
Ubah file ini hanya setelah disepakati tim, karena semua modul bergantung padanya.

Versi 2 (13 Nov): tambahan field untuk dashboard & persetujuan petugas. Semua perubahan aditif,
modul lama tetap jalan tanpa diubah.
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

# Siklus hidup klaim di dashboard
StatusPipeline = Literal[
    "baru",                  # masuk antrean, belum dicari
    "dicari",                # kandidat sumber sudah ada
    "diverifikasi",          # lapisan AI sudah memberi status
    "menunggu_persetujuan",  # draf klarifikasi siap, menunggu petugas
    "disetujui",             # petugas menyetujui klarifikasi
    "ditolak",               # petugas menolak / minta perbaikan
    "dipublikasi",           # klarifikasi sudah tayang
]
StatusPersetujuan = Literal["menunggu", "disetujui", "ditolak"]
MetodeVerifikasi = Literal["rag", "frame_match", "ocr", "asr", "manual"]
JenisBukti = Literal["kutipan", "frame", "transkrip", "metadata"]


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

    # Siklus hidup di dashboard
    status_pipeline: StatusPipeline = "baru"
    sumber_masuk: Literal["deteksi", "manual"] = "deteksi"


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

    # Untuk tampilan dashboard
    judul: Optional[str] = None
    uploader: Optional[str] = None
    thumbnail_url: Optional[str] = None
    rincian_skor: dict[str, float] = Field(default_factory=dict)


class HasilPencarian(BaseModel):
    claim_id: str
    kandidat: list[KandidatSumber] = []
    mode: Literal["live", "demo", "manual"] = "demo"
    diperbarui: Optional[datetime] = None


# ---------- Bukti & hasil verifikasi (output lapisan AI) ----------

class Bukti(BaseModel):
    jenis: JenisBukti
    url: HttpUrl
    cuplikan: Optional[str] = Field(None, description="Teks kutipan atau timestamp, mis. '00:42'")
    teks_viral: Optional[str] = None
    teks_sumber: Optional[str] = None
    catatan: Optional[str] = None


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

    # Paket bukti & penjelasan
    ringkasan: Optional[str] = None
    bukti: list[Bukti] = []
    keyakinan: Optional[float] = Field(None, ge=0, le=1)
    metode: list[MetodeVerifikasi] = []
    waktu_proses_detik: Optional[float] = Field(None, ge=0)
    waktu_verifikasi: Optional[datetime] = None

    # Persetujuan manusia (diisi lewat PATCH /verifikasi/{id}/persetujuan)
    status_persetujuan: StatusPersetujuan = "menunggu"
    catatan_petugas: Optional[str] = None
    disetujui_oleh: Optional[str] = None
    waktu_persetujuan: Optional[datetime] = None


# ---------- Dokumen lengkap untuk dashboard ----------

class RiwayatAksi(BaseModel):
    aksi: str
    aktor: Optional[str] = None
    waktu: datetime
    detail: dict = Field(default_factory=dict)


class KlaimLengkap(BaseModel):
    klaim: Klaim
    pencarian: Optional[HasilPencarian] = None
    proses_pencarian: Optional[dict] = None
    verifikasi: Optional[HasilVerifikasi] = None
    riwayat: list[RiwayatAksi] = []


class PermintaanPersetujuan(BaseModel):
    keputusan: Literal["disetujui", "ditolak"]
    petugas: str = Field(..., min_length=2, description="Nama petugas yang memutuskan")
    catatan: Optional[str] = None