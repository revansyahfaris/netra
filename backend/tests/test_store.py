"""Tes penyimpanan: klaim, pencarian, verifikasi, audit, statistik."""

from datetime import datetime, timezone

import pytest

import config
import store
from ai import HasilCariKorpus, doc_id_dari_url
from schemas import (
    Bukti,
    DrafKlarifikasi,
    HasilPencarian,
    HasilVerifikasi,
    KandidatSumber,
    Klaim,
)
from store import Repo, TautanBukti, tautan_dari_hasil_rag, tautan_dari_kandidat
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
    repo.simpan_klaim(klaim("c"))
    repo.simpan_verifikasi(verifikasi("a"))
    repo.simpan_verifikasi(verifikasi("b", "belum_bisa_diverifikasi"))
    repo.simpan_verifikasi(verifikasi("c", "tidak_ditemukan"))
    s = repo.statistik()
    assert s["total_klaim"] == 3
    assert s["per_status_pipeline"]["menunggu_persetujuan"] == 1
    assert s["per_status_verifikasi"]["terbukti_diubah"] == 1
    # Yang dieskalasi tidak boleh dihitung sebagai antrean persetujuan
    assert s["menunggu_persetujuan"] == 1
    assert s["perlu_eskalasi"] == 2


def test_seed_idempoten(repo):
    jumlah = seed_kalau_kosong(repo)
    assert jumlah >= 4
    assert seed_kalau_kosong(repo) == 0          # sudah ada isinya
    assert len(muat_klaim(repo)) == jumlah       # upsert, bukan duplikat
    assert len(repo.daftar_klaim()) == jumlah
    assert seed_ulang(repo) == jumlah


def test_simpan_dan_query_netra_klaim_bukti(repo):
    repo.simpan_klaim(klaim("k1"))
    repo.simpan_klaim(klaim("k2"))

    url_yt_pendek = "https://youtu.be/AbC123xyZ?si=share1"
    url_yt_panjang = "https://www.youtube.com/watch?v=AbC123xyZ&feature=share"
    rag_item_1 = HasilCariKorpus(
        chunk_id=11,
        doc_id=doc_id_dari_url(url_yt_pendek),
        judul="Latihan Gabungan 2021",
        url=url_yt_pendek,
        jenis_sumber="media",
        cakupan="temuan",
        jenis_konten="video",
        kutipan="Potongan pidato latihan 2021.",
        skor_kemiripan=0.72,
        metode_cari="vector",
    )
    rag_item_2 = HasilCariKorpus(
        chunk_id=12,
        doc_id=doc_id_dari_url(url_yt_pendek),
        judul="Latihan Gabungan 2021",
        url=url_yt_pendek,
        jenis_sumber="media",
        cakupan="temuan",
        jenis_konten="video",
        kutipan="Segmen lanjutan penjelasan komandan.",
        skor_kemiripan=0.89,
        metode_cari="vector",
    )
    kandidat_t1 = KandidatSumber(
        url="https://tniad.mil.id/rilis-resmi/?utm_source=ig",
        jenis_sumber="resmi",
        metode="frame_match",
        kemiripan=0.81,
        skor=0.81,
        cuplikan="01:12",
        judul="Siaran Pers Resmi",
    )

    # Duplikat chunk_id=11 harus menyisakan skor tertinggi, sementara chunk 11 & 12 tetap terpisah
    repo.simpan_bukti_klaim(
        "k1",
        [
            tautan_dari_hasil_rag(rag_item_1),
            tautan_dari_hasil_rag(rag_item_1.model_copy(update={"skor_kemiripan": 0.91})),
            tautan_dari_hasil_rag(rag_item_2, peran="acuan_utama"),
            tautan_dari_kandidat(kandidat_t1, peran="korroborasi"),
        ],
    )
    daftar = repo.daftar_bukti_klaim("k1")
    assert len(daftar) == 3
    assert daftar[0].skor == pytest.approx(0.91)
    assert [d.chunk_id for d in daftar] == [11, 12, None]
    assert daftar[2].doc_id == doc_id_dari_url("https://tniad.mil.id/rilis-resmi")

    # Tambah incremental (ganti=False) ke klaim k2 dengan URL varian -> query hoaks daur ulang ketemu k1 & k2
    repo.simpan_bukti_klaim(
        "k2",
        [TautanBukti(tier="tier1", metode="keyword", url=url_yt_panjang, skor=0.65)],
        ganti=False,
    )
    assert repo.klaim_memakai_dokumen(url_yt_pendek) == ["k1", "k2"]
    assert repo.klaim_memakai_dokumen(doc_id_dari_url(url_yt_panjang)) == ["k1", "k2"]

    with pytest.raises(store.TidakDitemukan):
        repo.simpan_bukti_klaim("tidak-ada", [])

    repo.hapus_semua()
    assert repo.daftar_bukti_klaim("k1") == []


def test_simpan_verifikasi_kelola_netra_klaim_bukti(repo):
    url_hoaks = "https://www.tiktok.com/@akun/video/777?is_from_webapp=1"
    url_asli = "https://www.tniad.mil.id/klarifikasi-resmi/?utm_source=x"
    repo.simpan_klaim(klaim("v1", media_url=url_hoaks))

    # 1. Backfill otomatis dari HasilVerifikasi mengabaikan media_url milik klaim viral sendiri
    hv = HasilVerifikasi(
        claim_id="v1",
        status="terbukti_diubah",
        sumber_utama=url_asli,
        keyakinan=0.88,
        metode=["frame_match"],
        bukti=[
            Bukti(jenis="metadata", url=url_asli, cuplikan="00:10", catatan="Sumber utama"),
            Bukti(jenis="frame", url=url_hoaks, cuplikan="00:10", catatan="Cuplikan viral"),
        ],
        draf_klarifikasi=DrafKlarifikasi(kartu="k", pendek="p", whatsapp="w"),
    )
    repo.simpan_verifikasi(hv)
    bukti_v1 = repo.daftar_bukti_klaim("v1")
    assert len(bukti_v1) == 1
    assert bukti_v1[0].doc_id == doc_id_dari_url(url_asli)
    assert bukti_v1[0].peran == "acuan_utama"

    # 2. Jika tautan kaya chunk_id sudah tersimpan, simpan_verifikasi tanpa tautan_bukti tidak menimpanya
    tautan_rag = TautanBukti(
        doc_id="dok_resmi_1",
        chunk_id=42,
        tier="tier2_rag",
        metode="vector",
        peran="acuan_utama",
        skor=0.95,
        url=url_asli,
    )
    repo.simpan_bukti_klaim("v1", [tautan_rag], ganti=True)
    repo.simpan_verifikasi(hv)
    assert [b.chunk_id for b in repo.daftar_bukti_klaim("v1")] == [42]

    # 3. Jika tautan_bukti diberikan eksplisit saat simpan_verifikasi, relasi diganti bersih
    tautan_baru = TautanBukti(tier="tier1", metode="ocr", peran="pembanding", skor=0.77, url="https://antaranews.com/berita/1")
    repo.simpan_verifikasi(hv, tautan_bukti=[tautan_baru])
    hasil_akhir = repo.daftar_bukti_klaim("v1")
    assert len(hasil_akhir) == 1
    assert hasil_akhir[0].doc_id == doc_id_dari_url("https://antaranews.com/berita/1")