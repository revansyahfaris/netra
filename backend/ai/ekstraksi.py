"""Ekstraksi sinyal media (audio & keyframes) untuk Lapisan AI Tahap 1 & 2.

Menggunakan ffmpeg/ffprobe dan memanfaatkan cache unduhan video dari search.frames.
Berbeda dari search.frames (yang memotong tepi 10% untuk pHash), keyframes di sini
disimpan utuh tanpa crop tepi agar teks overlay, tanggal, dan watermark tetap terbaca OCR.
"""

import hashlib
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import config
from search import frames

log = logging.getLogger("netra.ai.ekstraksi")

MAKS_DETIK_EKSTRAKSI = 180.0
MAKS_DETIK_EMBEDDING = 120.0  # batas durasi input video Gemini Embedding 2


class EkstraksiError(Exception):
    pass


@dataclass
class HasilEkstraksi:
    sumber: str
    folder_kerja: Path
    audio_path: Path | None = None
    keyframes: list[tuple[float, Path]] = field(default_factory=list)
    durasi: float | None = None


def _cek_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise EkstraksiError("ffmpeg belum terpasang")


def _folder_kerja(sumber: str) -> Path:
    folder = config.WORK_DIR / f"ai_{hashlib.md5(sumber.encode()).hexdigest()[:12]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _siapkan_video(sumber: str) -> Path:
    try:
        return frames.siapkan_video(sumber)
    except frames.VideoError as e:
        raise EkstraksiError(str(e)) from e


def durasi_video(video: Path) -> float | None:
    """Ambil durasi video (detik) menggunakan ffprobe."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (subprocess.SubprocessError, ValueError):
        return None


def ada_audio(video: Path) -> bool:
    """Periksa apakah file media memiliki track audio."""
    if not shutil.which("ffprobe"):
        return True
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return bool(out.stdout.strip())
    except subprocess.SubprocessError:
        return True


def detik_dari_cuplikan(cuplikan: str | None) -> float:
    """Konversi penanda timestamp ('01:12' atau '01:02:03') ke detik; 0.0 jika bukan timestamp."""
    if not cuplikan:
        return 0.0
    bagian = cuplikan.strip().split(":")
    if len(bagian) not in (2, 3) or not all(b.isdigit() for b in bagian):
        return 0.0
    angka = [int(b) for b in bagian]
    if len(angka) == 2:
        return float(angka[0] * 60 + angka[1])
    return float(angka[0] * 3600 + angka[1] * 60 + angka[2])


def ekstrak_audio(
    video: Path,
    mulai_detik: float = 0.0,
    durasi_maks: float = MAKS_DETIK_EKSTRAKSI,
    output: Path | None = None,
) -> Path | None:
    """Ekstrak track audio ke WAV 16 kHz mono untuk Whisper. Mengembalikan None jika video bisu."""
    _cek_ffmpeg()
    if not video.exists():
        raise EkstraksiError(f"File video tidak ditemukan: {video}")
    if not ada_audio(video):
        log.info("Video tanpa track audio, STT dilewati: %s", video.name)
        return None

    target = output or (_folder_kerja(str(video)) / "audio_16k.wav")
    target.parent.mkdir(parents=True, exist_ok=True)
    mulai = max(0.0, mulai_detik)

    cmd = ["ffmpeg", "-v", "error", "-y"]
    if mulai > 0:
        cmd += ["-ss", str(mulai)]
    cmd += [
        "-i", str(video),
        "-t", str(durasi_maks),
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
        str(target),
    ]
    hasil = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if hasil.returncode != 0:
        stderr = hasil.stderr.lower()
        if "does not contain any stream" in stderr or "no audio" in stderr:
            return None
        raise EkstraksiError(f"Ekstraksi audio gagal: {hasil.stderr[:200]}")
    if not target.exists() or target.stat().st_size <= 44:
        return None
    return target


def ekstrak_keyframes(
    video: Path,
    mulai_detik: float = 0.0,
    durasi_maks: float = MAKS_DETIK_EKSTRAKSI,
    interval_detik: float = 2.0,
    maks_frame: int = 12,
    lebar_maks: int = 1024,
    output_dir: Path | None = None,
) -> list[tuple[float, Path]]:
    """Ekstrak keyframes full-frame (tanpa crop tepi) untuk OCR Gemini.

    Jika segmen panjang, interval otomatis disesuaikan agar jumlah frame tidak melebihi `maks_frame`.
    """
    _cek_ffmpeg()
    if not video.exists():
        raise EkstraksiError(f"File video tidak ditemukan: {video}")
    if interval_detik <= 0 or maks_frame <= 0:
        raise EkstraksiError("interval_detik dan maks_frame harus lebih besar dari 0")

    folder = output_dir or (_folder_kerja(str(video)) / "keyframes_ocr")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)

    mulai = max(0.0, mulai_detik)
    total_durasi = durasi_video(video)
    jendela = durasi_maks
    if total_durasi is not None:
        sisa = max(total_durasi - mulai, 0.5)
        jendela = min(durasi_maks, sisa)

    interval_efektif = max(interval_detik, jendela / maks_frame)
    fps = 1.0 / interval_efektif

    cmd = ["ffmpeg", "-v", "error", "-y"]
    if mulai > 0:
        cmd += ["-ss", str(mulai)]
    cmd += [
        "-i", str(video),
        "-t", str(durasi_maks),
        "-vf", f"fps={fps:.6f},scale='min({lebar_maks},iw)':-2",
        "-frames:v", str(maks_frame),
        "-q:v", "2",
        str(folder / "kf_%04d.jpg"),
    ]
    hasil = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if hasil.returncode != 0:
        raise EkstraksiError(f"Ekstraksi keyframes gagal: {hasil.stderr[:200]}")

    daftar = sorted(folder.glob("kf_*.jpg"))
    if not daftar:
        raise EkstraksiError("Tidak ada keyframe yang berhasil diekstrak")
    return [(round(mulai + i * interval_efektif, 2), path) for i, path in enumerate(daftar)]


def potong_segmen(
    video: Path,
    mulai_detik: float = 0.0,
    durasi_maks: float = MAKS_DETIK_EMBEDDING,
    output: Path | None = None,
) -> Path:
    """Potong segmen video (maks 120 detik untuk Gemini Embedding 2 / pemotongan di sekitar cuplikan)."""
    _cek_ffmpeg()
    if not video.exists():
        raise EkstraksiError(f"File video tidak ditemukan: {video}")

    target = output or (_folder_kerja(str(video)) / f"segmen_{int(max(0.0, mulai_detik))}.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    mulai = max(0.0, mulai_detik)

    cmd = ["ffmpeg", "-v", "error", "-y"]
    if mulai > 0:
        cmd += ["-ss", str(mulai)]
    cmd += ["-i", str(video), "-t", str(durasi_maks), "-c", "copy", str(target)]
    hasil = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if hasil.returncode != 0 or not target.exists():
        raise EkstraksiError(f"Pemotongan video gagal: {hasil.stderr[:200]}")
    return target


def ekstrak_sinyal_media(
    sumber: str,
    mulai_detik: float = 0.0,
    durasi_maks: float = MAKS_DETIK_EKSTRAKSI,
    interval_detik: float = 2.0,
    maks_frame: int = 12,
) -> HasilEkstraksi:
    """Orkestrasi Tahap 1 untuk video (URL atau path lokal): siapkan file -> ekstrak audio + keyframes."""
    video = _siapkan_video(sumber)
    folder = _folder_kerja(sumber)
    durasi = durasi_video(video)
    audio = ekstrak_audio(video, mulai_detik=mulai_detik, durasi_maks=durasi_maks, output=folder / "audio_16k.wav")
    keyframes = ekstrak_keyframes(
        video,
        mulai_detik=mulai_detik,
        durasi_maks=durasi_maks,
        interval_detik=interval_detik,
        maks_frame=maks_frame,
        output_dir=folder / "keyframes_ocr",
    )
    return HasilEkstraksi(
        sumber=sumber,
        folder_kerja=folder,
        audio_path=audio,
        keyframes=keyframes,
        durasi=durasi,
    )

