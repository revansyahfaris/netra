"""API Netra: penghubung semua modul.

Jalankan dari folder backend:
    uvicorn main:app --reload
Lalu buka http://localhost:8000/docs

Alur: POST /prioritas -> GET /antrean -> POST /cari/{id} -> POST /verifikasi/{id}
      -> PATCH /verifikasi/{id}/persetujuan -> GET /bukti/{id}
Atau sekaligus: POST /pipeline/{id}
"""

import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import ai
import config
import media_publik
from store.db import mode as db_mode
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
from search import KonteksSinyal, cari_sumber
from store import (
    Repo,
    TautanBukti,
    TidakBoleh,
    TidakDitemukan,
    get_repo,
    seed_kalau_kosong,
    seed_ulang,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# httpx mencetak URL lengkap di level INFO (termasuk api_key SerpAPI), jadi dinaikkan ke WARNING
logging.getLogger("httpx").setLevel(logging.WARNING)
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
        "stt": "aktif" if config.stt_aktif() else "nonaktif",
        "pipeline_ai": config.PIPELINE_AI,
        "jit_tier2": config.JIT_TIER2,
        "media_publik": media_publik.aktif(),
        "database": db_mode(),
    }


@app.get("/media-sementara/{token}", tags=["publik"])
def ambil_media_sementara(token: str):
    """Layani keyframe lokal sementara bertanda tangan HMAC untuk Google Lens."""
    try:
        path, mime = media_publik.buka_token(token)
    except media_publik.TokenTidakSah as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, media_type=mime)


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


def _siapkan_konteks_sinyal(klaim: Klaim) -> tuple[KonteksSinyal | None, ai.SinyalKonten | None]:
    """Jalankan Tahap 1 sebelum pencarian saat mode AI aktif, sekaligus terbitkan URL keyframe."""
    if not config.PIPELINE_AI:
        return None, None
    sumber_eksternal = bool(
        config.search_aktif() or config.llm_aktif() or config.stt_aktif()
    )
    if not sumber_eksternal or klaim.jenis_media == "teks" or not klaim.media_url:
        return None, None
    if ai.adalah_url_placeholder(str(klaim.media_url)):
        return None, None

    sinyal = ai.ekstrak_sinyal_klaim(klaim, ambil_konten_eksternal=True)
    keyframe_urls = [
        url
        for kf in sinyal.keyframes_lokal[:5]
        if (url := media_publik.terbitkan_url(Path(kf))) is not None
    ]
    konteks = KonteksSinyal(
        stt_teks=sinyal.stt_teks,
        ocr_teks=list(sinyal.ocr.teks_unik),
        watermark=list(sinyal.ocr.watermark_terdeteksi),
        keyframe_urls=keyframe_urls,
    )
    return konteks, sinyal


def _jalankan_pencarian_internal(
    klaim: Klaim,
    url_manual: list[str] | None = None,
) -> tuple[HasilPencarian, dict, ai.SinyalKonten | None]:
    manual = list(url_manual or [])
    konteks, sinyal = _siapkan_konteks_sinyal(klaim)
    hasil, proses = cari_sumber(klaim, manual, konteks=konteks)
    if sinyal is not None:
        proses["sinyal_klaim"] = sinyal.model_dump(mode="json")
        if konteks and konteks.keyframe_urls:
            proses["jumlah_keyframe_lens"] = len(konteks.keyframe_urls)
    hasil = hasil.model_copy(update={"mode": proses.get("mode", "demo")})
    tersimpan = REPO.simpan_pencarian(hasil, proses, aktor="api")
    return tersimpan, proses, sinyal


@app.post("/cari/{claim_id}", response_model=HasilPencarian, tags=["pencarian"])
def cari(claim_id: str, req: PermintaanCari | None = None):
    """Cari kandidat sumber asli, lalu urutkan dari yang paling mungkin asli."""
    k = _ambil_klaim(claim_id)
    hasil, _, _ = _jalankan_pencarian_internal(k, (req.url_manual if req else []))
    return hasil


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

def _verifikasi_deterministik(klaim: Klaim, pencarian: HasilPencarian) -> HasilVerifikasi:
    """Fallback deterministik saat `PIPELINE_AI=0` atau API LLM tidak dikonfigurasi.

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
            bukti=[
                Bukti(
                    jenis="metadata",
                    url=k.url,
                    cuplikan=k.cuplikan,
                    teks_sumber=k.judul or None,
                    catatan=(
                        f"Kandidat skor {k.skor or 0:.2f}, diunggah "
                        f"{k.tanggal_unggah:%d %b %Y} oleh sumber {k.jenis_sumber}"
                        + (" dan berwatermark" if k.ada_watermark else "")
                    ),
                )
                for k in kandidat
            ],
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
            kartu="Konten ini bukan kejadian baru. Sumber asli lebih awal dan konteksnya berbeda.",
            pendek="Video/klaim ini sudah pernah beredar sebelumnya dengan konteks berbeda.",
            whatsapp=(
                "Cek fakta: konten yang beredar berasal dari "
                f"{utama.url} yang diunggah {utama.tanggal_unggah:%d/%m/%Y}. "
                "Narasi yang beredar tidak sesuai dengan konteks aslinya."
                if utama.tanggal_unggah else
                f"Cek fakta: konten yang beredar berasal dari {utama.url}."
            ),
        ),
        perlu_eskalasi=False,
        waktu_proses_detik=round(time.perf_counter() - mulai, 3),
    )


def _muat_sinyal_dari_proses(proses: dict | None) -> ai.SinyalKonten | None:
    mentah = (proses or {}).get("sinyal_klaim")
    if not isinstance(mentah, dict):
        return None
    try:
        return ai.SinyalKonten.model_validate(mentah)
    except Exception:
        return None


def jalankan_verifikasi_lengkap(
    klaim: Klaim,
    pencarian: HasilPencarian,
    *,
    proses: dict | None = None,
    sinyal_klaim_awal: ai.SinyalKonten | None = None,
) -> tuple[HasilVerifikasi, list[TautanBukti] | None]:
    """Jalankan pipeline AI penuh (Tahap 1-5) atau fallback deterministik jika kunci/flag nonaktif."""
    if not config.PIPELINE_AI or not config.llm_aktif():
        return _verifikasi_deterministik(klaim, pencarian), None

    mulai = time.perf_counter()
    sinyal_awal = sinyal_klaim_awal or _muat_sinyal_dari_proses(proses)
    ambil_eksternal = (pencarian.mode != "demo") or any(
        not ai.adalah_url_placeholder(str(k.url)) for k in pencarian.kandidat
    )
    hasil_tahap2 = ai.jalankan_tahap2(
        klaim,
        pencarian,
        ambil_konten_eksternal=ambil_eksternal,
        sinyal_klaim_awal=sinyal_awal,
        korroborasi=(proses or {}).get("korroborasi"),
    )
    hasil_v4 = ai.verifikasi_silang(klaim, hasil_tahap2)
    waktu = round(time.perf_counter() - mulai, 3)
    hasil_v5 = ai.susun_hasil_verifikasi(
        klaim,
        hasil_tahap2,
        hasil_v4,
        waktu_proses_detik=waktu,
        buat_draf_llm=True,
    )
    tautan = ai.kumpulkan_tautan_bukti(
        klaim,
        hasil_tahap2,
        hasil_v4,
        hasil_pencarian=pencarian,
    )
    return hasil_v5, tautan


def jalankan_verifikasi(klaim: Klaim, pencarian: HasilPencarian) -> HasilVerifikasi:
    """Wrapper kompatibel untuk pemanggil lama yang hanya mengharapkan `HasilVerifikasi`."""
    hasil, _ = jalankan_verifikasi_lengkap(klaim, pencarian)
    return hasil


@app.post("/verifikasi/{claim_id}", response_model=HasilVerifikasi, tags=["verifikasi"])
def verifikasi(claim_id: str):
    k = _ambil_klaim(claim_id)
    tersimpan = REPO.ambil_pencarian(claim_id)
    if tersimpan is None:
        raise HTTPException(400, "Jalankan /cari dulu untuk klaim ini")
    pencarian, proses = tersimpan
    hasil, tautan = jalankan_verifikasi_lengkap(k, pencarian, proses=proses)
    return REPO.simpan_verifikasi(hasil, aktor="api", tautan_bukti=tautan)


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


class StatusPekerjaanPipeline(BaseModel):
    claim_id: str
    status_kerja: Literal["belum_dijalankan", "antre", "berjalan", "selesai", "gagal"]
    tahap_saat_ini: str = "menunggu"
    dimulai_pada: datetime | None = None
    selesai_pada: datetime | None = None
    error: str | None = None
    mode_ai: bool = True


_LOCK_PEKERJAAN = threading.Lock()
_PEKERJAAN_PIPELINE: dict[str, StatusPekerjaanPipeline] = {}


def _set_status_kerja(claim_id: str, **updates) -> StatusPekerjaanPipeline:
    with _LOCK_PEKERJAAN:
        lama = _PEKERJAAN_PIPELINE.get(claim_id)
        if lama is None:
            baru = StatusPekerjaanPipeline(
                claim_id=claim_id,
                status_kerja=updates.pop("status_kerja", "antre"),
                mode_ai=updates.pop("mode_ai", config.PIPELINE_AI and config.llm_aktif()),
                **updates,
            )
        else:
            baru = lama.model_copy(update=updates)
        _PEKERJAAN_PIPELINE[claim_id] = baru
        return baru


def _jalankan_pipeline_sinkron(
    klaim: Klaim,
    url_manual: list[str] | None = None,
    *,
    saat_tahap: str | None = None,
) -> HasilPipeline:
    if saat_tahap:
        _set_status_kerja(klaim.claim_id, tahap_saat_ini="pencarian")
    pencarian, proses, sinyal = _jalankan_pencarian_internal(klaim, url_manual)
    if saat_tahap:
        _set_status_kerja(klaim.claim_id, tahap_saat_ini="verifikasi")
    hasil, tautan = jalankan_verifikasi_lengkap(
        klaim,
        pencarian,
        proses=proses,
        sinyal_klaim_awal=sinyal,
    )
    tersimpan = REPO.simpan_verifikasi(hasil, aktor="api", tautan_bukti=tautan)
    klaim_akhir = REPO.ambil_klaim(klaim.claim_id) or klaim
    return HasilPipeline(klaim=klaim_akhir, pencarian=pencarian, verifikasi=tersimpan)


def _jalankan_job_pipeline(claim_id: str, url_manual: list[str]) -> None:
    _set_status_kerja(
        claim_id,
        status_kerja="berjalan",
        tahap_saat_ini="pencarian",
        dimulai_pada=datetime.now(timezone.utc),
        selesai_pada=None,
        error=None,
    )
    try:
        klaim = REPO.ambil_klaim(claim_id)
        if klaim is None:
            raise TidakDitemukan(f"Klaim {claim_id} tidak ditemukan")
        _jalankan_pipeline_sinkron(klaim, url_manual, saat_tahap="ya")
        _set_status_kerja(
            claim_id,
            status_kerja="selesai",
            tahap_saat_ini="selesai",
            selesai_pada=datetime.now(timezone.utc),
        )
    except Exception as e:
        log.exception("Job latar belakang pipeline gagal (%s)", claim_id)
        _set_status_kerja(
            claim_id,
            status_kerja="gagal",
            tahap_saat_ini="gagal",
            selesai_pada=datetime.now(timezone.utc),
            error=str(e)[:300],
        )


@app.post("/pipeline/{claim_id}", response_model=HasilPipeline, tags=["pipeline"])
def pipeline(claim_id: str, req: PermintaanCari | None = None):
    """Cari sumber lalu verifikasi dalam satu panggilan sinkron."""
    k = _ambil_klaim(claim_id)
    return _jalankan_pipeline_sinkron(k, (req.url_manual if req else []))


@app.post(
    "/pipeline/{claim_id}/antre",
    response_model=StatusPekerjaanPipeline,
    status_code=202,
    tags=["pipeline"],
)
def antre_pipeline(
    claim_id: str,
    background_tasks: BackgroundTasks,
    req: PermintaanCari | None = None,
):
    """Jadwalkan pipeline penuh di latar belakang dan segera kembalikan status antrean."""
    _ambil_klaim(claim_id)
    with _LOCK_PEKERJAAN:
        aktif = _PEKERJAAN_PIPELINE.get(claim_id)
        if aktif and aktif.status_kerja in ("antre", "berjalan"):
            return aktif
    status_awal = _set_status_kerja(
        claim_id,
        status_kerja="antre",
        tahap_saat_ini="menunggu",
        dimulai_pada=None,
        selesai_pada=None,
        error=None,
        mode_ai=config.PIPELINE_AI and config.llm_aktif(),
    )
    background_tasks.add_task(
        _jalankan_job_pipeline,
        claim_id,
        list(req.url_manual) if req else [],
    )
    return status_awal


@app.get(
    "/pipeline/{claim_id}/status",
    response_model=StatusPekerjaanPipeline,
    tags=["pipeline"],
)
def status_pipeline_kerja(claim_id: str):
    """Pantau status pekerjaan pipeline latar belakang atau hasil yang sudah tersimpan."""
    lengkap = REPO.ambil_lengkap(claim_id)
    if lengkap is None:
        raise HTTPException(404, "Klaim tidak ditemukan")
    with _LOCK_PEKERJAAN:
        job = _PEKERJAAN_PIPELINE.get(claim_id)
    if job is not None:
        return job
    if lengkap.verifikasi is not None:
        return StatusPekerjaanPipeline(
            claim_id=claim_id,
            status_kerja="selesai",
            tahap_saat_ini="selesai",
            selesai_pada=lengkap.verifikasi.waktu_verifikasi,
            mode_ai=config.PIPELINE_AI and config.llm_aktif(),
        )
    if lengkap.pencarian is not None:
        return StatusPekerjaanPipeline(
            claim_id=claim_id,
            status_kerja="selesai",
            tahap_saat_ini="pencarian",
            selesai_pada=lengkap.pencarian.diperbarui,
            mode_ai=config.PIPELINE_AI and config.llm_aktif(),
        )
    return StatusPekerjaanPipeline(
        claim_id=claim_id,
        status_kerja="belum_dijalankan",
        tahap_saat_ini="menunggu",
        mode_ai=config.PIPELINE_AI and config.llm_aktif(),
    )


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
    with _LOCK_PEKERJAAN:
        _PEKERJAAN_PIPELINE.clear()
    jumlah = seed_ulang(REPO)
    return {"dimuat": jumlah, "waktu": datetime.now().isoformat()}