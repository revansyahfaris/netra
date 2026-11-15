"""Penyamaran akun media sosial pribadi pada keluaran API."""

from fastapi.testclient import TestClient

import config
import privasi


def test_url_x_jadi_tanpa_nama_akun():
    s = "lihat https://x.com/akunpribadi/status/2117956103019631060?s=20 ya"
    assert privasi.samarkan_teks(s) == "lihat https://x.com/i/status/2117956103019631060 ya"
    assert privasi.samarkan_teks("https://twitter.com/abc_1/status/99") == "https://x.com/i/status/99"
    assert privasi.samarkan_teks("https://x.com/i/status/5") == "https://x.com/i/status/5"


def test_handle_disamarkan_tapi_email_dan_url_lain_tidak():
    assert privasi.samarkan_teks("kata @budi_99 dan @Ani") == "kata @akun dan @akun"
    assert privasi.samarkan_teks("surel tim@undip.ac.id") == "surel tim@undip.ac.id"
    assert privasi.samarkan_teks("https://www.tiktok.com/@akun.lama/video/1") == "https://www.tiktok.com/@akun.lama/video/1"


def test_uploader_pribadi_disamarkan_resmi_tidak():
    data = {"kandidat": [
        {"jenis_sumber": "pribadi", "uploader": "budi99", "url": "https://x.com/budi99/status/1"},
        {"jenis_sumber": "resmi", "uploader": "Puspen TNI", "url": "https://tni.mil.id/a"},
    ]}
    hasil = privasi.samarkan(data)
    assert hasil["kandidat"][0] == {"jenis_sumber": "pribadi", "uploader": "Akun pribadi",
                                    "url": "https://x.com/i/status/1"}
    assert hasil["kandidat"][1]["uploader"] == "Puspen TNI"
    assert data["kandidat"][0]["uploader"] == "budi99"  # data asli tidak diubah


def test_respons_api_disamarkan_dan_bisa_dimatikan(monkeypatch):
    import main

    c = TestClient(main.app)
    c.post("/seed")
    klaim = {
        "claim_id": "p-uji",
        "teks_klaim": "Video dari @akunpribadi soal aparat",
        "jenis_media": "video",
        "media_url": "https://x.com/akunpribadi/status/123",
        "tanggal_ditemukan": "2026-11-14T10:00:00",
        "sumber_masuk": "manual",
    }
    assert c.post("/prioritas", json=klaim).status_code == 200
    k = c.get("/klaim/p-uji").json()["klaim"]
    assert k["media_url"] == "https://x.com/i/status/123"
    assert k["teks_klaim"] == "Video dari @akun soal aparat"
    antre = {x["klaim"]["claim_id"]: x for x in c.get("/antrean?ringkas=true").json()}
    assert antre["p-uji"]["klaim"]["media_url"] == "https://x.com/i/status/123"

    monkeypatch.setattr(config, "SAMARKAN_AKUN", False)
    assert c.get("/klaim/p-uji").json()["klaim"]["media_url"] == "https://x.com/akunpribadi/status/123"
