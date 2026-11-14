"""Tes Tahap 5 (klarifikasi), hosting keyframe sementara, dan integrasi pipeline penuh di API."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import config
import media_publik
import store
from ai import (
    HasilCariKorpus,
    HasilOCR,
    HasilTahap2,
    HasilVerifikasiSilang,
    SinyalKonten,
    SinyalSumberAcuan,
    TemuanBukti,
    doc_id_dari_url,
    kumpulkan_tautan_bukti,
    susun_hasil_verifikasi,
)
from schemas import (
    HasilPencarian,
    HasilVerifikasi,
    KandidatSumber,
    Klaim,
)
from store import Repo
from store.seed import muat_klaim

WAKTU = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


def _klaim_vid() -> Klaim:
    return Klaim(
        claim_id="k_full_1",
        teks_klaim="Video viral pengerahan pasukan kemarin malam",
        jenis_media="video",
        media_url="https://example.com/viral/v.mp4",
        tanggal_ditemukan=WAKTU,
    )


def _hasil_tahap2_contoh(indikasi_buzzer: bool = False) -> HasilTahap2:
    return HasilTahap2(
        claim_id="k_full_1",
        jalur="tier1_dan_rag_ke_tahap4",
        siap_tahap4=True,
        alasan_routing="Kandidat frame match + rujukan RAG.",
        sinyal_klaim=SinyalKonten(
            claim_id="k_full_1",
            teks_klaim="Video viral pengerahan pasukan kemarin malam",
            jenis_media="video",
            ocr=HasilOCR(teks_unik=["LATIHAN GABUNGAN 2021"]),
        ),
        kandidat_bersih=[
            KandidatSumber(
                url="https://www.youtube.com/watch?v=ASLI2021&si=abc",
                jenis_sumber="media",
                metode="frame_match",
                kemiripan=0.92,
                skor=0.90,
                cuplikan="01:15",
                judul="Latihan Gabungan 2021 di Situbondo",
            )
        ],
        hasil_rag=[
            HasilCariKorpus(
                chunk_id=14,
                doc_id=doc_id_dari_url("https://tniad.mil.id/rilis-latgab-2021"),
                judul="Siaran Pers Latgab TNI 2021",
                tanggal_terbit="2021-08-18",
                url="https://tniad.mil.id/rilis-latgab-2021",
                jenis_sumber="resmi",
                cakupan="resmi",
                jenis_konten="teks",
                kutipan="Latihan dilaksanakan di Situbondo pada Agustus 2021.",
                skor_kemiripan=0.88,
                metode_cari="vector",
            )
        ],
        metode_terpakai=["frame_match", "rag", "ocr"],
        indikasi_buzzer=indikasi_buzzer,
    )


def test_tahap5_draf_klarifikasi_llm_fallback_dan_guardrail(monkeypatch):
    klaim = _klaim_vid()
    ht2 = _hasil_tahap2_contoh()
    v4 = HasilVerifikasiSilang(
        claim_id="k_full_1",
        jalur_tahap2="tier1_dan_rag_ke_tahap4",
        status="terbukti_diubah",
        perlu_eskalasi=False,
        keyakinan=0.91,
        sumber_utama_url="https://www.youtube.com/watch?v=ASLI2021&si=abc",
        sumber_utama_judul="Latihan Gabungan 2021 di Situbondo",
        sumber_utama_tanggal="2021-08-18",
        perubahan=["tanggal_berbeda", "dipotong"],
        ringkasan="Video adalah rekaman latihan tahun 2021 yang diberi narasi kejadian baru.",
        fakta_utama="Latihan Gabungan dilaksanakan 18 Agustus 2021 di Situbondo.",
        apa_yang_diubah="Potongan menit 01:15 diunggah ulang dengan klaim kejadian semalam.",
        bukti=[
            TemuanBukti(
                jenis="frame",
                url="https://www.youtube.com/watch?v=ASLI2021&si=abc",
                cuplikan="01:15",
                teks_viral="kejadian kemarin malam",
                teks_sumber="Latihan Gabungan 2021 di Situbondo",
                catatan="Cocok frame pada 01:15",
            )
        ],
        metode=["frame_match", "rag", "ocr"],
    )

    # 1. Mode LLM sukses menghasilkan 3 format draf
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr(
        "llm.tanya_json",
        lambda *a, **kw: {
            "kartu": "KLARIFIKASI: Video tersebut adalah rekaman latihan tahun 2021.",
            "pendek": "Video latihan Agustus 2021 di Situbondo dipotong dan dinarasikan ulang.",
            "whatsapp": "*[KLARIFIKASI]* Video berasal dari Latihan Gabungan 2021 (Situbondo).",
        },
    )
    res_llm = susun_hasil_verifikasi(klaim, ht2, v4, waktu_proses_detik=1.25)
    assert isinstance(res_llm, HasilVerifikasi)
    assert res_llm.status == "terbukti_diubah"
    assert res_llm.perlu_eskalasi is False
    assert res_llm.draf_klarifikasi is not None
    assert "2021" in res_llm.draf_klarifikasi.whatsapp
    assert res_llm.waktu_proses_detik == 1.25

    # 2. Fallback deterministik saat API key kosong
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    res_det = susun_hasil_verifikasi(klaim, ht2, v4)
    assert res_det.draf_klarifikasi is not None
    assert "ASLI2021" in res_det.draf_klarifikasi.whatsapp

    # 3. Guardrail Tahap 5 memaksa eskalasi bila keyakinan di bawah ambang atau perubahan kosong
    v4_lemah = v4.model_copy(update={"keyakinan": 0.42})
    ht2_buzzer = _hasil_tahap2_contoh(indikasi_buzzer=True)
    res_eskalasi = susun_hasil_verifikasi(klaim, ht2_buzzer, v4_lemah)
    assert res_eskalasi.status == "belum_bisa_diverifikasi"
    assert res_eskalasi.perlu_eskalasi is True
    assert res_eskalasi.draf_klarifikasi is None
    assert "akun pribadi" in (res_eskalasi.ringkasan or "").lower()

    # 4. Tautan bukti mempertahankan chunk_id RAG dan doc_id deterministik tanpa menyertakan media_url klaim
    tautan = kumpulkan_tautan_bukti(
        klaim,
        ht2,
        v4,
        hasil_pencarian=HasilPencarian(claim_id="k_full_1", kandidat=ht2.kandidat_bersih),
    )
    rag_links = [t for t in tautan if t.tier == "tier2_rag" and t.chunk_id == 14]
    assert len(rag_links) == 1
    assert all(t.url != str(klaim.media_url) for t in tautan)


def test_media_publik_token_dan_endpoint(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    kf = work / "kf.jpg"
    kf.write_bytes(b"\xff\xd8\xff\xe0JPEG-DATA")
    luar = tmp_path / "rahasia.jpg"
    luar.write_bytes(b"\xff\xd8\xff\xe0LUAR")

    monkeypatch.setattr(config, "WORK_DIR", work)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://tunnel.contoh.id")
    monkeypatch.setattr(config, "MEDIA_SECRET", "rahasia-uji")
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'media.db'}")
    monkeypatch.setattr(config, "SERPAPI_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")

    with pytest.raises(media_publik.TokenTidakSah):
        media_publik.buat_token(luar)

    url_pub = media_publik.terbitkan_url(kf, ttl_detik=120)
    assert url_pub and url_pub.startswith("https://tunnel.contoh.id/media-sementara/")
    token = url_pub.rsplit("/", 1)[-1]

    store.reset_engine()
    import main as main_mod

    main_mod.REPO = Repo(store.db.get_session_factory())
    store.init_db()
    with TestClient(main_mod.app) as client:
        ok = client.get(f"/media-sementara/{token}")
        assert ok.status_code == 200
        assert ok.content == b"\xff\xd8\xff\xe0JPEG-DATA"
        assert ok.headers["content-type"].startswith("image/jpeg")

        rusak = client.get(f"/media-sementara/{token[:-3]}zzz")
        assert rusak.status_code == 404


def test_pipeline_ai_penuh_sinkron_dan_latar_belakang(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    kf = work / "kf_klaim.jpg"
    kf.write_bytes(b"\xff\xd8\xff\xe0KF")

    monkeypatch.setattr(config, "WORK_DIR", work)
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'full.db'}")
    monkeypatch.setattr(config, "SERPAPI_KEY", "dummy-serp")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-gemini")
    monkeypatch.setattr(config, "STT_BASE_URL", "")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://api.contoh.id")
    monkeypatch.setattr(config, "MEDIA_SECRET", "kunci-test")
    monkeypatch.setattr(config, "PIPELINE_AI", True)
    monkeypatch.setattr(config, "JIT_TIER2", True)

    store.reset_engine()
    import main as main_mod

    main_mod.REPO = Repo(store.db.get_session_factory())
    main_mod._PEKERJAAN_PIPELINE.clear()
    store.init_db()
    muat_klaim(main_mod.REPO)

    from ai import HasilEkstraksi, adalah_url_placeholder

    # Supaya klaim dummy c001 ikut menembus ekstraksi & Lens dengan file lokal uji
    monkeypatch.setattr(main_mod.ai, "adalah_url_placeholder", lambda url: "c001" not in str(url) and adalah_url_placeholder(url))
    monkeypatch.setattr("ai.routing.adalah_url_placeholder", lambda url: "c001" not in str(url) and adalah_url_placeholder(url))
    monkeypatch.setattr(
        "ai.ekstraksi.ekstrak_sinyal_media",
        lambda src: HasilEkstraksi(
            sumber=str(src),
            folder_kerja=work,
            audio_path=None,
            keyframes=[(2.0, kf)],
            durasi=12.0,
        ),
    )
    monkeypatch.setattr(
        "ai.ocr.ocr_keyframes",
        lambda kfs, fallback_aman=True: HasilOCR(
            teks_unik=["SITUBONDO 2021"], watermark_terdeteksi=["TikTok @akun"], sumber_ocr="gemini"
        ),
    )
    monkeypatch.setattr(
        "ai.ocr.ocr_gambar",
        lambda src, fallback_aman=True: HasilOCR(
            teks_unik=["KUTIPAN RESMI"], sumber_ocr="gemini"
        ),
    )

    from search import frames, web_search
    from search.models import Temuan

    lens_dipanggil = []
    monkeypatch.setattr(web_search, "cari_google", lambda q, kutipan=False, maks=8: [])
    monkeypatch.setattr(web_search, "cari_youtube", lambda q, maks=5: [])
    monkeypatch.setattr(
        web_search,
        "reverse_image",
        lambda url_g, maks=8, untuk_video=False: (
            lens_dipanggil.append((url_g, untuk_video))
            or [
                Temuan(
                    "https://www.youtube.com/watch?v=LATGAB2021",
                    "keyword",
                    0.66,
                    jenis_sumber="media",
                    dari_lens=True,
                )
            ]
        ),
    )
    monkeypatch.setattr(
        frames,
        "temuan_dari_video",
        lambda viral, cand, cache=None: Temuan(
            cand,
            "frame_match",
            0.91,
            jenis_sumber="media",
            tanggal_unggah=datetime(2021, 8, 18, tzinfo=timezone.utc),
            cuplikan="00:42",
            resolusi=1080,
            ada_watermark=False,
            kemiripan_frame=0.91,
        ),
    )
    monkeypatch.setattr(
        "ai.sumber.ekstrak_sinyal_kandidat",
        lambda cand, **kw: SinyalSumberAcuan(
            url=str(cand.url),
            judul="Latgab TNI 2021",
            jenis_sumber=cand.jenis_sumber,
            jenis_konten="video",
            sumber_ekstraksi="video_stt_ocr",
            ekstraksi_penuh_berhasil=True,
            detik_cuplikan=42.0,
            teks_isi="Latihan gabungan resmi Agustus 2021.",
        ),
    )
    monkeypatch.setattr(
        "ai.rag.cari_korpus",
        lambda **kw: _hasil_tahap2_contoh().hasil_rag,
    )
    monkeypatch.setattr(
        "llm.tanya_multimodal_json",
        lambda *a, **kw: {
            "status": "terbukti_diubah",
            "perlu_eskalasi": False,
            "konsisten_dengan_sumber": False,
            "sumber_tertua_meragukan": False,
            "keyakinan": 0.9,
            "sumber_utama_url": "https://www.youtube.com/watch?v=LATGAB2021",
            "sumber_utama_judul": "Latgab TNI 2021",
            "sumber_utama_tanggal": "2021-08-18",
            "manipulasi": {
                "dipotong": True,
                "detail_dipotong": "Cuplikan 00:42",
                "tanggal_berbeda": True,
                "detail_tanggal": "Video asli Agustus 2021",
                "kutipan_tidak_ada": False,
                "konteks_berbeda": True,
                "detail_konteks": "Latihan resmi diklaim pengerahan darurat",
                "lainnya": False,
            },
            "ringkasan": "Video merupakan cuplikan latihan tahun 2021.",
            "fakta_utama": "Latihan Gabungan 2021 dilaksanakan Agustus 2021.",
            "apa_yang_diubah": "Tahun kejadian diubah menjadi seolah baru terjadi.",
            "bukti": [
                {
                    "jenis": "frame",
                    "url": "https://www.youtube.com/watch?v=LATGAB2021",
                    "cuplikan": "00:42",
                    "teks_viral": "Video baru terjadi",
                    "teks_sumber": "Latgab TNI 2021",
                    "catatan": "Cocok dengan video latihan 2021",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "llm.tanya_json",
        lambda *a, **kw: {
            "kartu": "KLARIFIKASI: Video ini adalah rekaman Latgab TNI tahun 2021.",
            "pendek": "Rekaman berasal dari Latihan Gabungan TNI Agustus 2021.",
            "whatsapp": "*[KLARIFIKASI]* Video adalah rekaman Latgab TNI 2021, bukan kejadian baru.",
        },
    )

    with TestClient(main_mod.app) as client:
        # 1. Pipeline sinkron penuh Tahap 1 -> 5
        r_sync = client.post("/pipeline/c001")
        assert r_sync.status_code == 200, r_sync.text
        data = r_sync.json()
        assert data["verifikasi"]["status"] == "terbukti_diubah"
        assert "Latgab TNI 2021" in data["verifikasi"]["draf_klarifikasi"]["whatsapp"]
        assert lens_dipanggil and lens_dipanggil[0][1] is True
        # Relasi netra_klaim_bukti tercatat lewat tautan_bukti
        tautan_db = main_mod.REPO.daftar_bukti_klaim("c001")
        assert tautan_db

        # 2. Pipeline latar belakang (/antre -> /status)
        r_antre = client.post("/pipeline/c002/antre")
        assert r_antre.status_code == 202, r_antre.text
        assert r_antre.json()["status_kerja"] in ("antre", "berjalan", "selesai")

        r_status = client.get("/pipeline/c002/status")
        assert r_status.status_code == 200, r_status.text
        assert r_status.json()["status_kerja"] == "selesai"
        assert main_mod.REPO.ambil_verifikasi("c002") is not None
