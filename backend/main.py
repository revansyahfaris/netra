"""API Netra: penghubung semua modul.

Jalankan dari folder backend:
    uvicorn main:app --reload
Lalu buka http://localhost:8000/docs

Alur: POST /prioritas -> GET /antrean -> POST /cari/{id} -> POST /verifikasi/{id}
      -> GET /persetujuan -> POST /persetujuan/{id} -> GET /bukti/{id}
Atau sekaligus: POST /pipeline/{id}
"""

import html
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import config
from priority import hitung_prioritas
from schemas import (
    BuktiPublik, DrafKlarifikasi, HasilPencarian, HasilVerifikasi, KeputusanPetugas, Klaim, Persetujuan,
)
from search import cari_sumber

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Penyimpanan sementara di memori (hilang saat server restart)
KLAIM: dict[str, Klaim] = {}
PENCARIAN: dict[str, HasilPencarian] = {}
PROSES_PENCARIAN: dict[str, dict] = {}
VERIFIKASI: dict[str, HasilVerifikasi] = {}
PERSETUJUAN: dict[str, Persetujuan] = {}


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
    Input: klaim + kandidat terurut. Output: HasilVerifikasi.
    Panggil LLM dengan llm.tanya_json(prompt, model=config.GEMINI_MODEL_VERIFIKASI)."""
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


def simpan_verifikasi(hasil: HasilVerifikasi):
    """Simpan hasil verifikasi dan masukkan ke antrean persetujuan (keputusan lama direset)."""
    VERIFIKASI[hasil.claim_id] = hasil
    PERSETUJUAN[hasil.claim_id] = Persetujuan(claim_id=hasil.claim_id)


@app.post("/verifikasi/{claim_id}", response_model=HasilVerifikasi, tags=["verifikasi"])
def verifikasi(claim_id: str):
    k = _ambil_klaim(claim_id)
    if claim_id not in PENCARIAN:
        raise HTTPException(400, "Jalankan /cari dulu untuk klaim ini")
    hasil = jalankan_verifikasi(k, PENCARIAN[claim_id])
    simpan_verifikasi(hasil)
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
    simpan_verifikasi(hasil)
    return HasilPipeline(klaim=k, pencarian=pencarian, verifikasi=hasil)


# ---------- Persetujuan petugas ----------

class ItemPersetujuan(BaseModel):
    klaim: Klaim
    verifikasi: HasilVerifikasi
    persetujuan: Persetujuan


@app.get("/persetujuan", response_model=list[ItemPersetujuan], tags=["persetujuan"])
def antrean_persetujuan(status: str = "menunggu"):
    """Daftar klaim yang sudah diverifikasi. Filter status: menunggu / disetujui / ditolak / semua.
    Klaim yang perlu eskalasi dan berprioritas tinggi tampil paling atas."""
    item = [
        ItemPersetujuan(klaim=KLAIM[cid], verifikasi=VERIFIKASI[cid], persetujuan=p)
        for cid, p in PERSETUJUAN.items()
        if cid in KLAIM and cid in VERIFIKASI and (status == "semua" or p.status == status)
    ]
    return sorted(item, key=lambda i: (not i.verifikasi.perlu_eskalasi, -(i.klaim.skor_prioritas or 0)))


@app.post("/persetujuan/{claim_id}", response_model=Persetujuan, tags=["persetujuan"])
def putuskan(claim_id: str, keputusan: KeputusanPetugas):
    """Petugas menyetujui atau menolak. Draf boleh diedit lewat draf_final."""
    if claim_id not in VERIFIKASI:
        raise HTTPException(400, "Klaim belum diverifikasi")
    v = VERIFIKASI[claim_id]
    draf = keputusan.draf_final or v.draf_klarifikasi
    if keputusan.keputusan == "disetujui" and draf is None:
        raise HTTPException(400, "Tidak ada draf klarifikasi; isi draf_final sebelum menyetujui")
    p = Persetujuan(
        claim_id=claim_id,
        status=keputusan.keputusan,
        petugas=keputusan.petugas,
        catatan=keputusan.catatan,
        draf_final=draf if keputusan.keputusan == "disetujui" else None,
        waktu_keputusan=datetime.now(timezone.utc),
    )
    PERSETUJUAN[claim_id] = p
    return p


# ---------- Bukti publik ----------

def _bukti(claim_id: str) -> BuktiPublik:
    p = PERSETUJUAN.get(claim_id)
    if not p or p.status != "disetujui":
        raise HTTPException(404, "Bukti belum dipublikasikan")
    k, v = KLAIM[claim_id], VERIFIKASI[claim_id]
    pendukung = PENCARIAN[claim_id].kandidat[:3] if claim_id in PENCARIAN else []
    return BuktiPublik(
        claim_id=claim_id, teks_klaim=k.teks_klaim, status=v.status, perubahan=v.perubahan,
        sumber_utama=v.sumber_utama, sumber_pendukung=pendukung,
        klarifikasi=p.draf_final, disetujui_pada=p.waktu_keputusan,
    )


@app.get("/bukti", response_model=list[BuktiPublik], tags=["bukti publik"])
def daftar_bukti():
    return [_bukti(cid) for cid, p in PERSETUJUAN.items() if p.status == "disetujui"]


@app.get("/bukti/{claim_id}", response_model=BuktiPublik, tags=["bukti publik"])
def bukti(claim_id: str):
    return _bukti(claim_id)


LABEL_STATUS = {
    "terbukti_diubah": "Terbukti diubah",
    "tidak_ditemukan": "Sumber pendukung tidak ditemukan",
    "belum_bisa_diverifikasi": "Belum bisa diverifikasi",
}
LABEL_PERUBAHAN = {
    "dipotong": "Dipotong", "tanggal_berbeda": "Tanggal berbeda", "kutipan_tidak_ada": "Kutipan tidak ada di sumber asli",
    "konteks_berbeda": "Konteks berbeda", "lainnya": "Lainnya",
}


@app.get("/bukti/{claim_id}/halaman", response_class=HTMLResponse, tags=["bukti publik"])
def halaman_bukti(claim_id: str):
    """Halaman bukti publik siap dibagikan (tanpa perlu dashboard)."""
    b = _bukti(claim_id)
    e = html.escape
    perubahan = "".join(f"<li>{e(LABEL_PERUBAHAN.get(x, x))}</li>" for x in b.perubahan) or "<li>-</li>"
    sumber = "".join(
        f'<li><a href="{e(str(s.url))}" target="_blank" rel="noopener">{e(str(s.url))}</a>'
        f'<span>{e(s.jenis_sumber)} · {s.tanggal_unggah.date() if s.tanggal_unggah else "tanggal tidak diketahui"}'
        f'{" · menit " + e(s.cuplikan) if s.cuplikan and s.metode == "frame_match" else ""}</span></li>'
        for s in b.sumber_pendukung
    )
    return f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cek Fakta Netra · {e(b.claim_id)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:680px;margin:0 auto;padding:24px 16px;color:#1c1c1c;line-height:1.6}}
.tag{{display:inline-block;padding:2px 10px;border-radius:999px;background:#fdecea;color:#8a1c12;font-size:14px}}
.klaim{{border-left:3px solid #c9c9c9;padding:4px 12px;color:#555}}
.kartu{{background:#f3f6f4;border-radius:12px;padding:16px;margin:16px 0}}
li span{{display:block;color:#666;font-size:13px}} a{{color:#0b5c3b;word-break:break-all}}
footer{{color:#888;font-size:13px;margin-top:32px}}
</style></head><body>
<p class="tag">{e(LABEL_STATUS.get(b.status, b.status))}</p>
<h1>Cek fakta</h1>
<p class="klaim">{e(b.teks_klaim)}</p>
<div class="kartu"><strong>{e(b.klarifikasi.kartu)}</strong><p>{e(b.klarifikasi.pendek)}</p></div>
<h2>Apa yang diubah</h2><ul>{perubahan}</ul>
<h2>Sumber</h2><ul>{sumber or "<li>-</li>"}</ul>
<footer>Diverifikasi dengan Netra dan disetujui petugas pada {b.disetujui_pada:%d %b %Y %H.%M} UTC.</footer>
</body></html>"""
