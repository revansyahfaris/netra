"""Klien LLM tipis (Gemini lewat REST) yang dipakai bersama semua modul.

Sengaja tanpa SDK supaya tidak bergantung versi library.
Mendukung teks, input multimodal (gambar/audio/video inlineData), dan structured JSON output.
API key dikirim lewat header (bukan URL) dan tidak pernah ikut tercetak di log/pesan error.
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


# ---------- Penyusun parts ----------

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


# ---------- Pengiriman ----------

def pesan_error(r: httpx.Response) -> str:
    """Ambil pesan error dari respons (tanpa URL, jadi key tidak ikut tercetak)."""
    try:
        return str(r.json().get("error", {}).get("message", ""))[:200]
    except (ValueError, AttributeError):
        return r.reason_phrase


def _post(model: str, body: dict, timeout: float) -> httpx.Response:
    try:
        return httpx.post(
            URL.format(model=model),
            headers={"x-goog-api-key": config.GEMINI_API_KEY},
            json=body,
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        log.warning("Panggilan LLM gagal: %s", type(e).__name__)
        raise LLMError(type(e).__name__) from None


def _kirim_generate(
    parts: list[dict],
    suhu: float = 0.2,
    skema: dict | None = None,
    timeout: float | None = None,
    model: str | None = None,
    thinking: str | None = "low",
    instruksi_sistem: str | None = None,
) -> dict | list:
    if not config.llm_aktif():
        raise LLMError("GEMINI_API_KEY belum diisi")
    if not parts:
        raise LLMError("Parts prompt tidak boleh kosong")

    gen: dict = {"temperature": suhu, "responseMimeType": "application/json"}
    if skema is not None:
        gen["responseSchema"] = skema
    if thinking:
        gen["thinkingConfig"] = {"thinkingLevel": thinking}
    body: dict = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
    if instruksi_sistem:
        body["systemInstruction"] = {"parts": [{"text": instruksi_sistem}]}
    model_id = model or config.GEMINI_MODEL
    batas = timeout if timeout is not None else config.HTTP_TIMEOUT

    r = _post(model_id, body, batas)
    if r.status_code == 400 and thinking and "thinking" in pesan_error(r).lower():
        # Model ini tidak mendukung thinkingLevel: ulangi tanpa pengaturan itu
        gen.pop("thinkingConfig")
        r = _post(model_id, body, batas)
    if r.status_code != 200:
        pesan = f"HTTP {r.status_code}: {pesan_error(r)}"
        log.warning("Panggilan LLM gagal: %s", pesan)
        raise LLMError(pesan)
    try:
        isi = r.json()["candidates"][0]["content"]["parts"]
        # Abaikan bagian "pikiran" model; ambil teks jawabannya saja
        teks = "".join(p["text"] for p in isi if "text" in p and not p.get("thought"))
        return json.loads(teks)
    except (KeyError, IndexError, ValueError, TypeError) as e:
        log.warning("Jawaban LLM tidak bisa dibaca: %s", type(e).__name__)
        raise LLMError("jawaban tidak valid") from None


def tanya_json(
    prompt: str,
    suhu: float = 0.2,
    model: str | None = None,
    thinking: str | None = "low",
    skema: dict | None = None,
    timeout: float | None = None,
    instruksi_sistem: str | None = None,
) -> dict | list:
    """Kirim prompt teks dan minta jawaban berupa JSON. Melempar LLMError kalau gagal.

    model: kosongkan untuk model ringan (config.GEMINI_MODEL), atau
           config.GEMINI_MODEL_VERIFIKASI untuk tahap verifikasi.
    thinking: tingkat "berpikir" model seri 3 (minimal / low / medium / high, None = default model).
    """
    return _kirim_generate([part_teks(prompt)], suhu=suhu, skema=skema, timeout=timeout,
                           model=model, thinking=thinking, instruksi_sistem=instruksi_sistem)


def tanya_multimodal_json(
    parts: list[dict],
    suhu: float = 0.1,
    skema: dict | None = None,
    timeout: float | None = None,
    model: str | None = None,
    thinking: str | None = "low",
    instruksi_sistem: str | None = None,
) -> dict | list:
    """Kirim kombinasi teks + gambar/audio/video dan minta structured JSON.
    Default memakai config.GEMINI_MODEL_VERIFIKASI (tugas OCR/perbandingan)."""
    batas = timeout if timeout is not None else max(config.HTTP_TIMEOUT, 60.0)
    return _kirim_generate(parts, suhu=suhu, skema=skema, timeout=batas,
                           model=model or config.GEMINI_MODEL_VERIFIKASI, thinking=thinking,
                           instruksi_sistem=instruksi_sistem)
