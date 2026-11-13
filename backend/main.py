"""API Netra: penghubung semua modul.

Jalankan dari folder backend:
    uvicorn main:app --reload
Lalu buka http://localhost:8000/docs

Alur: POST /prioritas -> GET /antrean -> POST /cari/{id} -> POST /verifikasi/{id}
      -> PATCH /verifikasi/{id}/persetujuan -> GET /bukti/{id}
Atau sekaligus: POST /pipeline/{id}
"""

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from priority import hitung_prioritas
from schemas import (
    Bukti,
    DrafKlarifikasi,
    HasilPencarian,
    HasilVerifikasi,
    Klaim,
    KlaimLengkap,
    PermintaanPersetujuan,
)
from search import cari_sumber
from store import (
    Repo,
    TidakBoleh,
    TidakDitemukan,
    get_repo,
    seed_kalau_kosong,
    seed_ulang,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("netra.api")

REPO: Repo = get_repo()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from store import init_db

    init_db()
    if config.SEED_KALAU_KOSONG:
        seed_kalau_kosong(REPO)
    log.info("Netra siap. Klaim di database: %d", len(REPO.daftar_klaim()))
    yield


app = FastAPI(title="Netra API", version="0.3.0", lifespan=lifespan)

# Supaya dashboard (beda port/domain) bisa memanggil API ini
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _ambil_klaim(claim_id: str) -> Klaim:
    k = REPO.ambil_klaim(claim_id)
    if k is None:
        raise HTTPException(404, "Klaim tidak ditemukan")
    return k


@app.get("/health")
def health():
    return {
        "status": "ok",
        "jumlah_klaim": len(REPO.daftar_klaim()),
        "llm": "aktif" if config.llm_aktif() else "fallback keyword",
        "pencarian": "live" if config.search_aktif() else "demo",
        "database": "postgres" if config.DATABASE_URL else "sqlite",
    }


# ---------- Prioritas (Faris) ----------

@app.post("/prioritas", response_model=Klaim, tags=["prioritas"])
def tambah_klaim(klaim: Klaim):
    """Terima klaim dari sistem deteksi, beri skor prioritas, masukkan ke antrean."""
    k = hitung_prioritas(klaim)
    return REPO.simpan_klaim(k, aktor="api")


@app.get("/antrean", response_model=list[KlaimLengkap], tags=["prioritas"])
def antrean(
    status: str | None = Query(None, description="Filter status_pipeline"),
    level: str | None = Query(None, description="tinggi / sedang / rendah"),
):
    """Klaim terurut dari prioritas tertinggi, lengkap dengan status verifikasi."""
    return REPO.daftar_lengkap(status=status, level=level)


@app.get("/klaim/{claim_id}", response_model=KlaimLengkap, tags=["prioritas"])
def detail_klaim(claim_id: str):
    hasil = REPO.ambil_lengkap(claim_id)
    if hasil is None:
        raise HTTPException(404, "Klaim tidak ditemukan")
    return hasil


# ---------- Pencarian sumber (Faris) ----------

class PermintaanCari(BaseModel):
    url_manual: list[str] = []   # kandidat yang ditemukan petugas secara manual (semi-manual)


@app.post("/cari/{claim_id}", response_model=HasilPencarian, tags=["pencarian"])
def cari(claim_id: str, req: PermintaanCari | None = None):
    """Cari kandidat sumber asli, lalu urutkan dari yang paling mungkin asli."""
    k = _ambil_klaim(claim_id)
    hasil, proses = cari_sumber(k, (req.url_manual if req else []))
    hasil = hasil.model_copy(update={"mode": proses.get("mode", "demo")})
    return REPO.simpan_pencarian(hasil, proses, aktor="api")


@app.get("/cari/{claim_id}", response_model=HasilPencarian, tags=["pencarian"])
def ambil_pencarian(claim_id: str):
    hasil = REPO.ambil_pencarian(claim_id)
    if hasil is None:
        raise HTTPException(404, "Belum dicari")
    return hasil[0]


@app.get("/cari/{claim_id}/proses", tags=["pencarian"])
def proses_pencarian(claim_id: str):
    """Rincian proses: mode, query yang dipakai, video yang dicocokkan, rincian skor tiap kandidat."""
    hasil = REPO.ambil_pencarian(claim_id)
    if hasil is None:
        raise HTTPException(404, "Belum dicari")
    return hasil[1]


# ---------- Verifikasi & klarifikasi (Adriel) ----------

def jalankan_verifikasi(klaim: Klaim, pencarian: HasilPencarian) -> HasilVerifikasi:
    """TODO(Adriel): ganti dengan RAG + OCR/transkrip + perbandingan LLM.

    Versi sementara ini deterministik supaya dashboard bisa diuji end-to-end:
    - tanpa kandidat                  -> tidak_ditemukan
    - semua kandidat pribadi/watermark -> belum_bisa_diverifikasi (eskalasi)
    - ada kandidat bersih             -> terbukti_diubah + bukti metadata
    """
    mulai = time.perf_counter()
    kandidat = pencarian.kandidat
    if not kandidat:
        return HasilVerifikasi(
            claim_id=klaim.claim_id,
            status="tidak_ditemukan",
            ringkasan="Tidak ada sumber pendukung yang ditemukan untuk klaim ini.",
            perlu_eskalasi=True,
            metode=["manual"],
            waktu_proses_detik=round(time.perf_counter() - mulai, 3),
        )

    bersih = [k for k in kandidat if k.jenis_sumber != "pribadi" and not k.ada_watermark]
    if not bersih:
        return HasilVerifikasi(
            claim_id=klaim.claim_id,
            status="belum_bisa_diverifikasi",
            sumber_utama=kandidat[0].url,
            ringkasan=(
                "Kandidat sumber ditemukan, tetapi yang tertua pun berasal dari akun pribadi "
                "dan/atau berwatermark. Tidak ada sumber yang bisa dianggap otentik."
            ),
            perlu_eskalasi=True,
            metode=["frame_match"],
            waktu_proses_detik=round(time.perf_counter() - mulai, 3),
        )

    utama = bersih[0]
    perubahan = []
    if utama.tanggal_unggah and utama.tanggal_unggah.year < klaim.tanggal_ditemukan.year:
        perubahan.append("tanggal_berbeda")
    if utama.cuplikan and ":" in str(utama.cuplikan):
        perubahan.append("dipotong")
    if not perubahan:
        perubahan.append("konteks_berbeda")

    bukti = [
        Bukti(
            jenis="metadata",
            url=utama.url,
            cuplikan=utama.cuplikan,
            teks_sumber=utama.judul or None,
            catatan=(
                f"Kandidat peringkat 1 (skor {utama.skor or 0:.2f}), "
                f"diunggah {utama.tanggal_unggah:%d %b %Y}" if utama.tanggal_unggah else "Kandidat peringkat 1"
            ),
        )
    ]
    if klaim.media_url:
        bukti.append(Bukti(
            jenis="frame" if klaim.jenis_media == "video" else "kutipan",
            url=klaim.media_url,
            cuplikan=utama.cuplikan,
            teks_viral=klaim.teks_klaim,
            teks_sumber=utama.judul or None,
            catatan="Perbandingan konten viral dengan kandidat sumber asli.",
        ))

    return HasilVerifikasi(
        claim_id=klaim.claim_id,
        status="terbukti_diubah",
        sumber_utama=utama.url,
        perubahan=perubahan,
        ringkasan=(
            f"Konten yang beredar cocok dengan sumber yang lebih awal "
            f"({utama.tanggal_unggah:%d %b %Y})." if utama.tanggal_unggah
            else "Konten yang beredar cocok dengan sumber yang lebih awal."
        ),
        bukti=bukti,
        keyakinan=utama.skor,
        metode=["frame_match"] if klaim.jenis_media == "video" else ["rag"],
        draf_klarifikasi=DrafKlarifikasi(
            kartu="[DRAF] Konten ini bukan kejadian baru. Sumber asli lebih awal dan konteksnya berbeda.",
            pendek="[DRAF] Video/klaim ini sudah pernah beredar sebelumnya dengan konteks berbeda.",
            whatsapp=(
                "[DRAF] Cek fakta: konten yang beredar berasal dari "
                f"{utama.url} yang diunggah {utama.tanggal_unggah:%d/%m/%Y}. "
                "Narasi yang beredar tidak sesuai dengan konteks aslinya."
                if utama.tanggal_unggah else
                f"[DRAF] Cek fakta: konten yang beredar berasal dari {utama.url}."
            ),
        ),
        perlu_eskalasi=False,
        waktu_proses_detik=round(time.perf_counter() - mulai, 3),
    )


@app.post("/verifikasi/{claim_id}", response_model=HasilVerifikasi, tags=["verifikasi"])
def verifikasi(claim_id: str):
    k = _ambil_klaim(claim_id)
    if REPO.ambil_pencarian(claim_id) is None:
        raise HTTPException(400, "Jalankan /cari dulu untuk klaim ini")
    pencarian = REPO.ambil_pencarian(claim_id)[0]
    hasil = jalankan_verifikasi(k, pencarian)
    return REPO.simpan_verifikasi(hasil, aktor="api")


@app.get("/verifikasi/{claim_id}", response_model=HasilVerifikasi, tags=["verifikasi"])
def ambil_verifikasi(claim_id: str):
    hasil = REPO.ambil_verifikasi(claim_id)
    if hasil is None:
        raise HTTPException(404, "Belum diverifikasi")
    return hasil


@app.patch("/verifikasi/{claim_id}/persetujuan", response_model=HasilVerifikasi, tags=["persetujuan"])
def putuskan(claim_id: str, req: PermintaanPersetujuan):
    """Petugas menyetujui atau menolak draf klarifikasi."""
    _ambil_klaim(claim_id)
    try:
        return REPO.setujui(claim_id, req.keputusan, req.petugas, req.catatan)
    except TidakDitemukan as e:
        raise HTTPException(404, str(e))
    except TidakBoleh as e:
        raise HTTPException(409, str(e))


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
    return HasilPipeline(klaim=k, pencarian=pencarian, verifikasi=REPO.simpan_verifikasi(hasil, aktor="api"))


# ---------- Bukti publik & statistik ----------

@app.get("/bukti/{claim_id}", tags=["publik"])
def bukti_publik(claim_id: str):
    """Proyeksi publik: tanpa catatan internal petugas dan tanpa audit trail."""
    lengkap = REPO.ambil_lengkap(claim_id)
    if lengkap is None:
        raise HTTPException(404, "Klaim tidak ditemukan")
    v = lengkap.verifikasi
    disetujui = bool(v and v.status_persetujuan == "disetujui")
    return {
        "claim_id": lengkap.klaim.claim_id,
        "teks_klaim": lengkap.klaim.teks_klaim,
        "jenis_media": lengkap.klaim.jenis_media,
        "media_url": lengkap.klaim.media_url,
        "tanggal_ditemukan": lengkap.klaim.tanggal_ditemukan,
        "status": v.status if v else None,
        "ringkasan": v.ringkasan if v else None,
        "perubahan": v.perubahan if v else [],
        "keyakinan": v.keyakinan if v else None,
        "metode": v.metode if v else [],
        "sumber_utama": v.sumber_utama if v else None,
        "bukti": [b.model_dump(mode="json") for b in (v.bukti if v else [])],
        "klarifikasi": v.draf_klarifikasi.model_dump() if (v and disetujui and v.draf_klarifikasi) else None,
        "disetujui": disetujui,
        "waktu_verifikasi": v.waktu_verifikasi if v else None,
        "waktu_persetujuan": v.waktu_persetujuan if v else None,
        "simulasi": True,
    }


@app.get("/statistik", tags=["publik"])
def statistik():
    return REPO.statistik()


@app.post("/seed", tags=["dev"])
def seed():
    """Reset data demo (dev). Matikan lewat IZINKAN_SEED=0."""
    if not config.IZINKAN_SEED:
        raise HTTPException(403, "Seed dimatikan")
    jumlah = seed_ulang(REPO)
    return {"dimuat": jumlah, "waktu": datetime.now().isoformat()}