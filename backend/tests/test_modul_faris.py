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


@butuh_ffmpeg
def test_frame_match_video_panjang_berjendela(tmp_path):
    """Video > 180 detik tetap terdeteksi saat cuplikan diambil setelah menit ke-3."""
    asli_panjang = tmp_path / "panjang.mp4"
    viral_akhir = tmp_path / "viral_akhir.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "mandelbrot=size=320x240:rate=5", "-t", "205",
        "-f", "lavfi", "-i", "aevalsrc='sin(440*2*PI*t)*abs(sin(0.7*t)*sin(0.23*t*t))':s=8000:d=205",
        "-c:v", "libx264", "-preset", "ultrafast", "-shortest", str(asli_panjang),
    )
    _ffmpeg(
        "-ss", "185", "-t", "10", "-i", str(asli_panjang),
        "-c:v", "libx264", "-preset", "ultrafast", str(viral_akhir),
    )
    cocok = frames.bandingkan(str(viral_akhir), str(asli_panjang), cache={})
    assert cocok.kemiripan >= 0.7
    assert cocok.detik_kandidat is not None and 178 <= cocok.detik_kandidat <= 198


def test_url_kanonis_penerbit_dan_anti_duplikat_frame_match_palsu():
    import url_kanonis

    assert url_kanonis.penerbit_dari_url("https://news.detik.com/berita/d-1") == "news.detik.com"
    assert url_kanonis.penerbit_dari_url("https://www.tiktok.com/@akun.x/video/123") == "tiktok.com/@akun.x"
    assert url_kanonis.penerbit_dari_url("https://youtube.com/watch?v=abc", uploader="KompasTV") == "youtube.com/kompastv"

    # Dua URL YouTube kanonis sama, keyword kuat (0.65) + frame match lemah (0.20)
    # TIDAK boleh dilabeli sebagai frame_match 0.65
    a = Temuan(
        "https://www.youtube.com/watch?v=ABC123&si=tracking",
        "keyword",
        0.65,
        jenis_sumber="media",
        kemiripan_teks=0.65,
        resolusi=720,
    )
    b = Temuan(
        "https://youtu.be/ABC123",
        "frame_match",
        0.20,
        jenis_sumber="media",
        kemiripan_frame=0.20,
        cuplikan="00:05",
    )
    digabung = ranking.gabung_duplikat([a, b])
    assert len(digabung) == 1
    assert digabung[0].metode == "keyword"
    assert digabung[0].kemiripan == 0.65
    assert digabung[0].kemiripan_frame == 0.20

    # Sebaliknya, jika frame_match kuat (0.88), metode memang frame_match 0.88
    c = Temuan("https://youtu.be/ABC123", "frame_match", 0.88, kemiripan_frame=0.88, cuplikan="01:10")
    digabung2 = ranking.gabung_duplikat([a, c])
    assert digabung2[0].metode == "frame_match" and digabung2[0].kemiripan == 0.88


def test_korroborasi_independen_anti_buzzer():
    tgl = datetime(2025, 5, 1, tzinfo=timezone.utc)
    # 6 re-upload dari hanya 2 akun pribadi tidak boleh melampaui batas kontribusi pribadi / dianggap kredibel
    semua = [
        Temuan(f"https://www.tiktok.com/@buzzer1/video/{i}", "frame_match", 0.9, "pribadi", tanggal_unggah=tgl)
        for i in range(4)
    ] + [
        Temuan(f"https://www.tiktok.com/@buzzer{i}/video/99", "frame_match", 0.88, "pribadi", tanggal_unggah=tgl)
        for i in range(2, 5)
    ]
    ringkas_buzzer = ranking.evaluasi_korroborasi(semua)
    klaster_buzzer = ringkas_buzzer["footage_cocok"]
    assert klaster_buzzer["indikasi_buzzer"] is True
    assert klaster_buzzer["jumlah_pribadi"] == 4
    assert klaster_buzzer["jumlah_resmi"] == 0

    # Begitu ada sumber media/resmi ikut menguatkan footage yang sama, indikasi buzzer hilang & skor naik
    dengan_resmi = semua + [
        Temuan("https://tniad.mil.id/rilis-asli", "frame_match", 0.91, "resmi", tanggal_unggah=tgl),
    ]
    hasil = ranking.peringkat(dengan_resmi)
    ringkas_kredibel = ranking.evaluasi_korroborasi(hasil)
    klaster_kredibel = ringkas_kredibel["footage_cocok"]
    assert klaster_kredibel["indikasi_buzzer"] is False
    assert klaster_kredibel["jumlah_resmi"] == 1
    assert any(h.rincian_skor.get("korroborasi", 0.0) > 0.0 for h in hasil)


def test_pipeline_pencarian_lens_video_dan_peristiwa(monkeypatch):
    import config
    from search import KonteksSinyal, cari_sumber, web_search

    monkeypatch.setattr(config, "SERPAPI_KEY", "dummy-serp")
    panggilan_lens = []
    panggilan_google = []

    monkeypatch.setattr(
        web_search,
        "cari_google",
        lambda q, kutipan=False, maks=8: (panggilan_google.append(q) or []),
    )
    monkeypatch.setattr(web_search, "cari_youtube", lambda q, maks=5: [])

    def fake_lens(url_gambar, maks=8, untuk_video=False):
        panggilan_lens.append((url_gambar, untuk_video))
        return [
            Temuan(
                "https://www.youtube.com/watch?v=LENSVID1",
                "keyword",
                0.65,
                jenis_sumber="media",
                dari_lens=True,
                uploader="KompasTV",
            )
        ]

    monkeypatch.setattr(web_search, "reverse_image", fake_lens)
    monkeypatch.setattr(
        frames,
        "temuan_dari_video",
        lambda viral, cand, cache=None: Temuan(
            cand,
            "frame_match",
            0.91,
            jenis_sumber="media",
            cuplikan="00:30",
            kemiripan_frame=0.91,
        ),
    )

    k = klaim(
        claim_id="vid_lens",
        teks_klaim="Video disebut aksi terbaru",
        jenis_media="video",
        media_url="https://example.com/viral.mp4",
    )
    konteks = KonteksSinyal(
        stt_teks="Sambutan pembukaan latihan gabungan di Situbondo 2021",
        ocr_teks=["KOMPASTV SITUBONDO"],
        watermark=["TikTok @akun"],
        keyframe_urls=["https://tunnel.example.id/media-sementara/tok1"],
    )
    hasil, proses = cari_sumber(k, konteks=konteks)
    assert panggilan_lens == [("https://tunnel.example.id/media-sementara/tok1", True)]
    assert proses["query"]["peristiwa"]
    assert any(p in panggilan_google for p in proses["query"]["peristiwa"])
    assert "https://www.youtube.com/watch?v=LENSVID1" in proses["video_dicocokkan"]
    assert "korroborasi" in proses
    assert hasil.kandidat and hasil.kandidat[0].metode == "frame_match"


def test_cari_google_resolve_redirect_goto_dan_buang_internal(monkeypatch):
    import httpx
    from search import web_search

    monkeypatch.setattr(
        web_search,
        "_serpapi",
        lambda params: {
            "organic_results": [
                {
                    "link": "https://www.google.com/goto?url=CAES_TOK_1&gsessionid=abc",
                    "title": "Berita Kompas Gibran",
                    "snippet": "Klarifikasi resmi soal gim.",
                },
                {
                    "link": "https://www.google.com/url?q=https://tempo.co/cekfakta/123&sa=U",
                    "title": "Cek Fakta Tempo",
                    "snippet": "Penjelasan lengkap.",
                },
                {
                    "link": "https://www.google.com/goto?url=CAES_INTERNAL",
                    "title": "Internal Google",
                    "snippet": "Tetap google.com.",
                },
            ]
        },
    )

    def fake_get(url, follow_redirects=False, timeout=None):
        if "CAES_TOK_1" in url:
            return httpx.Response(
                302,
                headers={"location": "https://www.kompas.com/tren/read/1"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200,
            text='<A HREF="https://accounts.google.com/ServiceLogin">login</A>',
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("httpx.get", fake_get)
    hasil = web_search.cari_google("gibran gta 6")
    assert [t.url for t in hasil] == [
        "https://www.kompas.com/tren/read/1",
        "https://tempo.co/cekfakta/123",
    ]
    assert hasil[0].jenis_sumber == "media"


def test_cari_sumber_gambar_memakai_keyframe_url_untuk_lens(monkeypatch):
    import config
    from search import KonteksSinyal, cari_sumber, web_search

    monkeypatch.setattr(config, "SERPAPI_KEY", "dummy-serp")
    panggilan_lens = []
    monkeypatch.setattr(web_search, "cari_google", lambda q, kutipan=False, maks=8: [])
    monkeypatch.setattr(
        web_search,
        "reverse_image",
        lambda url_g, maks=8, untuk_video=False: (
            panggilan_lens.append((url_g, untuk_video)) or []
        ),
    )

    k = klaim(
        claim_id="img_lens",
        teks_klaim="Foto disebut pernyataan pejabat",
        jenis_media="gambar",
        media_url="https://www.instagram.com/p/Dfr0ZdtGMD0/",
    )
    konteks = KonteksSinyal(
        ocr_teks=[],
        watermark=[],
        keyframe_urls=["https://netra-api.tokorejeki.my.id/media-sementara/abc"],
    )
    cari_sumber(k, konteks=konteks)
    assert panggilan_lens == [("https://netra-api.tokorejeki.my.id/media-sementara/abc", False)]


def test_buat_query_tanpa_tanda_kutip_tidak_mengisi_kutipan(monkeypatch):
    from search import queries

    monkeypatch.setattr(
        "llm.tanya_json",
        lambda *a, **kw: {
            "kutipan": ["Gibran berkomentar bahwa ia akan bermain GTA 6"],
            "keyword": ["Gibran komentar GTA 6", "Gibran main GTA VI"],
        },
    )
    q_tanpa = queries.buat_query("Gibran berkomentar bahwa ia akan bermain GTA 6")
    assert q_tanpa["kutipan"] == []
    assert q_tanpa["keyword"] == ["Gibran komentar GTA 6", "Gibran main GTA VI"]

    monkeypatch.setattr(
        "llm.tanya_json",
        lambda *a, **kw: {
            "kutipan": ["Saya siap bermain GTA 6 November nanti"],
            "keyword": ["Gibran GTA 6"],
        },
    )
    q_dengan = queries.buat_query('Gibran bilang "Saya siap bermain GTA 6 November nanti"')
    assert q_dengan["kutipan"] == ["Saya siap bermain GTA 6 November nanti"]


def test_cari_sumber_gambar_carousel_kirim_multi_slide_ke_lens(monkeypatch):
    import config
    from search import KonteksSinyal, cari_sumber, web_search

    monkeypatch.setattr(config, "SERPAPI_KEY", "dummy-serp")
    panggilan_lens = []
    monkeypatch.setattr(web_search, "cari_google", lambda q, kutipan=False, maks=8: [])
    monkeypatch.setattr(
        web_search,
        "reverse_image",
        lambda url_g, maks=8, untuk_video=False: (
            panggilan_lens.append((url_g, untuk_video))
            or [
                Temuan(
                    f"https://kompas.com/read/{url_g[-1]}",
                    "frame_match",
                    0.8,
                    jenis_sumber="media",
                    dari_lens=True,
                )
            ]
        ),
    )

    k = klaim(
        claim_id="ig_multi",
        teks_klaim="Postingan carousel Instagram",
        jenis_media="gambar",
        media_url="https://www.instagram.com/p/CAROUSEL1/",
    )
    slides = [f"https://netra-api.tokorejeki.my.id/media-sementara/s{i}" for i in range(1, 5)]
    hasil, _ = cari_sumber(k, konteks=KonteksSinyal(keyframe_urls=slides))
    assert panggilan_lens == [(u, False) for u in slides]
    assert len(hasil.kandidat) == 4


def test_jenis_sumber_media_diperluas_dan_prefiks_kanal():
    assert sources.jenis_sumber("https://www.nu.or.id/amp/nasional/kesaksian-ugm") == "media"
    assert sources.jenis_sumber("https://tirto.id/cek-fakta-contoh") == "media"
    assert sources.jenis_sumber("https://katadata.co.id/berita/1") == "media"
    assert sources.jenis_sumber("https://mafindo.or.id/klarifikasi") == "media"
    assert sources.jenis_sumber("https://www.facebook.com/watch/?v=1", "Facebook · BBC News Indonesia") == "media"
    assert sources.jenis_sumber("https://www.instagram.com/p/abc/", "Instagram · @kompastv") == "media"
    assert sources.jenis_sumber("https://www.facebook.com/p/puspen/", "Facebook · Puspen TNI") == "resmi"
    # Akun pribadi di media sosial tetap diklasifikasikan sebagai pribadi
    assert sources.jenis_sumber("https://www.facebook.com/ryan.c.julianda/posts/1", "Facebook · Ryan C. Julianda") == "pribadi"


def test_cari_google_teruskan_source_ke_jenis_sumber(monkeypatch):
    import httpx
    from search import web_search

    monkeypatch.setattr(
        web_search,
        "_serpapi",
        lambda p: {
            "organic_results": [
                {
                    "link": "https://www.facebook.com/bbcnewsindonesia/videos/123/",
                    "title": "Liputan Demonstrasi UGM",
                    "snippet": "Laporan wartawan di lokasi.",
                    "source": "Facebook · BBC News Indonesia",
                },
                {
                    "link": "https://www.facebook.com/budi.santoso/posts/456/",
                    "title": "Status warganet",
                    "snippet": "Opini pribadi.",
                    "source": "Facebook · Budi Santoso",
                },
            ]
        },
    )
    hasil = web_search.cari_google("demonstrasi ugm")
    assert len(hasil) == 2
    assert hasil[0].jenis_sumber == "media"
    assert hasil[0].uploader == "Facebook · BBC News Indonesia"
    assert hasil[1].jenis_sumber == "pribadi"


def test_siapkan_dan_info_video_fallback_instagram_embed_mixed_carousel(tmp_path, monkeypatch):
    import json
    from contextlib import contextmanager
    import httpx
    import yt_dlp
    import config
    from search import frames

    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError("No video formats found!")

        def download(self, urls):
            raise RuntimeError("No video formats found!")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    ctx = {
        "gql_data": {
            "shortcode_media": {
                "__typename": "GraphSidecar",
                "shortcode": "DfkhFTFE8c3",
                "taken_at_timestamp": 1794600000,
                "owner": {"username": "persma.ugm"},
                "edge_media_to_caption": {
                    "edges": [{"node": {"text": "Kronologi kericuhan di sekitar kampus UGM."}}]
                },
                "edge_sidecar_to_children": {
                    "edges": [
                        {"node": {"is_video": False, "video_url": False, "display_url": "https://cdn.ig.test/cover.jpg"}},
                        {"node": {"is_video": True, "video_url": "https://cdn.ig.test/slide2.mp4", "display_url": "https://cdn.ig.test/slide2.jpg"}},
                    ]
                },
            }
        }
    }
    html_embed = f'<script>"contextJSON":{json.dumps(json.dumps(ctx))}</script>'

    def fake_get(url, follow_redirects=True, timeout=None, headers=None):
        assert "/embed/captioned/" in url
        return httpx.Response(
            200,
            text=html_embed,
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request("GET", url),
        )

    @contextmanager
    def fake_stream(method, url, follow_redirects=True, timeout=None, headers=None):
        assert url == "https://cdn.ig.test/slide2.mp4"
        yield httpx.Response(
            200,
            content=b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",
            headers={"content-type": "video/mp4", "content-length": "24"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.stream", fake_stream)

    url_ig = "https://www.instagram.com/p/DfkhFTFE8c3/?srtk=abc"
    info = frames.info_video(url_ig)
    assert info.uploader == "persma.ugm"
    assert "Kronologi kericuhan" in info.judul
    assert info.tanggal_unggah is not None and info.tanggal_unggah.year == 2026

    path_vid = frames.siapkan_video(url_ig)
    assert path_vid.exists()
    assert path_vid.name == "video.mp4"
    assert path_vid.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
