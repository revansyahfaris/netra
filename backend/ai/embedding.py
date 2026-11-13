"""Klien REST Gemini Embedding 2 untuk embedding multimodal (teks, gambar, video).

Mendukung Matryoshka Representation Learning (outputDimensionality: 768, 1536, 3072)
sehingga teks, gambar, dan klip video (<= 120 detik) berada dalam ruang vektor yang sama.
"""

import logging
from pathlib import Path

import httpx

import config
import llm

log = logging.getLogger("netra.ai.embedding")

EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
MAKS_INLINE_BYTES = 15 * 1024 * 1024  # batas aman payload inlineData


class EmbeddingError(Exception):
    pass


def embed_parts(
    parts: list[dict],
    task_type: str = "RETRIEVAL_DOCUMENT",
    dimensi: int | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> list[float]:
    """Kirim parts (teks dan/atau inlineData media) ke Gemini Embedding 2."""
    if not config.llm_aktif():
        raise EmbeddingError("GEMINI_API_KEY belum diisi")
    if not parts:
        raise EmbeddingError("Parts embedding tidak boleh kosong")

    model_id = model or config.GEMINI_EMBEDDING_MODEL
    dim = dimensi or config.EMBEDDING_DIM
    body = {
        "content": {"parts": parts},
        "taskType": task_type,
        "outputDimensionality": dim,
    }
    batas_waktu = timeout if timeout is not None else max(config.HTTP_TIMEOUT, 60.0)
    try:
        r = httpx.post(
            EMBED_URL.format(model=model_id),
            params={"key": config.GEMINI_API_KEY},
            json=body,
            timeout=batas_waktu,
        )
        r.raise_for_status()
        values = r.json()["embedding"]["values"]
        return [float(x) for x in values]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        log.warning("Panggilan Gemini Embedding gagal: %s", e)
        raise EmbeddingError(str(e)) from e


def embed_teks(
    teks: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
    dimensi: int | None = None,
) -> list[float]:
    """Buat embedding untuk teks."""
    bersih = teks.strip()
    if not bersih:
        raise EmbeddingError("Teks untuk embedding tidak boleh kosong")
    return embed_parts([llm.part_teks(bersih)], task_type=task_type, dimensi=dimensi)


def embed_multimodal(
    teks: str | None = None,
    media_path: Path | None = None,
    task_type: str = "RETRIEVAL_QUERY",
    dimensi: int | None = None,
) -> list[float]:
    """Buat embedding gabungan teks + gambar/video (<= 120 detik) dalam satu vektor."""
    parts: list[dict] = []
    if media_path is not None:
        if not media_path.exists():
            raise EmbeddingError(f"File media tidak ditemukan: {media_path}")
        if media_path.stat().st_size > MAKS_INLINE_BYTES:
            raise EmbeddingError(
                f"Ukuran media melebihi batas inline 15 MB ({media_path.name}); potong/kompres segmen terlebih dahulu"
            )
        try:
            parts.append(llm.part_file(media_path))
        except llm.LLMError as e:
            raise EmbeddingError(str(e)) from e

    if teks and teks.strip():
        parts.append(llm.part_teks(teks.strip()))

    if not parts:
        raise EmbeddingError("Minimal harus ada teks atau media untuk membuat embedding")
    return embed_parts(parts, task_type=task_type, dimensi=dimensi)


def format_vector_pg(vektor: list[float]) -> str:
    """Format list float ke literal string pgvector: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.8f}" for x in vektor) + "]"

