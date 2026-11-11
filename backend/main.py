"""API Netra: penghubung semua modul.

Jalankan dari folder backend:
    uvicorn main:app --reload
Lalu buka http://localhost:8000/docs

Alur: POST /prioritas -> GET /antrean -> POST /cari/{id} -> POST /verifikasi/{id}
Atau sekaligus: POST /pipeline/{id}
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from priority import hitung_prioritas
from schemas import DrafKlarifikasi, HasilPencarian, HasilVerifikasi, Klaim
from search import cari_sumber

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Penyimpanan sementara di memori (hilang saat server restart)
KLAIM: dict[str, Klaim] = {}
PENCARIAN: dict[str, HasilPencarian] = {}
PROSES_PENCARIAN: dict[str, dict] = {}
VERIFIKASI: dict[str, HasilVerifikasi] = {}


def muat_dummy():
    f = config.DUMMY_DIR / "klaim.json"
    if f.exists():
        for item in json.loads(f.read_text(encoding="utf-8")):
            k = hitung_prioritas(Klaim(**item))
            KLAIM[k.claim_id] = k


@asynccontextmanager
async def lifespan(app: FastAPI):
    muat_dummy()
    yield


app = FastAPI(title="Netra API", version="0.2.0", lifespan=lifespan)

# Supaya dashboard (beda port/domain) bisa memanggil API ini
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _ambil_klaim(claim_id: str) -> Klaim:
    if claim_id not in KLAIM:
        raise HTTPException(404, "Klaim tidak ditemukan")
    return KLAIM[claim_id]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "jumlah_klaim": len(KLAIM),
        "llm": "aktif" if config.llm_aktif() else "fallback keyword",
        "pencarian": "live" if config.search_aktif() else "demo",
    }


# ---------- Prioritas (Faris) ----------

@app.post("/prioritas", response_model=Klaim, tags=["prioritas"])
def tambah_klaim(klaim: Klaim):
    """Terima klaim dari sistem deteksi, beri skor prioritas, masukkan ke antrean."""
    k = hitung_prioritas(klaim)
    KLAIM[k.claim_id] = k
    return k


@app.get("/antrean", response_model=list[Klaim], tags=["prioritas"])
def antrean():
    return sorted(KLAIM.values(), key=lambda k: k.skor_prioritas or 0, reverse=True)


@app.get("/klaim/{claim_id}", response_model=Klaim, tags=["prioritas"])
def detail_klaim(claim_id: str):
    return _ambil_klaim(claim_id)


# ---------- Pencarian sumber (Faris) ----------

class PermintaanCari(BaseModel):
    url_manual: list[str] = []   # kandidat yang ditemukan petugas secara manual (semi-manual)


@app.post("/cari/{claim_id}", response_model=HasilPencarian, tags=["pencarian"])
def cari(claim_id: str, req: PermintaanCari | None = None):
    """Cari kandidat sumber asli, lalu urutkan dari yang paling mungkin asli."""
    k = _ambil_klaim(claim_id)
    hasil, proses = cari_sumber(k, (req.url_manual if req else []))
    PENCARIAN[claim_id] = hasil
    PROSES_PENCARIAN[claim_id] = proses
    return hasil


@app.get("/cari/{claim_id}", response_model=HasilPencarian, tags=["pencarian"])
def ambil_pencarian(claim_id: str):
    if claim_id not in PENCARIAN:
        raise HTTPException(404, "Belum dicari")
    return PENCARIAN[claim_id]


@app.get("/cari/{claim_id}/proses", tags=["pencarian"])
def proses_pencarian(claim_id: str):
    """Rincian proses: mode, query yang dipakai, video yang dicocokkan, rincian skor tiap kandidat."""
    if claim_id not in PROSES_PENCARIAN:
        raise HTTPException(404, "Belum dicari")
    return PROSES_PENCARIAN[claim_id]


# ---------- Verifikasi & klarifikasi (Adriel) ----------

def jalankan_verifikasi(klaim: Klaim, pencarian: HasilPencarian) -> HasilVerifikasi:
    """TODO (Adriel): ganti dengan RAG + OCR/transkrip + perbandingan LLM.
    Input: klaim + kandidat terurut. Output: HasilVerifikasi."""
    if not pencarian.kandidat:
        return HasilVerifikasi(claim_id=klaim.claim_id, status="tidak_ditemukan", perlu_eskalasi=True)
    utama = pencarian.kandidat[0]
    return HasilVerifikasi(
        claim_id=klaim.claim_id,
        status="terbukti_diubah",
        sumber_utama=utama.url,
        perubahan=["tanggal_berbeda", "konteks_berbeda"],
        draf_klarifikasi=DrafKlarifikasi(
            kartu="[CONTOH] Konten ini bukan kejadian terbaru.",
            pendek="[CONTOH] Konten lama diunggah ulang dengan narasi baru.",
            whatsapp=f"[CONTOH] Cek fakta: konten yang beredar berasal dari {utama.url}",
        ),
        perlu_eskalasi=False,
    )


@app.post("/verifikasi/{claim_id}", response_model=HasilVerifikasi, tags=["verifikasi"])
def verifikasi(claim_id: str):
    k = _ambil_klaim(claim_id)
    if claim_id not in PENCARIAN:
        raise HTTPException(400, "Jalankan /cari dulu untuk klaim ini")
    hasil = jalankan_verifikasi(k, PENCARIAN[claim_id])
    VERIFIKASI[claim_id] = hasil
    return hasil


@app.get("/verifikasi/{claim_id}", response_model=HasilVerifikasi, tags=["verifikasi"])
def ambil_verifikasi(claim_id: str):
    if claim_id not in VERIFIKASI:
        raise HTTPException(404, "Belum diverifikasi")
    return VERIFIKASI[claim_id]


# ---------- Pipeline sekaligus ----------

class HasilPipeline(BaseModel):
    klaim: Klaim
    pencarian: HasilPencarian
    verifikasi: HasilVerifikasi


@app.post("/pipeline/{claim_id}", response_model=HasilPipeline, tags=["pipeline"])
def pipeline(claim_id: str, req: PermintaanCari | None = None):
    """Cari sumber lalu verifikasi dalam satu panggilan (untuk demo)."""
    k = _ambil_klaim(claim_id)
    pencarian = cari(claim_id, req)
    hasil = jalankan_verifikasi(k, pencarian)
    VERIFIKASI[claim_id] = hasil
    return HasilPipeline(klaim=k, pencarian=pencarian, verifikasi=hasil)
