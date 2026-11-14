"""Tes Tahap 4: Cross-Verification LLM, deteksi manipulasi, guardrail eskalasi, dan fallback."""

from datetime import datetime, timezone

import httpx
import pytest

import config
import llm
from ai import (
    HasilCariKorpus,
    HasilOCR,
    HasilSTT,
    HasilTahap2,
    HasilVerifikasiSilang,
    ItemTeksOCR,
    SCHEMA_VERIFIKASI_SILANG,
    SYSTEM_PROMPT_VERIFIKASI,
    SegmenTranskrip,
    SinyalKonten,
    SinyalSumberAcuan,
    VerifikasiError,
    konversi_ke_bukti_schema,
    susun_konteks_verifikasi,
    susun_parts_verifikasi,
    verifikasi_silang,
)
from schemas import KandidatSumber, Klaim

SEKARANG = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)


def _klaim(**kw) -> Klaim:
    dasar = dict(
        claim_id="t4",
        teks_klaim="Video kejadian disebut terjadi minggu ini dan disertai ancaman",
        jenis_media="video",
        media_url="https://example.com/viral/video.mp4",
        tanggal_ditemukan=SEKARANG,
    )
    return Klaim(**{**dasar, **kw})


def _kandidat(**kw) -> KandidatSumber:
    dasar = dict(
        url="https://www.youtube.com/watch?v=ASLI-2019",
        tanggal_unggah=datetime(2019, 8, 21, tzinfo=timezone.utc),
        jenis_sumber="media",
        metode="frame_match",
        kemiripan=0.92,
        cuplikan="00:42",
        resolusi=1080,
        ada_watermark=False,
        kecocokan_audio=0.88,
        skor=0.89,
        judul="Liputan pengamanan resmi Agustus 2019",
    )
    return KandidatSumber(**{**dasar, **kw})


def _hasil_tahap2_siap(klaim: Klaim | None = None, **kw) -> HasilTahap2:
    k = klaim or _klaim()
    sinyal_klaim = SinyalKonten(
        claim_id=k.claim_id,
        teks_klaim=k.teks_klaim,
        jenis_media=k.jenis_media,
        media_url=str(k.media_url) if k.media_url else None,
        audio_tersedia=True,
        stt_teks="Warga diminta membubarkan diri segera",
        stt_segmen=[SegmenTranskrip(start=12.0, end=18.5, text="Warga diminta membubarkan diri segera")],
        sumber_stt="whisper_docker",
        ocr=HasilOCR(
            items=[
                ItemTeksOCR(
                    teks="TERJADI HARI INI NOV 2026",
                    kategori="overlay",
                    detik_awal=0.0,
                    detik_akhir=8.0,
                )
            ],
            teks_unik=["TERJADI HARI INI NOV 2026"],
            tanggal_di_layar="Nov 2026",
            sumber_ocr="gemini",
        ),
    )
    kandidat = _kandidat()
    sinyal_sumber = SinyalSumberAcuan(
        url=str(kandidat.url),
        judul=kandidat.judul,
        jenis_sumber=kandidat.jenis_sumber,
        jenis_konten="video",
        tanggal_unggah=kandidat.tanggal_unggah.isoformat() if kandidat.tanggal_unggah else None,
        sumber_ekstraksi="video_stt_ocr",
        ekstraksi_penuh_berhasil=True,
        detik_cuplikan=42.0,
        jendela_mulai_detik=22.0,
        jendela_durasi_detik=90.0,
        teks_isi="Transkrip lengkap: petugas berdialog persuasif sebelum penertiban tahun 2019",
        stt_teks="Petugas berdialog persuasif bersama tokoh masyarakat pada Agustus 2019",
        stt_segmen=[
            SegmenTranskrip(start=42.0, end=49.0, text="Petugas berdialog persuasif bersama tokoh masyarakat")
        ],
        sumber_stt="whisper_docker",
    )
    dasar = dict(
        claim_id=k.claim_id,
        jalur="tier1_ke_tahap4",
        siap_tahap4=True,
        alasan_routing="Kandidat bersih Tier-1 kuat.",
        sinyal_klaim=sinyal_klaim,
        kandidat_bersih=[kandidat],
        sinyal_sumber=[sinyal_sumber],
        metode_terpakai=["frame_match", "asr", "ocr"],
    )
    return HasilTahap2(**{**dasar, **kw})


def test_llm_mengirim_system_instruction(monkeypatch):
    tangkapan: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        tangkapan["body"] = json
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"status": "tidak_ditemukan"}'}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("httpx.post", fake_post)

    res = llm.tanya_multimodal_json(
        [llm.part_teks("uji konteks")],
        skema=SCHEMA_VERIFIKASI_SILANG,
        instruksi_sistem=SYSTEM_PROMPT_VERIFIKASI,
    )
    assert res == {"status": "tidak_ditemukan"}
    assert tangkapan["body"]["systemInstruction"] == {"parts": [{"text": SYSTEM_PROMPT_VERIFIKASI}]}


def test_shortcut_eskalasi_pra_llm_tidak_panggil_gemini(monkeypatch):
    def jangan_panggil(*args, **kwargs):
        raise AssertionError("Gemini tidak boleh dipanggil jika hasil Tahap 2 sudah eskalasi")

    monkeypatch.setattr("llm.tanya_multimodal_json", jangan_panggil)

    k = _klaim(claim_id="wc")
    ditolak = _kandidat(
        url="https://www.tiktok.com/@akun/video/99",
        jenis_sumber="pribadi",
        ada_watermark=True,
        judul="Reupload berwatermark",
    )
    tahap2_wc = HasilTahap2(
        claim_id="wc",
        jalur="eskalasi_worst_case",
        siap_tahap4=False,
        status_rekomendasi="belum_bisa_diverifikasi",
        perlu_eskalasi=True,
        alasan_routing="Semua kandidat berasal dari akun pribadi berwatermark.",
        sinyal_klaim=SinyalKonten(claim_id="wc", teks_klaim=k.teks_klaim, jenis_media="video"),
        kandidat_ditolak=[ditolak],
        metode_terpakai=["frame_match"],
    )

    hasil = verifikasi_silang(k, tahap2_wc)
    assert hasil.status == "belum_bisa_diverifikasi"
    assert hasil.perlu_eskalasi is True
    assert hasil.sumber_tertua_meragukan is True
    assert hasil.sumber_analisis == "eskalasi_pra_llm"
    assert hasil.sumber_utama_url == "https://www.tiktok.com/@akun/video/99"
    assert len(hasil.bukti) == 1 and hasil.bukti[0].jenis == "metadata"

    tahap2_kosong = HasilTahap2(
        claim_id="wc",
        jalur="eskalasi_tidak_ditemukan",
        siap_tahap4=False,
        status_rekomendasi="tidak_ditemukan",
        perlu_eskalasi=True,
        alasan_routing="Tidak ada sumber pendukung.",
        sinyal_klaim=SinyalKonten(claim_id="wc", teks_klaim=k.teks_klaim, jenis_media="teks"),
        metode_terpakai=["manual"],
    )
    hasil_kosong = verifikasi_silang(k, tahap2_kosong)
    assert hasil_kosong.status == "tidak_ditemukan"
    assert hasil_kosong.perlu_eskalasi is True
    assert hasil_kosong.bukti == []


def test_susun_parts_sertakan_timestamp_ocr_rag_dan_visual(tmp_path):
    img = tmp_path / "kf.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0dummyjpeg")

    k = _klaim(claim_id="vis")
    tahap2 = _hasil_tahap2_siap(
        k,
        jalur="tier1_dan_rag_ke_tahap4",
        hasil_rag=[
            HasilCariKorpus(
                chunk_id=7,
                doc_id="rilis-2019",
                judul="Rilis Resmi Pengamanan 2019",
                tanggal_terbit="2019-08-22",
                url="https://tniad.mil.id/rilis-2019",
                jenis_sumber="resmi",
                jenis_konten="teks",
                kutipan="Kegiatan pengamanan berlangsung kondusif pada Agustus 2019.",
                skor_kemiripan=0.88,
                metode_cari="vector",
            )
        ],
    )
    tahap2.sinyal_klaim.media_lokal = str(img)

    teks = susun_konteks_verifikasi(k, tahap2)
    assert "[00:12-00:18] Warga diminta membubarkan diri segera" in teks
    assert "TERJADI HARI INI NOV 2026" in teks
    assert "[00:42-00:49] Petugas berdialog persuasif bersama tokoh masyarakat" in teks
    assert "https://tniad.mil.id/rilis-2019" in teks

    parts = susun_parts_verifikasi(k, tahap2, sertakan_visual=True)
    assert len(parts) == 3
    assert parts[2]["inlineData"]["mimeType"] == "image/jpeg"


def test_verifikasi_silang_terbukti_diubah_dan_normalisasi_url(monkeypatch):
    k = _klaim(claim_id="ok1")
    tahap2 = _hasil_tahap2_siap(k)

    def fake_multimodal(parts, **kwargs):
        import config

        assert kwargs.get("instruksi_sistem") == SYSTEM_PROMPT_VERIFIKASI
        assert kwargs.get("skema") == SCHEMA_VERIFIKASI_SILANG
        assert kwargs.get("thinking") == config.GEMINI_THINKING_VERIFIKASI
        assert kwargs.get("media_resolution") == "MEDIA_RESOLUTION_LOW"
        return {
            "status": "terbukti_diubah",
            "keyakinan": 0.91,
            "konsisten_dengan_sumber": False,
            "sumber_tertua_meragukan": False,
            # Trailing slash berbeda sedikit dari URL asli -> harus dinormalisasi
            "sumber_utama_url": "https://www.youtube.com/watch?v=ASLI-2019/",
            "manipulasi": {
                "dipotong": True,
                "detail_dipotong": "Adegan dialog awal di menit 00:42 dipotong.",
                "tanggal_berbeda": True,
                "detail_tanggal": "Video Agustus 2019 diberi keterangan November 2026.",
                "kutipan_tidak_ada": False,
                "konteks_berbeda": False,
                "lainnya": False,
            },
            "ringkasan": "Video merupakan rekaman lama tahun 2019 yang dipotong bagian dialognya.",
            "fakta_utama": "Rekaman berasal dari peliputan Agustus 2019 saat petugas berdialog persuasif.",
            "apa_yang_diubah": "Klip dipotong di bagian dialog persuasif dan diberi label tanggal Nov 2026.",
            "bukti": [
                {
                    "jenis": "transkrip",
                    "url": "https://www.youtube.com/watch?v=ASLI-2019",
                    "cuplikan": "00:42-00:49",
                    "teks_viral": "Video kejadian minggu ini tanpa dialog",
                    "teks_sumber": "Petugas berdialog persuasif bersama tokoh masyarakat",
                    "catatan": "Segmen dialog asli hilang dari potongan viral.",
                },
                {
                    "jenis": "kutipan",
                    # URL halusinasi yang tidak ada di konteks -> harus dibuang!
                    "url": "https://situs-halusinasi.example/palsu",
                    "teks_sumber": "Klaim karangan.",
                },
            ],
        }

    monkeypatch.setattr("llm.tanya_multimodal_json", fake_multimodal)

    hasil = verifikasi_silang(k, tahap2, sertakan_visual=False)
    assert isinstance(hasil, HasilVerifikasiSilang)
    assert hasil.status == "terbukti_diubah"
    assert hasil.perlu_eskalasi is False
    assert hasil.alasan_eskalasi is None
    assert hasil.perubahan == ["dipotong", "tanggal_berbeda"]
    assert hasil.sumber_utama_url == "https://www.youtube.com/watch?v=ASLI-2019"
    assert hasil.sumber_utama_judul == "Liputan pengamanan resmi Agustus 2019"
    assert len(hasil.bukti) == 1
    assert hasil.bukti[0].cuplikan == "00:42-00:49"

    bukti_schema = konversi_ke_bukti_schema(hasil.bukti)
    assert len(bukti_schema) == 1
    assert str(bukti_schema[0].url) == "https://www.youtube.com/watch?v=ASLI-2019"


@pytest.mark.parametrize(
    "mutasi_respons",
    [
        {"keyakinan": 0.42},
        {"sumber_tertua_meragukan": True},
        {"konsisten_dengan_sumber": True},
        {
            "manipulasi": {
                "dipotong": False,
                "tanggal_berbeda": False,
                "kutipan_tidak_ada": False,
                "konteks_berbeda": False,
                "lainnya": False,
            }
        },
    ],
)
def test_guardrail_paksa_eskalasi_saat_ragu_atau_inkonsisten(monkeypatch, mutasi_respons):
    k = _klaim(claim_id="grd")
    tahap2 = _hasil_tahap2_siap(k)

    dasar_llm = {
        "status": "terbukti_diubah",
        "keyakinan": 0.85,
        "konsisten_dengan_sumber": False,
        "sumber_tertua_meragukan": False,
        "sumber_utama_url": "https://www.youtube.com/watch?v=ASLI-2019",
        "manipulasi": {
            "dipotong": False,
            "tanggal_berbeda": True,
            "kutipan_tidak_ada": False,
            "konteks_berbeda": False,
            "lainnya": False,
        },
        "ringkasan": "Perlu dicek.",
        "fakta_utama": "Ada perbedaan tahun.",
        "apa_yang_diubah": "Tahun kejadian.",
        "bukti": [],
    }
    dasar_llm.update(mutasi_respons)

    monkeypatch.setattr("llm.tanya_multimodal_json", lambda *a, **kw: dasar_llm)

    hasil = verifikasi_silang(k, tahap2, sertakan_visual=False)
    assert hasil.status == "belum_bisa_diverifikasi"
    assert hasil.perlu_eskalasi is True
    assert hasil.alasan_eskalasi


def test_fallback_aman_saat_llm_error_dan_mode_ketat(monkeypatch):
    k = _klaim(claim_id="err")
    tahap2 = _hasil_tahap2_siap(k)

    def gagal_llm(*args, **kwargs):
        raise llm.LLMError("HTTP 429: rate limit")

    monkeypatch.setattr("llm.tanya_multimodal_json", gagal_llm)

    hasil = verifikasi_silang(k, tahap2, sertakan_visual=False, fallback_aman=True)
    assert hasil.status == "belum_bisa_diverifikasi"
    assert hasil.perlu_eskalasi is True
    assert hasil.sumber_analisis == "fallback_error"
    assert "HTTP 429" in (hasil.catatan_sistem or "")
    assert hasil.sumber_utama_url == "https://www.youtube.com/watch?v=ASLI-2019"
    assert hasil.bukti  # metadata bukti Tier-1 tetap diselamatkan untuk petugas

    with pytest.raises(VerifikasiError):
        verifikasi_silang(k, tahap2, sertakan_visual=False, fallback_aman=False)


def test_susun_parts_verifikasi_lampirkan_semua_slide_gambar(tmp_path):
    slides = []
    for i in range(1, 4):
        p = tmp_path / f"slide_{i}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0" + str(i).encode())
        slides.append(str(p))

    k = _klaim(claim_id="ig_slide", jenis_media="gambar", media_url="https://www.instagram.com/p/CAROUSEL1/")
    tahap2 = _hasil_tahap2_siap(k)
    tahap2.sinyal_klaim.jenis_media = "gambar"
    tahap2.sinyal_klaim.media_lokal = slides[0]
    tahap2.sinyal_klaim.keyframes_lokal = slides

    parts = susun_parts_verifikasi(k, tahap2, sertakan_visual=True)
    gambar_parts = [p for p in parts if "inlineData" in p]
    assert len(gambar_parts) == 3

