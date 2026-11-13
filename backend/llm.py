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
        r = httpx.post(
            URL.format(model=model or config.GEMINI_MODEL),
            params={"key": config.GEMINI_API_KEY},
            json=body,
            timeout=config.HTTP_TIMEOUT,
        )
        r.raise_for_status()
        teks = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(teks)
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
        log.warning("Panggilan LLM gagal: %s", e)
        raise LLMError(str(e)) from e
