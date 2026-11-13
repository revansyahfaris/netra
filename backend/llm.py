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


def tanya_json(prompt: str, suhu: float = 0.2, model: str | None = None, thinking: str | None = "low") -> dict | list:
    """Kirim prompt dan minta jawaban berupa JSON. Melempar LLMError kalau gagal.

    model: kosongkan untuk model ringan (config.GEMINI_MODEL),
           atau isi config.GEMINI_MODEL_VERIFIKASI untuk tahap verifikasi.
    thinking: tingkat "berpikir" model seri 3 (minimal / low / medium / high, None = default model).
           Tugas ringan cukup "low" supaya cepat dan hemat token.
    """
    if not config.llm_aktif():
        raise LLMError("GEMINI_API_KEY belum diisi")

    gen = {"temperature": suhu, "responseMimeType": "application/json"}
    if thinking:
        gen["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen}
    r = _kirim(body, model)
    if r.status_code == 400 and thinking and "thinking" in _pesan_error(r).lower():
        # Model ini tidak mendukung thinkingLevel: ulangi tanpa pengaturan itu
        gen.pop("thinkingConfig")
        r = _kirim(body, model)
    if r.status_code != 200:
        pesan = f"HTTP {r.status_code}: {_pesan_error(r)}"
        log.warning("Panggilan LLM gagal: %s", pesan)
        raise LLMError(pesan)
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        # Abaikan bagian "pikiran" model; ambil teks jawabannya saja
        teks = "".join(p["text"] for p in parts if "text" in p and not p.get("thought"))
        return json.loads(teks)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Jawaban LLM tidak bisa dibaca: %s", type(e).__name__)
        raise LLMError("jawaban tidak valid") from None


def _kirim(body: dict, model: str | None) -> httpx.Response:
    try:
        # Key lewat header, bukan URL, supaya tidak tercetak di log
        return httpx.post(
            URL.format(model=model or config.GEMINI_MODEL),
            headers={"x-goog-api-key": config.GEMINI_API_KEY},
            json=body,
            timeout=config.HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        log.warning("Panggilan LLM gagal: %s", type(e).__name__)
        raise LLMError(type(e).__name__) from None


def _pesan_error(r: httpx.Response) -> str:
    """Ambil pesan error dari respons (tanpa URL, jadi key tidak ikut tercetak)."""
    try:
        return str(r.json().get("error", {}).get("message", ""))[:200]
    except ValueError:
        return r.reason_phrase
