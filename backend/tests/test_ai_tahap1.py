"""Tes Tahap 1 modul AI (ekstraksi media & klien STT). Jalankan: pytest -q"""

import shutil
import subprocess
from types import SimpleNamespace

import httpx
import pytest

import config
from ai import (
    EkstraksiError,
    STTError,
    cek_kesehatan,
    detik_dari_cuplikan,
    ekstrak_audio,
    ekstrak_keyframes,
    ekstrak_sinyal_media,
    transkrip_audio,
)


def test_default_config_stt_mengarah_ke_8100():
    assert config.STT_BASE_URL == "http://localhost:8100"
    assert config.stt_aktif() is True


@pytest.mark.parametrize(
    "cuplikan,detik",
    [
        ("00:42", 42.0),
        ("01:12", 72.0),
        ("01:02:03", 3723.0),
        (None, 0.0),
        ("Kutipan biasa tanpa timestamp", 0.0),
    ],
)
def test_detik_dari_cuplikan(cuplikan, detik):
    assert detik_dari_cuplikan(cuplikan) == detik


def test_ekstrak_audio_video_bisu_mengembalikan_none(tmp_path, monkeypatch):
    video = tmp_path / "bisu.mp4"
    video.write_bytes(b"dummy")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("ai.ekstraksi.ada_audio", lambda p: False)

    assert ekstrak_audio(video) is None


def test_ekstrak_audio_perintah_ffmpeg(tmp_path, monkeypatch):
    video = tmp_path / "klip.mp4"
    video.write_bytes(b"dummy")
    out = tmp_path / "out.wav"
    dipanggil = {}

    def fake_run(cmd, **kwargs):
        dipanggil["cmd"] = cmd
        out.write_bytes(b"RIFF" + b"\x00" * 100)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("ai.ekstraksi.ada_audio", lambda p: True)
    monkeypatch.setattr("subprocess.run", fake_run)

    hasil = ekstrak_audio(video, mulai_detik=15.0, durasi_maks=60.0, output=out)
    assert hasil == out
    cmd = dipanggil["cmd"]
    assert "-ss" in cmd and "15.0" in cmd
    assert "-ar" in cmd and "16000" in cmd
    assert "-ac" in cmd and "1" in cmd


def test_ekstrak_keyframes_tanpa_crop_dan_patuhi_maks_frame(tmp_path, monkeypatch):
    video = tmp_path / "klip.mp4"
    video.write_bytes(b"dummy")
    out_dir = tmp_path / "kf"
    dipanggil = {}

    def fake_run(cmd, **kwargs):
        dipanggil["cmd"] = cmd
        out_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1, 7):
            (out_dir / f"kf_{i:04d}.jpg").write_bytes(b"jpg")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("ai.ekstraksi.durasi_video", lambda p: 120.0)
    monkeypatch.setattr("subprocess.run", fake_run)

    hasil = ekstrak_keyframes(video, interval_detik=2.0, maks_frame=6, output_dir=out_dir)
    cmd_str = " ".join(dipanggil["cmd"])
    assert "crop=" not in cmd_str  # OCR butuh frame utuh tanpa pemotongan tepi
    assert "fps=0.050000" in cmd_str  # 120s / 6 frame = 1 frame tiap 20s (0.05 fps)
    assert len(hasil) == 6
    assert hasil[0][0] == 0.0 and hasil[1][0] == 20.0


def test_transkrip_audio_none_mengembalikan_kosong():
    hasil = transkrip_audio(None)
    assert hasil.teks == ""
    assert hasil.segmen == []
    assert hasil.sumber_stt == "kosong"


def test_transkrip_audio_file_tidak_ada(tmp_path):
    with pytest.raises(STTError):
        transkrip_audio(tmp_path / "tidak_ada.wav")


def test_transkrip_audio_sukses(tmp_path, monkeypatch):
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"RIFF\x00\x00")
    tangkapan = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        tangkapan["url"] = url
        tangkapan["headers"] = headers
        tangkapan["data"] = data
        return httpx.Response(
            200,
            json={
                "text": "TNI tetap netral.",
                "language": "id",
                "duration": 3.5,
                "segments": [
                    {"start": 0.0, "end": 1.8, "text": " TNI tetap "},
                    {"start": 1.8, "end": 3.5, "text": " netral. "},
                ],
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr(config, "STT_API_KEY", "rahasia-netra")
    hasil = transkrip_audio(audio)

    assert tangkapan["url"] == "http://localhost:8100/v1/audio/transcriptions"
    assert tangkapan["headers"] == {"Authorization": "Bearer rahasia-netra"}
    assert tangkapan["data"]["model"] == config.STT_MODEL
    assert tangkapan["data"]["response_format"] == "verbose_json"
    assert tangkapan["data"]["temperature"] == "0.0"
    assert hasil.teks == "TNI tetap netral."
    assert len(hasil.segmen) == 2
    assert hasil.segmen[0].start == 0.0 and hasil.segmen[0].text == "TNI tetap"


def test_cek_kesehatan_kirim_api_key(monkeypatch):
    tangkapan = {}

    def fake_get(url, headers=None, timeout=None):
        tangkapan["headers"] = headers
        return httpx.Response(200, text="OK", request=httpx.Request("GET", url))

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr(config, "STT_API_KEY", "kunci-stt")
    assert cek_kesehatan() is True
    assert tangkapan["headers"] == {"Authorization": "Bearer kunci-stt"}


def test_transkrip_audio_error_http(tmp_path, monkeypatch):
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"RIFF\x00\x00")

    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.post", fake_post)
    with pytest.raises(STTError):
        transkrip_audio(audio)


# ---------- Integrasi ffmpeg nyata (jika terpasang) ----------

butuh_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg tidak ada")


@butuh_ffmpeg
def test_ekstraksi_nyata_dengan_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    vid = tmp_path / "contoh.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:size=640x360:rate=10:d=4",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=4",
            "-shortest", str(vid),
        ],
        check=True,
    )
    hasil = ekstrak_sinyal_media(str(vid), interval_detik=1.0, maks_frame=5)
    assert hasil.audio_path is not None and hasil.audio_path.exists()
    assert len(hasil.keyframes) >= 3
    assert all(p.exists() for _, p in hasil.keyframes)

