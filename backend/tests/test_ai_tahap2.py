"""Tes Tahap 2 modul AI: ekstraksi sinyal sumber acuan & logika percabangan (routing)."""

import json
from datetime import datetime, timezone

import httpx

import config
from ai import (
    HasilCariKorpus,
    HasilOCR,
    HasilSTT,
    HasilTahap2,
    ItemTeksOCR,
    SegmenTranskrip,
    SinyalKonten,
    SinyalSumberAcuan,
    adalah_url_placeholder,
    deteksi_jenis_kandidat,
    ekstrak_sinyal_kandidat,
    ekstrak_sinyal_klaim,
    ekstrak_teks_html,
    evaluasi_kandidat,
    hitung_jendela_video,
    jalankan_tahap2,
    transkrip_audio_aman,
)
from schemas import HasilPencarian, KandidatSumber, Klaim

WAKTU_CONTOH = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)


def _klaim(**kw) -> Klaim:
    dasar = dict(
        claim_id="t_tahap2",
        teks_klaim="Klaim contoh uji",
        jenis_media="teks",
        tanggal_ditemukan=WAKTU_CONTOH,
    )
    return Klaim(**{**dasar, **kw})


def _kandidat(**kw) -> KandidatSumber:
    dasar = dict(
        url="https://tniad.mil.id/rilis-uji",
        jenis_sumber="resmi",
        metode="keyword",
        kemiripan=0.8,
        skor=0.8,
        judul="Rilis Uji",
    )
    return KandidatSumber(**{**dasar, **kw})


def _rag_item(**kw) -> HasilCariKorpus:
    dasar = dict(
        chunk_id=1,
        doc_id="dok_001",
        judul="Siaran Pers Resmi Kasad",
        tanggal_terbit="2026-11-08",
        url="https://tniad.mil.id/siaran-pers",
        jenis_sumber="resmi",
        jenis_konten="teks",
        kutipan="Kasad menegaskan TNI AD tunduk pada supremasi sipil.",
        skor_kemiripan=0.88,
        metode_cari="vector",
    )
    return HasilCariKorpus(**{**dasar, **kw})


def test_deteksi_jenis_kandidat_dan_placeholder():
    assert adalah_url_placeholder("https://example.com/viral/v.mp4") is True
    assert adalah_url_placeholder("https://www.youtube.com/watch?v=CONTOH-ASLI-2019") is True
    assert adalah_url_placeholder("https://rri.co.id/berita/klarifikasi-123") is False

    assert deteksi_jenis_kandidat(_kandidat(url="https://www.youtube.com/watch?v=abc")) == "video"
    assert deteksi_jenis_kandidat(_kandidat(url="https://www.tiktok.com/@a/video/1")) == "video"
    assert deteksi_jenis_kandidat(_kandidat(url="https://cdn.site.id/foto.jpg")) == "gambar"
    assert (
        deteksi_jenis_kandidat(
            _kandidat(
                url="https://www.kompas.com/cekfakta/read/2023/09/20/berita",
                metode="frame_match",
                cuplikan="Konten lama tahun 2023",
            )
        )
        == "artikel"
    )


def test_hitung_jendela_video_sekitar_cuplikan():
    mulai, durasi, pusat = hitung_jendela_video("00:42", durasi_total=120.0, konteks_sebelum=20.0, durasi_jendela=90.0)
    assert pusat == 42.0
    assert mulai == 22.0
    assert durasi == 90.0

    # Jika durasi video ternyata lebih pendek daripada estimasi mulai, clamp aman
    mulai_pendek, _, _ = hitung_jendela_video("02:00", durasi_total=60.0, konteks_sebelum=10.0, durasi_jendela=40.0)
    assert mulai_pendek == 20.0

    assert hitung_jendela_video("Kutipan teks biasa") == (0.0, 90.0, None)


def test_ekstrak_teks_html_membersihkan_script_dan_mengambil_artikel():
    halaman = """
    <html>
      <head>
        <title>Berita Lama</title>
        <meta property="og:title" content="Rilis Resmi Klarifikasi" />
        <meta property="article:published_time" content="2024-10-12T09:00:00+07:00" />
        <style>.iklan { display: none; }</style>
      </head>
      <body>
        <nav>Beranda | Politik | Kontak</nav>
        <article>
          <h1>Klarifikasi Resmi</h1>
          <p>Dinas Penerangan TNI AD memastikan video yang beredar adalah rekaman latihan tahun 2021 di lokasi berbeda.</p>
          <p>Masyarakat diimbau tidak menyebarkan narasi yang dipelintir dan selalu memeriksa sumber resmi.</p>
        </article>
        <footer>Hak Cipta 2026</footer>
        <script>console.log("jangan ikut terekstrak");</script>
      </body>
    </html>
    """
    hasil = ekstrak_teks_html(halaman)
    assert hasil["judul"] == "Rilis Resmi Klarifikasi"
    assert hasil["tanggal_terbit"] == "2024-10-12T09:00:00+07:00"
    assert "rekaman latihan tahun 2021" in hasil["isi"]
    assert "jangan ikut terekstrak" not in hasil["isi"]
    assert "Beranda | Politik" not in hasil["isi"]
    assert "Hak Cipta" not in hasil["isi"]


def test_ekstrak_sinyal_kandidat_artikel_web_sukses_dan_fallback(monkeypatch):
    k = _kandidat(url="https://tniad.mil.id/berita/klarifikasi-resmi", judul="Klarifikasi TNI AD", cuplikan="Snippet awal")

    def fake_get(url, follow_redirects=True, timeout=None, headers=None):
        html_ok = (
            "<html><body><article><p>"
            "Siaran pers resmi menegaskan pernyataan tersebut tidak pernah disampaikan oleh pimpinan TNI AD dalam forum mana pun."
            "</p></article></body></html>"
        )
        return httpx.Response(
            200,
            text=html_ok,
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("httpx.get", fake_get)
    sinyal = ekstrak_sinyal_kandidat(k)
    assert sinyal.jenis_konten == "artikel"
    assert sinyal.sumber_ekstraksi == "web_artikel"
    assert sinyal.ekstraksi_penuh_berhasil is True
    assert "tidak pernah disampaikan" in sinyal.teks_isi

    def fake_get_error(url, **kwargs):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr("httpx.get", fake_get_error)
    sinyal_fallback = ekstrak_sinyal_kandidat(k)
    assert sinyal_fallback.sumber_ekstraksi == "fallback_snippet"
    assert sinyal_fallback.ekstraksi_penuh_berhasil is False
    assert "Klarifikasi TNI AD" in sinyal_fallback.teks_isi
    assert "Snippet awal" in sinyal_fallback.teks_isi


def test_ekstrak_sinyal_kandidat_video_memotong_sekitar_cuplikan(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    vid = tmp_path / "asli.mp4"
    vid.write_bytes(b"mp4")
    aud = tmp_path / "aud.wav"
    aud.write_bytes(b"RIFF" + b"\x00" * 100)
    kf = tmp_path / "kf_0001.jpg"
    kf.write_bytes(b"jpg")
    tangkapan = {}

    monkeypatch.setattr("ai.ekstraksi._siapkan_video", lambda src: vid)
    monkeypatch.setattr("ai.ekstraksi.durasi_video", lambda p: 180.0)

    def fake_audio(video, mulai_detik=0.0, durasi_maks=90.0, output=None):
        tangkapan["audio_mulai"] = mulai_detik
        tangkapan["audio_durasi"] = durasi_maks
        return aud

    def fake_keyframes(video, mulai_detik=0.0, durasi_maks=90.0, output_dir=None, **kw):
        tangkapan["kf_mulai"] = mulai_detik
        return [(mulai_detik, kf)]

    monkeypatch.setattr("ai.ekstraksi.ekstrak_audio", fake_audio)
    monkeypatch.setattr("ai.ekstraksi.ekstrak_keyframes", fake_keyframes)
    monkeypatch.setattr(
        "ai.sumber.transkrip_audio_aman",
        lambda path, bahasa="id": HasilSTT(
            teks="Ini adalah kegiatan latihan tahun 2019.",
            segmen=[SegmenTranskrip(start=0.0, end=3.0, text="Ini adalah kegiatan latihan tahun 2019.")],
            sumber_stt="whisper_docker",
        ),
    )
    monkeypatch.setattr(
        "ai.ocr.ocr_keyframes",
        lambda keyframes, fallback_aman=True: HasilOCR(
            items=[ItemTeksOCR(teks="KOMPASTV ARSIP 2019", kategori="watermark")],
            teks_unik=["KOMPASTV ARSIP 2019"],
            sumber_ocr="gemini",
        ),
    )

    k = _kandidat(
        url="https://www.youtube.com/watch?v=REALVIDEO123",
        jenis_sumber="media",
        metode="frame_match",
        cuplikan="00:42",
        judul="Liputan Latihan 2019",
    )
    sinyal = ekstrak_sinyal_kandidat(k, konteks_sebelum=15.0, durasi_jendela=60.0)
    assert tangkapan["audio_mulai"] == 27.0
    assert tangkapan["kf_mulai"] == 27.0
    assert tangkapan["audio_durasi"] == 60.0
    assert sinyal.sumber_ekstraksi == "video_stt_ocr"
    assert sinyal.ekstraksi_penuh_berhasil is True
    assert sinyal.detik_cuplikan == 42.0
    assert "kegiatan latihan tahun 2019" in sinyal.teks_isi
    assert "KOMPASTV ARSIP 2019" in sinyal.teks_isi


def test_transkrip_audio_aman_saat_stt_tidak_aktif_tanpa_gemini(tmp_path, monkeypatch):
    aud = tmp_path / "suara.wav"
    aud.write_bytes(b"RIFF" + b"\x00" * 100)

    def fail_docker(*args, **kwargs):
        from ai import STTError

        raise STTError("connection refused")

    gemini_dipanggil = {"n": 0}

    def fail_if_called(*args, **kwargs):
        gemini_dipanggil["n"] += 1
        raise AssertionError("Gemini tidak boleh dipanggil untuk fallback STT")

    monkeypatch.setattr("ai.stt.transkrip_audio", fail_docker)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("llm.tanya_multimodal_json", fail_if_called)

    hasil = transkrip_audio_aman(aud)
    assert hasil.sumber_stt == "tidak_aktif"
    assert hasil.teks == ""
    assert hasil.segmen == []
    assert gemini_dipanggil["n"] == 0

    monkeypatch.setattr(config, "STT_BASE_URL", "")
    hasil_kosong_url = transkrip_audio_aman(aud)
    assert hasil_kosong_url.sumber_stt == "tidak_aktif"
    assert gemini_dipanggil["n"] == 0


def test_sinyal_konten_query_rag_menggabungkan_dan_deduplikasi():
    s = SinyalKonten(
        claim_id="c1",
        teks_klaim="Kasad menyatakan sesuatu",
        jenis_media="video",
        stt_teks="Kasad menyatakan sesuatu. Video dipotong.",
        ocr=HasilOCR(teks_unik=["Kasad menyatakan sesuatu", "BERITA BARU"]),
    )
    q = s.query_rag()
    assert q.count("Kasad menyatakan sesuatu") == 2  # satu di klaim, satu di kalimat stt (teks OCR duplikat dibuang)
    assert "BERITA BARU" in q


def test_routing_jalur_tier1_kuat_ke_tahap4(monkeypatch):
    klaim = _klaim(
        claim_id="v1",
        teks_klaim="Video prajurit membubarkan warga minggu ini",
        jenis_media="video",
        media_url="https://example.com/viral/v1.mp4",
    )
    pencarian = HasilPencarian(
        claim_id="v1",
        kandidat=[
            _kandidat(
                url="https://www.youtube.com/watch?v=REALVID",
                jenis_sumber="media",
                metode="frame_match",
                kemiripan=0.93,
                skor=0.91,
                cuplikan="00:42",
                ada_watermark=False,
            )
        ],
    )

    monkeypatch.setattr(
        "ai.sumber.ekstrak_sinyal_kandidat",
        lambda k, **kw: SinyalSumberAcuan(
            url=str(k.url),
            judul=k.judul,
            jenis_sumber=k.jenis_sumber,
            jenis_konten="video",
            sumber_ekstraksi="video_stt_ocr",
            ekstraksi_penuh_berhasil=True,
            detik_cuplikan=42.0,
            teks_isi="Liputan tahun 2019",
            sumber_stt="whisper_docker",
        ),
    )
    rag_dipanggil = {"n": 0}
    monkeypatch.setattr("ai.rag.cari_korpus", lambda **kw: rag_dipanggil.__setitem__("n", rag_dipanggil["n"] + 1) or [])

    hasil = jalankan_tahap2(klaim, pencarian)
    assert isinstance(hasil, HasilTahap2)
    assert hasil.jalur == "tier1_ke_tahap4"
    assert hasil.siap_tahap4 is True
    assert hasil.perlu_eskalasi is False
    assert rag_dipanggil["n"] == 0
    assert "frame_match" in hasil.metode_terpakai
    assert "asr" in hasil.metode_terpakai


def test_routing_jalur_tier1_plus_rag_untuk_klaim_kutipan(monkeypatch):
    klaim = _klaim(
        claim_id="c002",
        teks_klaim="Kasad disebut menyatakan 'TNI siap ambil alih pemerintahan sipil'",
        jenis_media="gambar",
        media_url="https://example.com/viral/gambar-c002.jpg",
    )
    pencarian = HasilPencarian(
        claim_id="c002",
        kandidat=[
            _kandidat(
                url="https://tniad.mil.id/CONTOH-siaran-pers-kasad",
                jenis_sumber="resmi",
                metode="kutipan",
                kemiripan=0.55,
                skor=0.73,
                cuplikan="Kasad menegaskan TNI tunduk pada otoritas sipil.",
            )
        ],
    )
    monkeypatch.setattr("ai.rag.cari_korpus", lambda **kw: [_rag_item()])

    hasil = jalankan_tahap2(klaim, pencarian)
    assert hasil.jalur == "tier1_dan_rag_ke_tahap4"
    assert hasil.siap_tahap4 is True
    assert len(hasil.sinyal_sumber) == 1
    assert len(hasil.hasil_rag) == 1
    assert "rag" in hasil.metode_terpakai


def test_routing_kandidat_kosong_ke_tier2_rag_dan_eskalasi_tidak_ditemukan(monkeypatch):
    klaim = _klaim(claim_id="c004", teks_klaim="Pengumuman pembagian sembako")
    pencarian = HasilPencarian(claim_id="c004", kandidat=[])

    # 1. Jika RAG menemukan korpus resmi -> teruskan ke Tahap 4 via tier2_rag_ke_tahap4
    monkeypatch.setattr("ai.rag.cari_korpus", lambda **kw: [_rag_item(metode_cari="keyword", skor_kemiripan=0.3)])
    hasil_ada = jalankan_tahap2(klaim, pencarian)
    assert hasil_ada.jalur == "tier2_rag_ke_tahap4"
    assert hasil_ada.siap_tahap4 is True
    assert hasil_ada.perlu_eskalasi is False

    # 2. Jika RAG juga kosong -> eskalasi tidak_ditemukan
    monkeypatch.setattr("ai.rag.cari_korpus", lambda **kw: [])
    hasil_kosong = jalankan_tahap2(klaim, pencarian)
    assert hasil_kosong.jalur == "eskalasi_tidak_ditemukan"
    assert hasil_kosong.siap_tahap4 is False
    assert hasil_kosong.status_rekomendasi == "tidak_ditemukan"
    assert hasil_kosong.perlu_eskalasi is True


def test_routing_worst_case_semua_pribadi_watermark(monkeypatch):
    klaim = _klaim(
        claim_id="c001b",
        teks_klaim="Video pengamanan disebut baru terjadi pekan ini",
        jenis_media="video",
        media_url="https://example.com/viral/video-c001b.mp4",
    )
    pencarian = HasilPencarian(
        claim_id="c001b",
        kandidat=[
            _kandidat(
                url="https://www.tiktok.com/@akun.lama/video/CONTOH-2023",
                jenis_sumber="pribadi",
                metode="frame_match",
                kemiripan=0.94,
                skor=0.82,
                ada_watermark=True,
            )
        ],
    )
    # Abaikan skor vektor di bawah ambang relevansi
    monkeypatch.setattr(
        "ai.rag.cari_korpus",
        lambda **kw: [_rag_item(metode_cari="vector", skor_kemiripan=0.30)],
    )

    hasil = jalankan_tahap2(klaim, pencarian)
    assert hasil.jalur == "eskalasi_worst_case"
    assert hasil.siap_tahap4 is False
    assert hasil.status_rekomendasi == "belum_bisa_diverifikasi"
    assert hasil.perlu_eskalasi is True
    assert len(hasil.kandidat_ditolak) == 1
    assert hasil.kandidat_bersih == []


def test_evaluasi_kandidat_lemah_di_bawah_ambang_turun_ke_rag():
    klaim = _klaim(claim_id="lemah")
    pencarian = HasilPencarian(
        claim_id="lemah",
        kandidat=[_kandidat(kemiripan=0.38, skor=0.35)],
    )
    kep = evaluasi_kandidat(klaim, pencarian)
    assert kep.tier1_memadai is False
    assert kep.perlu_rag is True


def test_ekstrak_sinyal_klaim_video_dan_gambar(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    img = tmp_path / "viral.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\ndummy")

    monkeypatch.setattr(
        "ai.ocr.ocr_gambar",
        lambda src, fallback_aman=True: HasilOCR(
            items=[ItemTeksOCR(teks="KUTIPAN PALSU", kategori="overlay")],
            teks_unik=["KUTIPAN PALSU"],
            sumber_ocr="gemini",
        ),
    )
    k_img = _klaim(
        claim_id="g1",
        teks_klaim="Kasad berujar demikian",
        jenis_media="gambar",
        media_url="https://cdn.site.id/viral.png",
    )
    s_img = ekstrak_sinyal_klaim(k_img)
    assert s_img.ocr.teks_unik == ["KUTIPAN PALSU"]
    assert "KUTIPAN PALSU" in s_img.query_rag()

    from ai.ekstraksi import HasilEkstraksi

    aud = tmp_path / "a.wav"
    aud.write_bytes(b"RIFF")
    kf = tmp_path / "kf.jpg"
    kf.write_bytes(b"jpg")
    monkeypatch.setattr(
        "ai.ekstraksi.ekstrak_sinyal_media",
        lambda src: HasilEkstraksi(sumber=src, folder_kerja=tmp_path, audio_path=aud, keyframes=[(1.0, kf)], durasi=5.0),
    )
    monkeypatch.setattr(
        "ai.routing.transkrip_audio_aman",
        lambda p: HasilSTT(teks="Ucapan viral.", segmen=[], sumber_stt="whisper_docker"),
    )
    monkeypatch.setattr(
        "ai.ocr.ocr_keyframes",
        lambda kfs, fallback_aman=True: HasilOCR(teks_unik=["TEKS VIDEO"], sumber_ocr="gemini"),
    )

    k_vid = _klaim(
        claim_id="v_real",
        teks_klaim="Video viral kejadian baru",
        jenis_media="video",
        media_url="https://cdn.site.id/viral.mp4",
    )
    s_vid = ekstrak_sinyal_klaim(k_vid)
    assert s_vid.audio_tersedia is True
    assert s_vid.stt_teks == "Ucapan viral."
    assert s_vid.ocr.teks_unik == ["TEKS VIDEO"]
    assert s_vid.media_lokal == str(kf)

    # Jika STT sedang tidak aktif, catatan tercatat jelas dan 'asr' tidak masuk metode_terpakai
    monkeypatch.setattr(
        "ai.routing.transkrip_audio_aman",
        lambda p: HasilSTT(teks="", segmen=[], sumber_stt="tidak_aktif"),
    )
    s_off = ekstrak_sinyal_klaim(k_vid)
    assert s_off.sumber_stt == "tidak_aktif"
    assert s_off.catatan and "tidak aktif" in s_off.catatan.lower()
    p_kosong = HasilPencarian(claim_id="v_real", kandidat=[])
    monkeypatch.setattr("ai.rag.cari_korpus", lambda **kw: [])
    monkeypatch.setattr("ai.routing.ekstrak_sinyal_klaim", lambda *a, **kw: s_off)
    res_off = jalankan_tahap2(k_vid, p_kosong)
    assert "asr" not in res_off.metode_terpakai


def test_integrasi_dengan_data_dummy_demo(monkeypatch):
    klaim_list = json.loads((config.DUMMY_DIR / "klaim.json").read_text(encoding="utf-8"))
    kandidat_map = json.loads((config.DUMMY_DIR / "kandidat.json").read_text(encoding="utf-8"))
    klaim_by_id = {d["claim_id"]: Klaim.model_validate(d) for d in klaim_list}

    monkeypatch.setattr("ai.rag.cari_korpus", lambda **kw: [])

    # c001b -> worst case eskalasi
    p_c001b = HasilPencarian(
        claim_id="c001b",
        kandidat=[KandidatSumber.model_validate(k) for k in kandidat_map["c001b"]],
    )
    r_c001b = jalankan_tahap2(klaim_by_id["c001b"], p_c001b, ambil_konten_eksternal=False)
    assert r_c001b.status_rekomendasi == "belum_bisa_diverifikasi"
    assert r_c001b.perlu_eskalasi is True

    # c004 -> tidak_ditemukan
    p_c004 = HasilPencarian(claim_id="c004", kandidat=[])
    r_c004 = jalankan_tahap2(klaim_by_id["c004"], p_c004, ambil_konten_eksternal=False)
    assert r_c004.status_rekomendasi == "tidak_ditemukan"
    assert r_c004.perlu_eskalasi is True

    # c001 -> tier1_ke_tahap4
    p_c001 = HasilPencarian(
        claim_id="c001",
        kandidat=[KandidatSumber.model_validate(k) for k in kandidat_map["c001"]],
    )
    r_c001 = jalankan_tahap2(klaim_by_id["c001"], p_c001, ambil_konten_eksternal=False)
    assert r_c001.jalur == "tier1_ke_tahap4"
    assert r_c001.siap_tahap4 is True
    assert r_c001.sinyal_sumber[0].detik_cuplikan == 42.0


def test_routing_dua_sumbu_dan_jit_tier2_cache_dan_multi_keyframe(tmp_path, monkeypatch):
    kf_paths = []
    for idx in range(3):
        p = tmp_path / f"kf_{idx}.jpg"
        p.write_bytes(b"jpg-dummy")
        kf_paths.append(str(p))

    klaim = _klaim(
        claim_id="vid_jit",
        teks_klaim="Video pasukan disebut terjadi kemarin",
        jenis_media="video",
        media_url="https://example.com/viral/v.mp4",
    )
    # Kandidat media bersih tapi hanya metode keyword (tanpa frame_match) -> harus masuk sumbu B Tier-2
    k_hit = _kandidat(
        url="https://news.detik.com/berita/d-111?utm_source=x",
        jenis_sumber="media",
        metode="keyword",
        kemiripan=0.62,
        skor=0.68,
        judul="Berita Detik Sudah Ada",
    )
    k_baru = _kandidat(
        url="https://kompas.com/read/2021/latihan-gabungan",
        jenis_sumber="media",
        metode="keyword",
        kemiripan=0.58,
        skor=0.64,
        judul="Berita Kompas Baru",
    )
    pencarian = HasilPencarian(claim_id="vid_jit", kandidat=[k_hit, k_baru])

    kep = evaluasi_kandidat(klaim, pencarian)
    assert kep.tier1_memadai is False
    assert len(kep.kandidat_tier2) == 2

    from ai import doc_id_dari_url

    id_hit = doc_id_dari_url(str(k_hit.url))
    diindeks = []
    cari_args = {}

    monkeypatch.setattr("ai.rag.dokumen_masih_aktif", lambda doc_id: doc_id == id_hit)
    monkeypatch.setattr(
        "ai.sumber.ekstrak_sinyal_kandidat",
        lambda cand, **kw: SinyalSumberAcuan(
            url=str(cand.url),
            judul=cand.judul,
            jenis_sumber=cand.jenis_sumber,
            jenis_konten="artikel",
            sumber_ekstraksi="web_artikel",
            ekstraksi_penuh_berhasil=True,
            teks_isi="Liputan tahun 2021 latihan gabungan.",
        ),
    )
    monkeypatch.setattr(
        "ai.rag.indeks_dokumen_teks",
        lambda dok, teks: diindeks.append((dok.doc_id, dok.cakupan, teks)) or 1,
    )

    def fake_cari(**kw):
        cari_args.update(kw)
        return [_rag_item(url=str(k_baru.url), doc_id=doc_id_dari_url(str(k_baru.url)), cakupan="temuan")]

    monkeypatch.setattr("ai.rag.cari_korpus", fake_cari)
    monkeypatch.setattr("ai.routing.ekstrak_sinyal_klaim", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("harus memakai sinyal_klaim_awal")))

    sinyal_awal = SinyalKonten(
        claim_id="vid_jit",
        teks_klaim=klaim.teks_klaim,
        jenis_media="video",
        media_lokal=kf_paths[1],
        keyframes_lokal=kf_paths,
        stt_teks="Sambutan latihan tahun 2021.",
    )
    hasil = jalankan_tahap2(
        klaim,
        pencarian,
        ambil_konten_eksternal=True,
        sinyal_klaim_awal=sinyal_awal,
        jit_tier2=True,
    )
    assert hasil.jalur == "tier2_rag_ke_tahap4"
    assert len(hasil.jit_cache_hit) == 1
    assert len(hasil.jit_diindeks) == 1
    assert diindeks and diindeks[0][1] == "temuan"
    assert len(cari_args["media_paths"]) == 3
    assert cari_args["cakupan"] == ["resmi", "temuan"]

    # Tanpa kandidat Tier-2 yang layak -> cari korpus harus membatasi cakupan='resmi'
    cari_kosong = {}
    monkeypatch.setattr("ai.rag.cari_korpus", lambda **kw: cari_kosong.update(kw) or [])
    res_resmi = jalankan_tahap2(
        klaim,
        HasilPencarian(claim_id="vid_jit", kandidat=[]),
        ambil_konten_eksternal=False,
        sinyal_klaim_awal=sinyal_awal,
    )
    assert res_resmi.jalur == "eskalasi_tidak_ditemukan"
    assert cari_kosong["cakupan"] == "resmi"
