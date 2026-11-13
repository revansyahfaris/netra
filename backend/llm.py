"""Klien LLM tipis (Gemini lewat REST) yang dipakai bersama semua modul.

Sengaja tanpa SDK supaya tidak bergantung versi library.
Mendukung teks, input multimodal (gambar/audio/video inlineData), dan structured JSON output.
"""

import base64
import json
import logging
import mimetypes
from pathlib import Path

import httpx

import config

log = logging.getLogger("netra.llm")

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MIME_UMUM = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
}


class LLMError(Exception):
    pass


def part_teks(teks: str) -> dict:
    return {"text": teks}


def part_bytes(data: bytes, mime_type: str) -> dict:
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(data).decode("ascii"),
        }
    }


def part_file(path: Path, mime_type: str | None = None) -> dict:
    if not path.exists():
        raise LLMError(f"File media tidak ditemukan: {path}")
    mime = mime_type or MIME_UMUM.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return part_bytes(path.read_bytes(), mime)


def _kirim_generate(
    parts: list[dict],
    suhu: float = 0.2,
    skema: dict | None = None,
    timeout: float | None = None,
) -> dict | list:
    if not config.llm_aktif():
        raise LLMError("GEMINI_API_KEY belum diisi")
    if not parts:
        raise LLMError("Parts prompt tidak boleh kosong")

    gen_config: dict = {
        "temperature": suhu,
        "responseMimeType": "application/json",
    }
    if skema is not None:
        gen_config["responseSchema"] = skema

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_config,
    }
    try:
        r = httpx.post(
            URL.format(model=config.GEMINI_MODEL),
            params={"key": config.GEMINI_API_KEY},
            json=body,
            timeout=timeout if timeout is not None else config.HTTP_TIMEOUT,
        )
        r.raise_for_status()
        teks = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(teks)
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
        log.warning("Panggilan LLM gagal: %s", e)
        raise LLMError(str(e)) from e


def tanya_json(
    prompt: str,
    suhu: float = 0.2,
    skema: dict | None = None,
    timeout: float | None = None,
) -> dict | list:
    """Kirim prompt teks dan minta jawaban berupa JSON. Melempar LLMError kalau gagal."""
    return _kirim_generate([part_teks(prompt)], suhu=suhu, skema=skema, timeout=timeout)


def tanya_multimodal_json(
    parts: list[dict],
    suhu: float = 0.1,
    skema: dict | None = None,
    timeout: float | None = None,
) -> dict | list:
    """Kirim kombinasi teks + gambar/audio/video dan minta structured JSON."""
    batas_waktu = timeout if timeout is not None else max(config.HTTP_TIMEOUT, 60.0)
    return _kirim_generate(parts, suhu=suhu, skema=skema, timeout=batas_waktu)
