"""Tes Tahap 1 modul OCR & deduplikasi Gemini serta klien multimodal llm.py."""

import json

import httpx
import pytest

import config
import llm
from ai import HasilOCR, ItemTeksOCR, OCRError, deduplikasi_item, ocr_gambar, ocr_keyframes
from ai.ocr import SCHEMA_OCR


def test_ocr_keyframes_hybrid_resolusi_sedang_dan_thinking_low(tmp_path, monkeypatch):
    import config
    from PIL import Image
    from ai import ocr

    img = tmp_path / "f1.jpg"
    Image.new("RGB", (32, 32), color=(240, 240, 240)).save(img, format="JPEG")
    tangkapan = {}

    def fake_post(url, params=None, json=None, timeout=None, headers=None):
        tangkapan["url"] = url
        tangkapan["body"] = json
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"items": [{"teks": "CONTOH TEKS", "kategori": "overlay"}], "watermark_terdeteksi": [], "tanggal_di_layar": null}'
                                }
                            ]
                        }
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr(config, "WORK_DIR", tmp_path)
    monkeypatch.setattr(httpx, "post", fake_post)

    hasil = ocr.ocr_keyframes([(1.0, img)])
    assert hasil.teks_unik == ["CONTOH TEKS"]
    gen_cfg = tangkapan["body"]["generationConfig"]
    assert gen_cfg["thinkingConfig"] == {"thinkingLevel": "low"}
    assert gen_cfg["mediaResolution"] == "MEDIA_RESOLUTION_MEDIUM"


def test_llm_multimodal_fallback_http_400_tanpa_media_resolution(tmp_path, monkeypatch):
    import config

    img = tmp_path / "f1.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0dummy")
    panggilan = []

    def fake_post(url, params=None, json=None, timeout=None, headers=None):
        panggilan.append(dict(json["generationConfig"]))
        if len(panggilan) == 1:
            return httpx.Response(
                400,
                json={"error": {"message": 'Unknown name "mediaResolution" at generation_config'}},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr(httpx, "post", fake_post)

    res = llm.tanya_multimodal_json(
        [llm.part_teks("cek"), llm.part_file(img)],
        thinking="low",
        media_resolution="MEDIA_RESOLUTION_MEDIUM",
    )
    assert res == {"ok": True}
    assert len(panggilan) == 2
    assert panggilan[0]["mediaResolution"] == "MEDIA_RESOLUTION_MEDIUM"
    assert "mediaResolution" not in panggilan[1]


def test_llm_multimodal_mengirim_inlinedata_dan_schema(tmp_path, monkeypatch):
    img = tmp_path / "f1.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0dummy")
    tangkapan = {}

    def fake_post(url, params=None, json=None, timeout=None, headers=None):
        tangkapan["url"] = url
        tangkapan["body"] = json
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("httpx.post", fake_post)

    res = llm.tanya_multimodal_json([llm.part_teks("cek"), llm.part_file(img)], skema=SCHEMA_OCR)
    assert res == {"ok": True}
    parts = tangkapan["body"]["contents"][0]["parts"]
    assert parts[0] == {"text": "cek"}
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert tangkapan["body"]["generationConfig"]["responseSchema"] == SCHEMA_OCR


def test_deduplikasi_item_menggabungkan_teks_mirip_dan_rentang_waktu():
    items = [
        ItemTeksOCR(teks="BREAKING: Kejadian di Papua!", kategori="overlay", detik_awal=0.0, detik_akhir=2.0),
        ItemTeksOCR(teks="BREAKING Kejadian di Papua", kategori="overlay", detik_awal=2.0, detik_akhir=6.0),
        ItemTeksOCR(teks="KOMPASTV", kategori="watermark", detik_awal=0.0, detik_akhir=6.0),
    ]
    hasil = deduplikasi_item(items)
    assert len(hasil) == 2
    assert hasil[0].teks == "BREAKING: Kejadian di Papua!"
    assert hasil[0].detik_awal == 0.0 and hasil[0].detik_akhir == 6.0
    assert hasil[1].kategori == "watermark"


def test_ocr_keyframes_kosong_mengembalikan_status_kosong(tmp_path):
    hasil = ocr_keyframes([(0.0, tmp_path / "tidak_ada.jpg")])
    assert hasil.sumber_ocr == "kosong"
    assert hasil.items == [] and hasil.teks_unik == []


def test_ocr_keyframes_structured_output_dan_dedup(tmp_path, monkeypatch):
    f1 = tmp_path / "kf_0001.jpg"
    f2 = tmp_path / "kf_0002.jpg"
    f1.write_bytes(b"jpg1")
    f2.write_bytes(b"jpg2")

    payload_gemini = {
        "items": [
            {"teks": "TNI BUBARKAN WARGA MINGGU INI", "kategori": "overlay", "detik_awal": 0.0, "detik_akhir": 4.0},
            {"teks": "TNI BUBARKAN WARGA MINGGU INI!", "kategori": "overlay", "detik_awal": 4.0, "detik_akhir": 8.0},
            {"teks": "12 Nov 2026", "kategori": "tanggal_layar", "detik_awal": 0.0, "detik_akhir": 8.0},
        ],
        "watermark_terdeteksi": ["@akun.contoh", "@AKUN.CONTOH", "TikTok"],
        "tanggal_di_layar": "12 Nov 2026",
    }

    def fake_post(url, params=None, **kwargs):
        body = kwargs["json"]
        assert body["generationConfig"]["responseSchema"] == SCHEMA_OCR
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload_gemini)}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("httpx.post", fake_post)

    hasil = ocr_keyframes([(0.0, f1), (4.0, f2)])
    assert isinstance(hasil, HasilOCR)
    assert hasil.sumber_ocr == "gemini"
    assert len(hasil.items) == 2  # overlay duplikat digabung, tanggal tetap terpisah
    assert hasil.items[0].detik_awal == 0.0 and hasil.items[0].detik_akhir == 8.0
    assert hasil.teks_unik == ["TNI BUBARKAN WARGA MINGGU INI!", "12 Nov 2026"]
    assert hasil.watermark_terdeteksi == ["@akun.contoh", "TikTok"]
    assert hasil.tanggal_di_layar == "12 Nov 2026"


def test_ocr_keyframes_fallback_saat_api_key_kosong(tmp_path, monkeypatch):
    f1 = tmp_path / "kf_0001.jpg"
    f1.write_bytes(b"jpg1")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")

    hasil = ocr_keyframes([(0.0, f1)], fallback_aman=True)
    assert hasil.sumber_ocr == "gagal"
    assert hasil.catatan and "GEMINI_API_KEY" in hasil.catatan

    with pytest.raises(OCRError):
        ocr_keyframes([(0.0, f1)], fallback_aman=False)


def test_ocr_gambar_url_dan_lokal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")

    def fake_get(url, follow_redirects=True, timeout=None):
        return httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\ndummy",
            headers={"content-type": "image/png"},
            request=httpx.Request("GET", url),
        )

    def fake_post(url, params=None, **kwargs):
        parts = kwargs["json"]["contents"][0]["parts"]
        assert parts[2]["inlineData"]["mimeType"] == "image/png"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "items": [{"teks": "KUTIPAN KASAD", "kategori": "judul_berita"}],
                                            "watermark_terdeteksi": [],
                                            "tanggal_di_layar": None,
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)

    hasil = ocr_gambar("https://example.com/viral/gambar.png")
    assert hasil.sumber_ocr == "gemini"
    assert hasil.teks_unik == ["KUTIPAN KASAD"]


def test_ocr_gambar_ekstrak_og_image_dari_html(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")

    halaman_ig = (
        '<!DOCTYPE html><html><head>'
        '<meta name="twitter:image" content="https://cdn.example.com/foto/ig.jpg?a=1&amp;b=2" />'
        "</head><body>Instagram</body></html>"
    )

    def fake_get(url, follow_redirects=True, timeout=None, headers=None):
        if "instagram.com" in url:
            return httpx.Response(
                200,
                text=halaman_ig,
                headers={"content-type": "text/html; charset=utf-8"},
                request=httpx.Request("GET", url),
            )
        if "cdn.example.com" in url:
            assert "a=1&b=2" in url
            return httpx.Response(
                200,
                content=b"\xff\xd8\xff\xe0dummyjpeg",
                headers={"content-type": "image/jpeg"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200,
            text="<html><body>Halaman tanpa og image</body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    def fake_post(url, params=None, **kwargs):
        parts = kwargs["json"]["contents"][0]["parts"]
        assert parts[2]["inlineData"]["mimeType"] == "image/jpeg"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "items": [{"teks": "BERMAIN GTA VI", "kategori": "overlay"}],
                                            "watermark_terdeteksi": [],
                                            "tanggal_di_layar": None,
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)

    from ai.ocr import path_cache_gambar

    url_ig = "https://www.instagram.com/p/Dfr0ZdtGMD0/"
    hasil = ocr_gambar(url_ig)
    assert hasil.sumber_ocr == "gemini"
    assert hasil.teks_unik == ["BERMAIN GTA VI"]
    cached = path_cache_gambar(url_ig)
    assert cached is not None and cached.read_bytes().startswith(b"\xff\xd8\xff")

    gagal = ocr_gambar("https://example.com/no-preview")
    assert gagal.sumber_ocr == "gagal"
    assert path_cache_gambar("https://example.com/no-preview") is None


def test_ocr_gambar_instagram_carousel_multi_slide(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key")

    ctx = {
        "gql_data": {
            "shortcode_media": {
                "__typename": "GraphSidecar",
                "edge_sidecar_to_children": {
                    "edges": [
                        {"node": {"display_url": f"https://cdn.ig.test/slide_{i}.jpg"}}
                        for i in range(1, 5)
                    ]
                },
            }
        }
    }
    html_embed = f'<script>"contextJSON":{json.dumps(json.dumps(ctx))}</script>'

    def fake_get(url, follow_redirects=True, timeout=None, headers=None):
        if "/embed/captioned/" in url:
            return httpx.Response(
                200,
                text=html_embed,
                headers={"content-type": "text/html; charset=utf-8"},
                request=httpx.Request("GET", url),
            )
        if "cdn.ig.test/slide_" in url:
            nomor = url.rsplit("_", 1)[1][0]
            return httpx.Response(
                200,
                content=b"\xff\xd8\xff\xe0" + nomor.encode(),
                headers={"content-type": "image/jpeg"},
                request=httpx.Request("GET", url),
            )
        raise AssertionError(f"URL tak terduga: {url}")

    parts_terkirim = []

    def fake_post(url, params=None, **kwargs):
        parts = kwargs["json"]["contents"][0]["parts"]
        parts_terkirim.extend(parts)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "items": [
                                                {"teks": "SLIDE PERTAMA BERITA", "kategori": "overlay"},
                                                {"teks": "TANGKAPAN LAYAR KOMENTAR", "kategori": "overlay"},
                                            ],
                                            "watermark_terdeteksi": [],
                                            "tanggal_di_layar": None,
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)

    from ai.ocr import daftar_cache_gambar

    url_post = "https://www.instagram.com/p/CAROUSEL1/?utm_source=ig_web_copy_link"
    hasil = ocr_gambar(url_post)
    assert hasil.sumber_ocr == "gemini"
    assert hasil.teks_unik == ["SLIDE PERTAMA BERITA", "TANGKAPAN LAYAR KOMENTAR"]

    daftar = daftar_cache_gambar(url_post)
    assert [p.name for p in daftar] == ["gambar.jpg", "gambar_02.jpg", "gambar_03.jpg", "gambar_04.jpg"]
    assert [p.read_bytes()[-1:] for p in daftar] == [b"1", b"2", b"3", b"4"]

    gambar_parts = [p for p in parts_terkirim if "inlineData" in p]
    assert len(gambar_parts) == 4
