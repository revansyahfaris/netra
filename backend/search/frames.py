"""Pencocokan video: frame (perceptual hash) dan audio (envelope cross-correlation).

Butuh ffmpeg terpasang di sistem. Unduh video lewat yt-dlp (YouTube, TikTok, X, IG, dll.).
Semua fungsi menerima URL maupun path file lokal (berguna untuk demo dan tes).
"""

import hashlib
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

import config
from url_kanonis import normalisasi_url

from . import dates, instagram, sources

log = logging.getLogger("netra.frames")

FPS_VIRAL = 1             # video viral: 1 frame per detik
FPS_KANDIDAT = 4          # kandidat lebih rapat supaya tidak meleset karena beda titik potong
FPS_KASAR_PANJANG = 0.5   # scan awal hemat untuk video > 3 menit (1 frame per 2 detik)
MAKS_DETIK = 180          # panjang satu jendela rapat (3 menit)
MAKS_DETIK_PANJANG = 1800 # batas scan kasar video panjang (30 menit)
JARAK_MIRIP = 10          # jarak pHash (0-64) <= ini dianggap frame yang sama
JARAK_BEDA = 24           # jarak >= ini dianggap frame berbeda
ENVELOPE_DETIK = 0.25     # resolusi envelope audio


class VideoError(Exception):
    pass


@dataclass
class InfoVideo:
    url: str
    judul: str = ""
    uploader: str | None = None
    tanggal_unggah: object = None   # datetime | None
    resolusi: int | None = None
    durasi: float | None = None


@dataclass
class HasilCocok:
    kemiripan: float
    detik_kandidat: float | None
    kecocokan_audio: float | None


def _cek_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise VideoError("ffmpeg belum terpasang")


def _folder_kerja(sumber: str) -> Path:
    kunci = sumber if Path(sumber).exists() else (normalisasi_url(sumber) or sumber)
    folder = config.WORK_DIR / hashlib.md5(kunci.encode()).hexdigest()[:12]
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _detik_ke_teks(detik: float) -> str:
    detik = int(detik)
    return f"{detik // 60:02d}:{detik % 60:02d}"


# ---------- Info & unduh ----------

def _info_video_instagram_embed(sumber: str) -> InfoVideo | None:
    info = instagram.ambil_info_instagram_embed(sumber)
    if not info or not info.video_urls:
        return None
    return InfoVideo(
        url=normalisasi_url(sumber) or sumber,
        judul=info.caption[:120],
        uploader=info.uploader,
        tanggal_unggah=info.tanggal_unggah,
    )


def _unduh_video_instagram_embed(sumber: str, folder: Path) -> Path | None:
    info = instagram.ambil_info_instagram_embed(sumber)
    if not info or not info.video_urls:
        return None
    for video_url in info.video_urls:
        try:
            return instagram.unduh_video_url(video_url, folder / "video.mp4")
        except Exception as e:
            log.debug("Fallback unduh video embed Instagram gagal (%s): %s", video_url[:60], e)
    return None


def info_video(sumber: str) -> InfoVideo:
    """Metadata tanpa mengunduh: tanggal unggah, resolusi tertinggi, uploader."""
    p = Path(sumber)
    if p.exists():
        meta = _ffprobe(p)
        return InfoVideo(url=sumber, judul=p.name, resolusi=meta.get("tinggi"), durasi=meta.get("durasi"))
    try:
        import yt_dlp
    except ImportError as e:
        if ig := _info_video_instagram_embed(sumber):
            return ig
        raise VideoError("yt-dlp belum terpasang") from e
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            d = ydl.extract_info(sumber, download=False)
    except Exception as e:  # yt-dlp melempar banyak jenis error
        if ig := _info_video_instagram_embed(sumber):
            return ig
        raise VideoError(f"Gagal membaca info video: {e}") from e
    tinggi = max((f.get("height") or 0 for f in d.get("formats") or []), default=0) or d.get("height")
    return InfoVideo(
        url=d.get("webpage_url") or sumber,
        judul=d.get("title", ""),
        uploader=d.get("channel") or d.get("uploader"),
        tanggal_unggah=dates.parse(d.get("upload_date")),
        resolusi=tinggi or None,
        durasi=d.get("duration"),
    )


def siapkan_video(sumber: str) -> Path:
    """Kembalikan path video lokal; unduh versi resolusi rendah kalau sumbernya URL."""
    p = Path(sumber)
    if p.exists():
        return p
    folder = _folder_kerja(sumber)
    ada = list(folder.glob("video.*"))
    if ada:
        return ada[0]
    try:
        import yt_dlp
    except ImportError as e:
        if ig_path := _unduh_video_instagram_embed(sumber, folder):
            return ig_path
        raise VideoError("yt-dlp belum terpasang") from e
    opsi = {
        "quiet": True,
        "no_warnings": True,
        "format": (
            "worst[height>=240][acodec!=none]/"
            "worstvideo[height>=240]+worstaudio/"
            "worst[acodec!=none]/worstvideo+worstaudio/worst"
        ),
        "merge_output_format": "mp4",
        "outtmpl": str(folder / "video.%(ext)s"),
        "max_filesize": instagram.MAKS_BYTES_VIDEO,
    }
    try:
        with yt_dlp.YoutubeDL(opsi) as ydl:
            ydl.download([sumber])
    except Exception as e:
        # yt-dlp sering gagal pada carousel campuran / post IG tertentu: fallback ke embed video_url
        if ig_path := _unduh_video_instagram_embed(sumber, folder):
            return ig_path
        raise VideoError(f"Gagal mengunduh video: {e}") from e
    ada = list(folder.glob("video.*"))
    if not ada:
        if ig_path := _unduh_video_instagram_embed(sumber, folder):
            return ig_path
        raise VideoError("Video tidak terunduh")
    return ada[0]


def _ffprobe(path: Path) -> dict:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=height:format=duration", "-of", "default=nw=1", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}
    meta = {}
    for baris in out.splitlines():
        k, _, v = baris.partition("=")
        try:
            if k == "height":
                meta["tinggi"] = int(v)
            elif k == "duration":
                meta["durasi"] = float(v)
        except ValueError:
            pass
    return meta


# ---------- Frame ----------

def hash_frame(
    video: Path,
    fps: float = FPS_VIRAL,
    mulai_detik: float = 0.0,
    durasi: float = MAKS_DETIK,
) -> list[tuple[float, imagehash.ImageHash]]:
    """Ekstrak frame lalu hitung perceptual hash tiap frame.
    Tepi frame dipotong 10% supaya watermark/overlay di pojok tidak mengganggu."""
    _cek_ffmpeg()
    mulai = max(0.0, float(mulai_detik))
    folder = video.parent / f"frames_{video.stem}_{fps}_{int(mulai)}"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    cmd = ["ffmpeg", "-v", "error"]
    if mulai > 0:
        cmd += ["-ss", str(mulai)]
    cmd += [
        "-i", str(video),
        "-t", str(durasi),
        "-vf", f"fps={fps},crop=iw*0.8:ih*0.8,scale=256:-2",
        str(folder / "f_%04d.jpg"),
    ]
    hasil = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if hasil.returncode != 0:
        raise VideoError(f"ffmpeg gagal: {hasil.stderr[:200]}")
    frame = sorted(folder.glob("f_*.jpg"))
    if not frame:
        raise VideoError("Tidak ada frame yang bisa diambil")
    return [(mulai + i / fps, imagehash.phash(Image.open(f))) for i, f in enumerate(frame)]


def cocokkan_frame(viral, kandidat) -> tuple[float, float | None]:
    """Rata-rata kemiripan tiap frame viral terhadap frame kandidat terdekat (0-1),
    plus detik di video kandidat tempat potongan viral DIMULAI (dari voting selisih waktu)."""
    if not viral or not kandidat:
        return 0.0, None
    skor, selisih = [], []
    for t_viral, h in viral:
        d, t_kand = min((h - hk, t) for t, hk in kandidat)
        skor.append(min(1.0, max(0.0, (JARAK_BEDA - d) / (JARAK_BEDA - JARAK_MIRIP))))
        if d <= JARAK_MIRIP + 4:
            selisih.append(t_kand - t_viral)
    mulai = None
    if selisih:
        # Ambil selisih yang paling banyak "disetujui" frame lain (toleransi 1 detik)
        mulai = max(selisih, key=lambda s: sum(abs(s - x) <= 1 for x in selisih))
        mulai = max(mulai, 0.0)
    return round(float(np.mean(skor)), 3), mulai


# ---------- Audio ----------

def envelope_audio(
    video: Path,
    mulai_detik: float = 0.0,
    durasi: float = MAKS_DETIK,
) -> np.ndarray | None:
    """Energi audio per 0.25 detik (None kalau video tanpa suara)."""
    _cek_ffmpeg()
    sr = 8000
    mulai = max(0.0, float(mulai_detik))
    cmd = ["ffmpeg", "-v", "error"]
    if mulai > 0:
        cmd += ["-ss", str(mulai)]
    cmd += ["-i", str(video), "-t", str(durasi), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    hasil = subprocess.run(cmd, capture_output=True, timeout=180)
    if hasil.returncode != 0 or not hasil.stdout:
        return None
    x = np.frombuffer(hasil.stdout, dtype=np.int16).astype(np.float32)
    n = int(sr * ENVELOPE_DETIK)
    if len(x) < n * 8:
        return None
    x = x[: len(x) // n * n].reshape(-1, n)
    env = np.sqrt((x ** 2).mean(axis=1))
    if env.std() < 1e-6:
        return None
    return (env - env.mean()) / env.std()


def cocokkan_audio(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    """Korelasi silang ternormalisasi: potongan pendek digeser di sepanjang yang panjang."""
    if a is None or b is None:
        return None
    pendek, panjang = (a, b) if len(a) <= len(b) else (b, a)
    n = len(pendek)
    if n < 8:
        return None
    terbaik = -1.0
    for mulai in range(0, len(panjang) - n + 1):
        seg = panjang[mulai: mulai + n]
        if seg.std() < 1e-6:
            continue
        seg = (seg - seg.mean()) / seg.std()
        terbaik = max(terbaik, float(np.dot(pendek, seg) / n))
    return round(max(0.0, min(terbaik, 1.0)), 3)


# ---------- Gabungan ----------

def _pilih_jendela_awal(viral, kandidat_kasar, durasi_total: float) -> float:
    """Temukan detik mulai jendela rapat terbaik dari hasil scan kasar video panjang."""
    _, detik = cocokkan_frame(viral, kandidat_kasar)
    if detik is None and viral and kandidat_kasar:
        _, detik = min((h - hk, t) for _, h in viral for t, hk in kandidat_kasar)
    if detik is None:
        return 0.0
    maks_mulai = max(0.0, durasi_total - MAKS_DETIK)
    return min(maks_mulai, max(0.0, float(detik) - 30.0))


def bandingkan(viral_src: str, kandidat_src: str, cache: dict | None = None) -> HasilCocok:
    """Bandingkan video viral dengan satu kandidat. `cache` menyimpan hash viral supaya tidak dihitung ulang."""
    cache = cache if cache is not None else {}
    if "viral" not in cache:
        v = siapkan_video(viral_src)
        cache["viral"] = (hash_frame(v), envelope_audio(v))
    h_viral, a_viral = cache["viral"]

    k = siapkan_video(kandidat_src)
    durasi_k = _ffprobe(k).get("durasi")
    mulai = 0.0
    if durasi_k is not None and durasi_k > MAKS_DETIK:
        batas_kasar = min(float(durasi_k), float(MAKS_DETIK_PANJANG))
        h_kasar = hash_frame(k, fps=FPS_KASAR_PANJANG, mulai_detik=0.0, durasi=batas_kasar)
        mulai = _pilih_jendela_awal(h_viral, h_kasar, float(durasi_k))

    kemiripan, detik = cocokkan_frame(
        h_viral,
        hash_frame(k, FPS_KANDIDAT, mulai_detik=mulai, durasi=MAKS_DETIK),
    )
    audio = cocokkan_audio(a_viral, envelope_audio(k, mulai_detik=mulai, durasi=MAKS_DETIK))
    return HasilCocok(kemiripan, detik, audio)


def temuan_dari_video(viral_src: str, kandidat_src: str, cache: dict | None = None):
    """Hasilkan Temuan lengkap (metadata + kemiripan) untuk satu kandidat video."""
    from .models import Temuan

    info = info_video(kandidat_src)
    cocok = bandingkan(viral_src, kandidat_src, cache)
    return Temuan(
        url=info.url,
        metode="frame_match",
        kemiripan=cocok.kemiripan,
        jenis_sumber=sources.jenis_sumber(info.url, info.uploader),
        judul=info.judul,
        tanggal_unggah=info.tanggal_unggah,
        cuplikan=None if cocok.detik_kandidat is None else _detik_ke_teks(cocok.detik_kandidat),
        resolusi=info.resolusi,
        ada_watermark=sources.perkiraan_watermark(info.url),
        kecocokan_audio=cocok.kecocokan_audio,
        uploader=info.uploader,
        asal="phash",
        kemiripan_frame=cocok.kemiripan,
    )
