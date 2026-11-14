"""Perbaikan menjelang penjurian: hasil Lens yang hanya mirip gambar, dan pengaman biaya link publik."""

from fastapi.testclient import TestClient

import config
from search import ranking
from search.models import Temuan, relevansi_judul

KLAIM = "41 Ton Emas ditemukan TNI dari Buke Asing dan 13 KKB tertangkap"


def _lens(url, judul, kemiripan=0.65, jenis="media"):
    t = Temuan(url=url, metode="keyword", kemiripan=kemiripan, jenis_sumber=jenis, judul=judul)
    t.dari_lens = True
    t.kemiripan_teks = relevansi_judul(KLAIM, judul)
    return t


def test_relevansi_judul_membedakan_berita_nyambung():
    assert relevansi_judul(KLAIM, "TNI Temukan 41 Ton Emas Ilegal dari Warga Negara Asing") >= 0.5
    assert relevansi_judul(KLAIM, "Satgas Operasi Pengamanan Perbatasan Maphilindo 2017") < 0.25


def test_foto_mirip_tapi_beda_berita_tidak_jadi_juara():
    nyambung = Temuan(
        url="https://turnbackhoax.id/emas", metode="keyword", kemiripan=0.70, jenis_sumber="media",
        judul="[SALAH] TNI Temukan 41 Ton Emas Ilegal dari Warga Negara Asing",
    )
    tak_nyambung = [
        _lens(f"https://media{i}.id/foto", "Satgas Operasi Pengamanan Perbatasan Maphilindo 2017")
        for i in range(4)
    ]
    hasil = ranking.peringkat(ranking.gabung_duplikat([nyambung, *tak_nyambung]))
    assert hasil[0].url == "https://turnbackhoax.id/emas"
    for t in hasil[1:]:
        assert ranking.hanya_visual(t)
        assert "korroborasi" not in t.rincian_skor
        assert t.rincian_skor["kemiripan"] <= ranking.MAKS_KEMIRIPAN_VISUAL
        assert t.skor < hasil[0].skor


def test_hasil_lens_yang_nyambung_tetap_dihitung_penuh():
    t = _lens("https://kompas.id/emas", "TNI amankan 41 ton emas dari warga asing")
    assert not ranking.hanya_visual(t)


def test_batas_proses_harian_dan_health(monkeypatch):
    import main

    monkeypatch.setattr(config, "BATAS_PROSES_HARIAN", 1)
    monkeypatch.setattr(config, "JEDA_PROSES_ULANG_MENIT", 0)
    monkeypatch.setattr(config, "llm_aktif", lambda: True)
    main._KUOTA.update(tanggal=None, jumlah=0)
    main._TERAKHIR_DIPROSES.clear()

    main._pakai_kuota("a")
    try:
        main._pakai_kuota("b")
        assert False, "seharusnya ditolak"
    except main.HTTPException as e:
        assert e.status_code == 429

    c = TestClient(main.app)
    h = c.get("/health").json()
    assert h["batas_proses_harian"] == 1
    assert h["sisa_proses_hari_ini"] == 0
    assert "seed_diizinkan" in h


def test_jeda_proses_ulang(monkeypatch):
    import main

    monkeypatch.setattr(config, "BATAS_PROSES_HARIAN", 0)
    monkeypatch.setattr(config, "JEDA_PROSES_ULANG_MENIT", 10)
    monkeypatch.setattr(config, "search_aktif", lambda: True)
    main._TERAKHIR_DIPROSES.clear()
    main._pakai_kuota("x")
    try:
        main._pakai_kuota("x")
        assert False
    except main.HTTPException as e:
        assert e.status_code == 429 and "menit" in e.detail
    main._pakai_kuota("y")  # klaim lain tetap boleh


def test_mode_demo_tidak_kena_kuota(monkeypatch):
    import main

    monkeypatch.setattr(config, "BATAS_PROSES_HARIAN", 1)
    monkeypatch.setattr(config, "llm_aktif", lambda: False)
    monkeypatch.setattr(config, "search_aktif", lambda: False)
    main._KUOTA.update(tanggal=None, jumlah=5)
    main._pakai_kuota("z")  # tidak memanggil API berbayar, jadi tidak dibatasi
