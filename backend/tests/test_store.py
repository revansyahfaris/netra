"""Tes penyimpanan: klaim, pencarian, verifikasi, audit, statistik."""

from datetime import datetime, timezone

import pytest

import config
import store
from schemas import (
    DrafKlarifikasi,
    HasilPencarian,
    HasilVerifikasi,
    KandidatSumber,
    Klaim,
)
from store import Repo
from store.seed import muat_klaim, seed_kalau_kosong, seed_ulang


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'tes.db'}")
    store.reset_engine()
    store.init_db()
    r = Repo(store.db.get_session_factory())
    yield r
    store.reset_engine()


def klaim(claim_id="t1", **kw):
    dasar = dict(
        claim_id=claim_id,
        teks_klaim="Konten contoh",
        jenis_media="teks",
        tanggal_ditemukan=datetime(2026, 11, 12, tzinfo=timezone.utc),
        skor_prioritas=0.8,
        level="tinggi",
    )
    return Klaim(**{**dasar, **kw})


def pencarian(claim_id, url="https://www.tniad.mil.id/berita", jenis="resmi"):
    return HasilPencarian(claim_id=claim_id, kandidat=[
        KandidatSumber(url=url, jenis_sumber=jenis, metode="keyword", kemiripan=0.8, skor=0.7,
                       judul="Siaran pers", uploader="Dispenad",
                       rincian_skor={"kemiripan": 0.8, "tanggal": 1.0})
    ])


def verifikasi(claim_id, status="terbukti_diubah"):
    return HasilVerifikasi(
        claim_id=claim_id,
        status=status,
        perlu_eskalasi=status != "terbukti_diubah",
        draf_klarifikasi=DrafKlarifikasi(kartu="k", pendek="p", whatsapp="w") if status == "terbukti_diubah" else None,
    )


def test_simpan_dan_ambil_klaim(repo):
    k = repo.simpan_klaim(klaim())
    assert repo.ambil_klaim("t1").teks_klaim == k.teks_klaim
    assert repo.ambil_klaim("tidak-ada") is None


def test_status_tidak_turun_saat_klaim_dikirim_ulang(repo):
    repo.simpan_klaim(klaim())
    repo.simpan_verifikasi(verifikasi("t1"))
    assert repo.ambil_klaim("t1").status_pipeline == "menunggu_persetujuan"
    repo.simpan_klaim(klaim())  # kirim ulang dari sistem deteksi
    assert repo.ambil_klaim("t1").status_pipeline == "menunggu_persetujuan"


def test_antrean_terurut_skor(repo):
    repo.simpan_klaim(klaim("rendah", skor_prioritas=0.8))
    repo.simpan_klaim(klaim("tinggi", skor_prioritas=0.9))
    repo.simpan_klaim(klaim("sedang", skor_prioritas=0.85))
    assert [k.claim_id for k in repo.daftar_klaim()] == ["tinggi", "sedang", "rendah"]


def test_pencarian_memajukan_status(repo):
    repo.simpan_klaim(klaim())
    repo.simpan_pencarian(pencarian("t1"), {"mode": "demo"})
    assert repo.ambil_klaim("t1").status_pipeline == "dicari"
    hasil, proses = repo.ambil_pencarian("t1")
    assert hasil.kandidat[0].judul == "Siaran pers"
    assert proses["mode"] == "demo"


def test_verifikasi_terbukti_masuk_persetujuan(repo):
    repo.simpan_klaim(klaim())
    repo.simpan_verifikasi(verifikasi("t1"))
    assert repo.ambil_klaim("t1").status_pipeline == "menunggu_persetujuan"


def test_verifikasi_eskalasi_tidak_masuk_persetujuan(repo):
    repo.simpan_klaim(klaim())
    repo.simpan_verifikasi(verifikasi("t1", "belum_bisa_diverifikasi"))
    assert repo.ambil_klaim("t1").status_pipeline == "diverifikasi"
    with pytest.raises(store.TidakBoleh):
        repo.setujui("t1", "disetujui", "Petugas A")


def test_data_bertahan_di_repo_baru(repo, tmp_path):
    repo.simpan_klaim(klaim())
    repo2 = Repo(store.db.get_session_factory())
    assert repo2.ambil_klaim("t1") is not None


def test_statistik(repo):
    repo.simpan_klaim(klaim("a"))
    repo.simpan_klaim(klaim("b"))
    repo.simpan_verifikasi(verifikasi("a"))
    s = repo.statistik()
    assert s["total_klaim"] == 2
    assert s["per_status_pipeline"]["menunggu_persetujuan"] == 1
    assert s["per_status_verifikasi"]["terbukti_diubah"] == 1


def test_seed_idempoten(repo):
    jumlah = seed_kalau_kosong(repo)
    assert jumlah >= 4
    assert seed_kalau_kosong(repo) == 0          # sudah ada isinya
    assert len(muat_klaim(repo)) == jumlah       # upsert, bukan duplikat
    assert len(repo.daftar_klaim()) == jumlah
    assert seed_ulang(repo) == jumlah