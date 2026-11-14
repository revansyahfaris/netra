"""Status pipeline melaporkan tahap demi tahap untuk tampilan progres di dashboard."""

import time

from fastapi.testclient import TestClient

import main
import progres


def test_lapor_tanpa_pemantau_tidak_error():
    progres.lapor("apa_saja")  # tidak ada job yang memantau


def test_job_mencatat_riwayat_tahap_dan_waktu_total():
    c = TestClient(main.app)
    c.post("/seed")
    claim_id = c.get("/antrean").json()[0]["klaim"]["claim_id"]
    main._PEKERJAAN_PIPELINE.pop(claim_id, None)
    main._jalankan_job_pipeline(claim_id, [])
    st = c.get(f"/pipeline/{claim_id}/status").json()
    assert st["status_kerja"] == "selesai"
    tahap = [r["tahap"] for r in st["riwayat_tahap"]]
    assert tahap[0] == "mulai"
    assert "pencarian" in tahap
    v = c.get(f"/klaim/{claim_id}").json()["verifikasi"]
    assert v["waktu_proses_detik"] is not None


def test_catat_tahap_tidak_duplikat():
    cid = "uji-progres"
    main._set_status_kerja(cid, status_kerja="berjalan", tahap_saat_ini="mulai", riwayat_tahap=[])
    main._catat_tahap(cid, "pencarian")
    main._catat_tahap(cid, "pencarian")
    main._catat_tahap(cid, "verifikasi")
    st = main._PEKERJAAN_PIPELINE[cid]
    assert [r.tahap for r in st.riwayat_tahap] == ["pencarian", "verifikasi"]
    assert st.tahap_saat_ini == "verifikasi"
