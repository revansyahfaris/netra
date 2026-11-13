"""Tes Tahap 1 modul OCR & deduplikasi Gemini serta klien multimodal llm.py."""

import json

import httpx
import pytest

import config
import llm
from ai import HasilOCR, ItemTeksOCR, OCRError, deduplikasi_item, ocr_gambar, ocr_keyframes
from ai.ocr import SCHEMA_OCR


def test_llm_multimodal_mengirim_inlinedata_dan_schema(tmp_path, monkeypatch):
    img = tmp_path / "f1.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0dummy")
    tangkapan = {}

    def fake_post(url, params=None, json=None, timeout=None):
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
