"""Tes modul prioritas & pencari. Jalankan dari folder backend: pytest -q"""

import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from schemas import Klaim
from priority import hitung_prioritas
from priority.classifier import klasifikasi_keyword
from search import dates, frames, ranking, sources
from search.models import Temuan, kemiripan_teks
from search.queries import _fallback

SEKARANG = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def klaim(**kw):
    dasar = dict(claim_id="t", teks_klaim="x", jenis_media="teks", tanggal_ditemukan=SEKARANG)
    return Klaim(**{**dasar, **kw})


# ---------- Prioritas ----------

def test_keyword_pimpinan_lebih_sensitif_dari_umum():
    assert klasifikasi_keyword("Kasad disebut bilang sesuatu").label_topik == "pimpinan"
    assert klasifikasi_keyword("Pendaftaran bintara dibuka").label_topik == "umum"


def test_viral_cepat_dan_sensitif_jadi_tinggi():
    k = hitung_prioritas(klaim(teks_klaim="Kasad ancam bubarkan warga", laju_sebar=1500,
                               pengikut_pengunggah=200_000), SEKARANG)
    assert k.level == "tinggi" and k.skor_prioritas >= 0.65 and k.alasan


def test_klaim_lama_dan_sepi_jadi_rendah():
    k = hitung_prioritas(klaim(teks_klaim="Kegiatan bakti sosial", laju_sebar=2,
                               tanggal_ditemukan=SEKARANG - timedelta(days=5)), SEKARANG)
    assert k.level == "rendah"


# ---------- Query, sumber, tanggal ----------

def test_fallback_query_mengambil_kutipan():
    q = _fallback("Kasad disebut menyatakan 'TNI siap ambil alih pemerintahan sipil'")
    assert q["kutipan"] == ["TNI siap ambil alih pemerintahan sipil"]
    assert q["keyword"]


def test_jenis_sumber():
    assert sources.jenis_sumber("https://www.tniad.mil.id/berita") == "resmi"
    assert sources.jenis_sumber("https://news.detik.com/x") == "media"
    assert sources.jenis_sumber("https://www.youtube.com/watch?v=1", "Dispenad") == "resmi"
    assert sources.jenis_sumber("https://www.tiktok.com/@a/video/1") == "pribadi"
    assert sources.perkiraan_watermark("https://www.tiktok.com/@a/video/1") is True


@pytest.mark.parametrize("teks,tahun", [("20190821", 2019), ("Aug 21, 2019", 2019), ("21 Agu 2019", 2019),
                                        ("2019-08-21T10:00", 2019), ("5 years ago", 2021)])
def test_parse_tanggal(teks, tahun):
    assert dates.parse(teks, SEKARANG).year == tahun


def test_kemiripan_kutipan_persis():
    assert kemiripan_teks("siap ambil alih", "Ia berkata: siap ambil alih kota", kutipan=True) == 0.95


# ---------- Peringkat ----------

def test_sumber_tertua_resmi_tajam_menang():
    tgl = lambda y: datetime(y, 1, 1, tzinfo=timezone.utc)
    t = [
        Temuan("https://tiktok.com/v", "frame_match", 0.97, "pribadi", tanggal_unggah=tgl(2026), resolusi=480, ada_watermark=True),
        Temuan("https://youtube.com/asli", "frame_match", 0.9, "media", tanggal_unggah=tgl(2019), resolusi=1080, ada_watermark=False),
        Temuan("https://x.com/tidak-relevan", "keyword", 0.1),
    ]
    hasil = ranking.peringkat(t)
    assert hasil[0].url == "https://youtube.com/asli"
    assert len(hasil) == 2  # kemiripan < 0.3 dibuang


def test_gabung_duplikat():
    a = Temuan("https://a.com/x", "keyword", 0.5, resolusi=720)
    b = Temuan("https://a.com/x/", "frame_match", 0.9)
    (g,) = ranking.gabung_duplikat([a, b])
    assert g.kemiripan == 0.9 and g.resolusi == 720 and g.metode == "frame_match"


# ---------- Frame & audio (pakai video sintetis) ----------

butuh_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg tidak ada")


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    d = tmp_path_factory.mktemp("vid")
    asli, viral, lain = d / "asli.mp4", d / "viral.mp4", d / "lain.mp4"
    # Video "asli": 30 detik, gambar terus berubah (zoom fraktal) + audio dengan volume naik-turun
    _ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=10", "-t", "30",
            "-f", "lavfi", "-i", "aevalsrc='sin(440*2*PI*t)*abs(sin(0.7*t)*sin(0.23*t*t))':s=8000:d=30",
            "-shortest", str(asli))
    # Video "viral": potongan detik 10-20, resolusi turun, ada kotak watermark
    _ffmpeg("-ss", "10", "-t", "10", "-i", str(asli),
            "-vf", "scale=480:-2,drawbox=x=10:y=10:w=80:h=30:color=white@0.8:t=fill", str(viral))
    # Video tidak terkait
    _ffmpeg("-f", "lavfi", "-i", "life=size=640x360:rate=10:mold=10:ratio=0.3", "-t", "15",
            "-f", "lavfi", "-i", "anoisesrc=d=15:a=0.3", "-shortest", str(lain))
    return asli, viral, lain


@butuh_ffmpeg
def test_frame_match_menemukan_potongan(video):
    asli, viral, lain = video
    cache = {}
    cocok = frames.bandingkan(str(viral), str(asli), cache)
    beda = frames.bandingkan(str(viral), str(lain), cache)
    assert cocok.kemiripan > 0.7 > beda.kemiripan
    assert 8 <= cocok.detik_kandidat <= 18          # potongan berasal dari sekitar detik 10-20
    assert cocok.kecocokan_audio > 0.7
    assert (beda.kecocokan_audio or 0) < cocok.kecocokan_audio


@butuh_ffmpeg
def test_temuan_dari_video_lokal(video):
    asli, viral, _ = video
    t = frames.temuan_dari_video(str(viral), str(asli))
    assert t.metode == "frame_match" and t.resolusi == 720 and t.cuplikan


# ---------- Alur API lengkap sampai bukti publik ----------

def test_alur_persetujuan_dan_bukti():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        assert c.get("/bukti/c001").status_code == 404           # belum diverifikasi
        assert c.post("/pipeline/c001").status_code == 200
        antre = c.get("/persetujuan").json()
        assert [i["klaim"]["claim_id"] for i in antre] == ["c001"]
        assert c.get("/bukti/c001").status_code == 404           # belum disetujui

        r = c.post("/persetujuan/c001", json={"keputusan": "disetujui", "petugas": "Serka Budi",
                                              "draf_final": {"kartu": "Video 2019", "pendek": "Lama", "whatsapp": "Cek"}})
        assert r.status_code == 200 and r.json()["status"] == "disetujui"
        assert c.get("/persetujuan").json() == []
        b = c.get("/bukti/c001").json()
        assert b["klarifikasi"]["kartu"] == "Video 2019" and b["sumber_pendukung"]
        h = c.get("/bukti/c001/halaman")
        assert h.status_code == 200 and "Video 2019" in h.text and "<script" not in h.text

        c.post("/pipeline/c002")
        c.post("/persetujuan/c002", json={"keputusan": "ditolak", "petugas": "Serka Budi", "catatan": "sumber kurang"})
        assert c.get("/bukti/c002").status_code == 404
        assert len(c.get("/bukti").json()) == 1
        assert c.post("/persetujuan/c003", json={"keputusan": "disetujui", "petugas": "x"}).status_code == 400
