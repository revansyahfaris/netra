"""Klien Speech-to-Text (STT) menuju layanan Whisper Docker (Speaches).

Secara default memanggil http://localhost:8100/v1/audio/transcriptions
menggunakan model deepdml/faster-whisper-large-v3-turbo-ct2.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

import config
import llm

log = logging.getLogger("netra.ai.stt")

MAKS_BYTES_AUDIO_GEMINI = 15 * 1024 * 1024

SCHEMA_STT_GEMINI = {
    "type": "OBJECT",
    "properties": {
        "text": {"type": "STRING"},
        "language": {"type": "STRING"},
        "segments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start": {"type": "NUMBER"},
                    "end": {"type": "NUMBER"},
                    "text": {"type": "STRING"},
                },
                "required": ["start", "end", "text"],
            },
        },
    },
    "required": ["text", "segments"],
}

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

    return _bangun_hasil_stt(hasil, sumber_stt="whisper_docker")


def _angka_detik(nilai: object) -> float:
    try:
        return round(max(0.0, float(nilai)), 2)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _bangun_hasil_stt(
    hasil: dict,
    sumber_stt: str,
    default_bahasa: str | None = None,
) -> HasilSTT:
    segmen: list[SegmenTranskrip] = []
    for item in hasil.get("segments") or []:
        if not isinstance(item, dict):
            continue
        teks_segmen = str(item.get("text", "")).strip()
        if not teks_segmen:
            continue
        mulai = _angka_detik(item.get("start", 0.0))
        selesai = _angka_detik(item.get("end", mulai))
        segmen.append(SegmenTranskrip(start=mulai, end=max(mulai, selesai), text=teks_segmen))

    teks_utuh = str(hasil.get("text", "")).strip() or " ".join(s.text for s in segmen)
    durasi_mentah = hasil.get("duration")
    try:
        durasi = float(durasi_mentah) if durasi_mentah is not None else None
    except (TypeError, ValueError):
        durasi = None
    return HasilSTT(
        teks=teks_utuh,
        segmen=segmen,
        bahasa=hasil.get("language") or default_bahasa,
        durasi=durasi,
        sumber_stt=sumber_stt,
    )


def _prompt_transkrip_gemini(bahasa: str | None) -> str:
    aturan_bahasa = (
        f"Bahasa utama ucapan adalah '{bahasa}' (kode ISO-639-1). Transkripsikan apa adanya sesuai ucapan asli tanpa menerjemahkan."
        if bahasa
        else "Deteksi bahasa ucapan aslinya dan transkripsikan apa adanya tanpa menerjemahkan."
    )
    return (
        "Transkripsikan ucapan dalam file audio ini secara akurat dan verbatim untuk verifikasi fakta.\n"
        f"{aturan_bahasa}\n"
        "Aturan:\n"
        "- Jangan mengarang kata yang tidak diucapkan; jika hanya musik/hening tanpa ucapan, isi `text` dengan string kosong `\"\"` dan `segments` kosong `[]`.\n"
        "- Isi `text` dengan transkrip lengkap, `language` dengan kode bahasa (mis. `id`), dan `segments` berisi potongan kalimat berurutan dengan timestamp `start` & `end` dalam detik."
    )


def transkrip_audio_gemini(
    audio_path: Path | None,
    bahasa: str | None = "id",
    model: str | None = None,
) -> HasilSTT:
    """Transkripsikan audio memakai Gemini Flash-Lite multimodal sebagai fallback STT."""
    if audio_path is None:
        return HasilSTT(teks="", segmen=[], sumber_stt="kosong")
    if not audio_path.exists():
        raise STTError(f"File audio tidak ditemukan: {audio_path}")
    if audio_path.stat().st_size > MAKS_BYTES_AUDIO_GEMINI:
        batas_mb = MAKS_BYTES_AUDIO_GEMINI // (1024 * 1024)
        raise STTError(f"Ukuran audio melebihi batas inline Gemini ({batas_mb} MB)")

    mime = MIME_AUDIO.get(audio_path.suffix.lower())
    model_id = model or config.STT_GEMINI_MODEL
    try:
        mentah = llm.tanya_multimodal_json(
            [llm.part_teks(_prompt_transkrip_gemini(bahasa)), llm.part_file(audio_path, mime_type=mime)],
            suhu=0.0,
            skema=SCHEMA_STT_GEMINI,
            timeout=config.STT_TIMEOUT,
            model=model_id,
            thinking="minimal",
        )
        if not isinstance(mentah, dict):
            raise ValueError("Respons STT Gemini bukan JSON object")
    except (llm.LLMError, ValueError, TypeError) as e:
        log.warning("Fallback STT Gemini gagal: %s", e)
        raise STTError(str(e)) from e

    return _bangun_hasil_stt(mentah, sumber_stt="gemini", default_bahasa=bahasa)

