"""Klien Speech-to-Text (STT) menuju layanan Whisper Docker (Speaches).

Secara default memanggil http://localhost:8100/v1/audio/transcriptions
menggunakan model deepdml/faster-whisper-large-v3-turbo-ct2.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

import config

log = logging.getLogger("netra.ai.stt")

MIME_AUDIO = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


class STTError(Exception):
    pass


@dataclass
class SegmenTranskrip:
    start: float
    end: float
    text: str


@dataclass
class HasilSTT:
    teks: str
    segmen: list[SegmenTranskrip] = field(default_factory=list)
    bahasa: str | None = None
    durasi: float | None = None
    sumber_stt: str = "whisper_docker"


def _headers(api_key: str | None = None) -> dict[str, str]:
    key = (config.STT_API_KEY if api_key is None else api_key).strip()
    return {"Authorization": f"Bearer {key or 'local'}"}


def cek_kesehatan(base_url: str | None = None, api_key: str | None = None) -> bool:
    """Periksa apakah container STT merespons /health."""
    url = (base_url or config.STT_BASE_URL).rstrip("/")
    if not url:
        return False
    try:
        r = httpx.get(f"{url}/health", headers=_headers(api_key), timeout=5.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def transkrip_audio(
    audio_path: Path | None,
    bahasa: str | None = "id",
    base_url: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    api_key: str | None = None,
) -> HasilSTT:
    """Transkripsikan file audio menjadi teks dan daftar segmen ber-timestamp."""
    if audio_path is None:
        return HasilSTT(teks="", segmen=[], sumber_stt="kosong")
    if not audio_path.exists():
        raise STTError(f"File audio tidak ditemukan: {audio_path}")

    url = (base_url or config.STT_BASE_URL).rstrip("/")
    if not url:
        raise STTError("STT_BASE_URL belum diisi")
    model_id = model or config.STT_MODEL
    mime = MIME_AUDIO.get(audio_path.suffix.lower(), "application/octet-stream")

    data = {
        "model": model_id,
        "response_format": "verbose_json",
        "temperature": str(temperature),
    }
    if bahasa:
        data["language"] = bahasa

    try:
        with audio_path.open("rb") as f:
            r = httpx.post(
                f"{url}/v1/audio/transcriptions",
                headers=_headers(api_key),
                files={"file": (audio_path.name, f, mime)},
                data=data,
                timeout=config.STT_TIMEOUT,
            )
        r.raise_for_status()
        hasil = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Panggilan STT gagal: %s", e)
        raise STTError(str(e)) from e

    segmen = [
        SegmenTranskrip(
            start=round(float(s.get("start", 0.0)), 2),
            end=round(float(s.get("end", 0.0)), 2),
            text=str(s.get("text", "")).strip(),
        )
        for s in (hasil.get("segments") or [])
        if str(s.get("text", "")).strip()
    ]
    return HasilSTT(
        teks=str(hasil.get("text", "")).strip(),
        segmen=segmen,
        bahasa=hasil.get("language"),
        durasi=hasil.get("duration"),
        sumber_stt="whisper_docker",
    )

