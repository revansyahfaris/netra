"""Klien LLM tipis (Gemini lewat REST) yang dipakai bersama semua modul.

Sengaja tanpa SDK supaya tidak bergantung versi library.
Kalau mau ganti ke OpenAI atau penyedia lain, cukup ubah fungsi `tanya_json`.
"""

import json
import logging

import httpx

import config

log = logging.getLogger("netra.llm")

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    pass


def tanya_json(prompt: str, suhu: float = 0.2, model: str | None = None) -> dict | list:
    """Kirim prompt dan minta jawaban berupa JSON. Melempar LLMError kalau gagal.

    model: kosongkan untuk model ringan (config.GEMINI_MODEL),
           atau isi config.GEMINI_MODEL_VERIFIKASI untuk tahap verifikasi.
    """
    if not config.llm_aktif():
        raise LLMError("GEMINI_API_KEY belum diisi")

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": suhu, "responseMimeType": "application/json"},
    }
    try:
        # Key lewat header, bukan URL, supaya tidak tercetak di log
        r = httpx.post(
            URL.format(model=model or config.GEMINI_MODEL),
            headers={"x-goog-api-key": config.GEMINI_API_KEY},
            json=body,
            timeout=config.HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        log.warning("Panggilan LLM gagal: %s", type(e).__name__)
        raise LLMError(type(e).__name__) from None
    if r.status_code != 200:
        pesan = f"HTTP {r.status_code}: {_pesan_error(r)}"
        log.warning("Panggilan LLM gagal: %s", pesan)
        raise LLMError(pesan)
    try:
        teks = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(teks)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Jawaban LLM tidak bisa dibaca: %s", type(e).__name__)
        raise LLMError("jawaban tidak valid") from None


def _pesan_error(r: httpx.Response) -> str:
    """Ambil pesan error dari respons (tanpa URL, jadi key tidak ikut tercetak)."""
    try:
        return str(r.json().get("error", {}).get("message", ""))[:200]
    except ValueError:
        return r.reason_phrase
