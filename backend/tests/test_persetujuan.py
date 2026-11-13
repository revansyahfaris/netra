"""Tes alur persetujuan lewat API: approve, tolak, transisi ilegal, bukti publik."""

import pytest
from fastapi.testclient import TestClient

import config
import store
from store import Repo
from store.seed import muat_klaim


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    store.reset_engine()
    import main as main_mod

    main_mod.REPO = Repo(store.db.get_session_factory())
    store.init_db()
    muat_klaim(main_mod.REPO)
    with TestClient(main_mod.app) as c:
        yield c


def jalankan(client, claim_id):
    r = client.post(f"/pipeline/{claim_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_pipeline_formal_menunggu_persetujuan(client):
    hasil = jalankan(client, "c002")
    assert hasil["verifikasi"]["status"] == "terbukti_diubah"
    assert hasil["verifikasi"]["status_persetujuan"] == "menunggu"
    assert hasil["verifikasi"]["bukti"], "paket bukti tidak boleh kosong"
    detail = client.get("/klaim/c002").json()
    assert detail["klaim"]["status_pipeline"] == "menunggu_persetujuan"
    assert detail["riwayat"]


def test_setujui_lalu_tampil_di_bukti_publik(client):
    jalankan(client, "c002")
    r = client.patch("/verifikasi/c002/persetujuan",
                     json={"keputusan": "disetujui", "petugas": "Petugas Demo", "catatan": "Bukti lengkap"})
    assert r.status_code == 200, r.text
    assert r.json()["status_persetujuan"] == "disetujui"

    publik = client.get("/bukti/c002").json()
    assert publik["disetujui"] is True
    assert publik["klarifikasi"] is not None
    assert "catatan_petugas" not in publik          # catatan internal tidak bocor
    assert "riwayat" not in publik

    detail = client.get("/klaim/c002").json()
    assert detail["klaim"]["status_pipeline"] == "disetujui"
    aksi = [r["aksi"] for r in detail["riwayat"]]
    assert "persetujuan_disetujui" in aksi


def test_tidak_bisa_setujui_dua_kali(client):
    jalankan(client, "c002")
    body = {"keputusan": "disetujui", "petugas": "Petugas Demo"}
    assert client.patch("/verifikasi/c002/persetujuan", json=body).status_code == 200
    r = client.patch("/verifikasi/c002/persetujuan", json=body)
    assert r.status_code == 409


def test_tolak_wajib_catatan(client):
    jalankan(client, "c002")
    r = client.patch("/verifikasi/c002/persetujuan",
                     json={"keputusan": "ditolak", "petugas": "Petugas Demo"})
    assert r.status_code == 409
    r = client.patch("/verifikasi/c002/persetujuan",
                     json={"keputusan": "ditolak", "petugas": "Petugas Demo", "catatan": "Sumber belum cukup"})
    assert r.status_code == 200
    assert client.get("/klaim/c002").json()["klaim"]["status_pipeline"] == "ditolak"


def test_worst_case_dieskalasi_bukan_disetujui(client):
    hasil = jalankan(client, "c001b")
    assert hasil["verifikasi"]["status"] == "belum_bisa_diverifikasi"
    assert hasil["verifikasi"]["perlu_eskalasi"] is True
    r = client.patch("/verifikasi/c001b/persetujuan",
                     json={"keputusan": "disetujui", "petugas": "Petugas Demo"})
    assert r.status_code == 409
    assert client.get("/klaim/c001b").json()["klaim"]["status_pipeline"] == "diverifikasi"


def test_tanpa_kandidat_tidak_ditemukan(client):
    hasil = jalankan(client, "c004")
    assert hasil["verifikasi"]["status"] == "tidak_ditemukan"
    assert hasil["verifikasi"]["perlu_eskalasi"] is True


def test_statistik_dan_seed(client):
    jalankan(client, "c002")
    s = client.get("/statistik").json()
    assert s["total_klaim"] >= 5
    assert s["menunggu_persetujuan"] >= 1
    assert client.post("/seed").status_code == 200
    assert client.get("/statistik").json()["total_klaim"] >= 5