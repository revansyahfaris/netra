"""Tahap 3 (Tier-2 Search / RAG): Korpus Resmi Multimodal di Neon pgvector.

Mengindeks dokumen teks (chunk 300-500 kata) serta aset gambar/video resmi (<= 120 detik)
menggunakan Gemini Embedding 2, serta menyediakan retriever semantik dengan fallback
Full-Text Search (FTS) PostgreSQL Bahasa Indonesia jika embedding API gagal.
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import BaseModel, Field

import config

from . import ekstraksi, embedding

log = logging.getLogger("netra.ai.rag")

SCHEMA_PATH = Path(__file__).parent / "schema_rag.sql"
EKSTENSI_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


class RAGError(Exception):
    pass


class DokumenKorpus(BaseModel):
    doc_id: str
    judul: str
    url: str
    tanggal_terbit: date | str | None = None
    jenis_sumber: Literal["resmi", "media", "pribadi"] = "resmi"
    jenis_media: Literal["teks", "gambar", "video"] = "teks"
    ringkasan: str | None = None
    metadata: dict = Field(default_factory=dict)


class HasilCariKorpus(BaseModel):
    chunk_id: int
    doc_id: str
    judul: str
    tanggal_terbit: str | None = None
    url: str
    jenis_sumber: str
    jenis_konten: str
    kutipan: str
    skor_kemiripan: float
    detik_mulai: float | None = None
    detik_selesai: float | None = None
    metode_cari: Literal["vector", "keyword"]


def _koneksi(dsn: str | None = None) -> psycopg.Connection:
    url = (dsn or config.DATABASE_URL).strip()
    if not url:
        raise RAGError("DATABASE_URL belum diisi")
    try:
        return psycopg.connect(url, connect_timeout=int(max(config.HTTP_TIMEOUT, 10)))
    except psycopg.Error as e:
        raise RAGError(f"Gagal terhubung ke database: {e}") from e


def siapkan_skema(dsn: str | None = None) -> None:
    """Jalankan schema_rag.sql (aktifkan pgvector dan buat tabel korpus jika belum ada)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    try:
        with _koneksi(dsn) as conn:
            conn.execute(sql)
            conn.commit()
    except psycopg.Error as e:
        raise RAGError(f"Gagal menyiapkan skema RAG: {e}") from e


def potong_teks(teks: str, target_kata: int = 350, overlap_kata: int = 50) -> list[str]:
    """Pecah teks menjadi potongan 300-500 kata dengan overlap antar-chunk."""
    if target_kata <= 0:
        raise ValueError("target_kata harus > 0")
    if overlap_kata < 0 or overlap_kata >= target_kata:
        raise ValueError("overlap_kata harus >= 0 dan < target_kata")

    kata = teks.split()
    if not kata:
        return []
    if len(kata) <= target_kata:
        return [" ".join(kata)]

    hasil: list[str] = []
    langkah = target_kata - overlap_kata
    mulai = 0
    while mulai < len(kata):
        akhir = min(mulai + target_kata, len(kata))
        hasil.append(" ".join(kata[mulai:akhir]))
        if akhir >= len(kata):
            break
        mulai += langkah
    return hasil


def _upsert_dokumen(cur: psycopg.Cursor, dok: DokumenKorpus) -> None:
    tgl = dok.tanggal_terbit.isoformat() if isinstance(dok.tanggal_terbit, date) else dok.tanggal_terbit
    cur.execute(
        """
        INSERT INTO netra_korpus_dokumen
            (doc_id, judul, tanggal_terbit, url, jenis_sumber, jenis_media, ringkasan, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (doc_id) DO UPDATE SET
            judul = EXCLUDED.judul,
            tanggal_terbit = EXCLUDED.tanggal_terbit,
            url = EXCLUDED.url,
            jenis_sumber = EXCLUDED.jenis_sumber,
            jenis_media = EXCLUDED.jenis_media,
            ringkasan = EXCLUDED.ringkasan,
            metadata = EXCLUDED.metadata
        """,
        (
            dok.doc_id,
            dok.judul,
            tgl,
            dok.url,
            dok.jenis_sumber,
            dok.jenis_media,
            dok.ringkasan,
            json.dumps(dok.metadata),
        ),
    )


def indeks_dokumen_teks(
    dokumen: DokumenKorpus,
    isi_teks: str,
    target_kata: int = 350,
    overlap_kata: int = 50,
    dsn: str | None = None,
) -> int:
    """Chunk dokumen teks, buat embedding Gemini Embedding 2, dan simpan ke Neon pgvector."""
    potongan = potong_teks(isi_teks, target_kata=target_kata, overlap_kata=overlap_kata)
    if not potongan:
        raise RAGError("Isi dokumen kosong, tidak ada yang bisa diindeks")

    vektor_list = [
        embedding.embed_teks(f"Judul: {dokumen.judul}\n\n{p}", task_type="RETRIEVAL_DOCUMENT")
        for p in potongan
    ]

    try:
        with _koneksi(dsn) as conn:
            with conn.cursor() as cur:
                _upsert_dokumen(cur, dokumen)
                cur.execute("DELETE FROM netra_korpus_chunk WHERE doc_id = %s", (dokumen.doc_id,))
                for idx, (teks_chunk, vek) in enumerate(zip(potongan, vektor_list)):
                    cur.execute(
                        """
                        INSERT INTO netra_korpus_chunk
                            (doc_id, urutan, jenis_konten, isi_teks, embedding)
                        VALUES (%s, %s, 'teks', %s, %s::vector)
                        """,
                        (dokumen.doc_id, idx, teks_chunk, embedding.format_vector_pg(vek)),
                    )
            conn.commit()
    except psycopg.Error as e:
        raise RAGError(f"Gagal menyimpan chunk ke database: {e}") from e
    return len(potongan)


def indeks_media_korpus(
    dokumen: DokumenKorpus,
    media_path: Path,
    teks_pendamping: str = "",
    detik_mulai: float | None = None,
    detik_selesai: float | None = None,
    urutan: int = 0,
    dsn: str | None = None,
) -> int:
    """Indeks aset gambar atau klip video resmi (<= 120 detik) ke Neon pgvector."""
    if not media_path.exists():
        raise RAGError(f"File media korpus tidak ditemukan: {media_path}")

    sumber_embed = media_path
    adalah_video = dokumen.jenis_media == "video" or media_path.suffix.lower() in EKSTENSI_VIDEO
    if adalah_video:
        durasi = ekstraksi.durasi_video(media_path)
        if durasi is not None and durasi > ekstraksi.MAKS_DETIK_EMBEDDING:
            mulai = max(0.0, detik_mulai or 0.0)
            sumber_embed = ekstraksi.potong_segmen(
                media_path,
                mulai_detik=mulai,
                durasi_maks=ekstraksi.MAKS_DETIK_EMBEDDING,
            )

    konteks_teks = "\n".join(t for t in (dokumen.judul, teks_pendamping.strip()) if t)
    vek = embedding.embed_multimodal(
        teks=konteks_teks,
        media_path=sumber_embed,
        task_type="RETRIEVAL_DOCUMENT",
    )

    jenis_konten = "video" if adalah_video else "gambar"
    isi_tersimpan = teks_pendamping.strip() or dokumen.judul

    try:
        with _koneksi(dsn) as conn:
            with conn.cursor() as cur:
                _upsert_dokumen(cur, dokumen)
                cur.execute(
                    """
                    INSERT INTO netra_korpus_chunk
                        (doc_id, urutan, jenis_konten, isi_teks, detik_mulai, detik_selesai, lokasi_media, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (doc_id, urutan) DO UPDATE SET
                        jenis_konten = EXCLUDED.jenis_konten,
                        isi_teks = EXCLUDED.isi_teks,
                        detik_mulai = EXCLUDED.detik_mulai,
                        detik_selesai = EXCLUDED.detik_selesai,
                        lokasi_media = EXCLUDED.lokasi_media,
                        embedding = EXCLUDED.embedding
                    """,
                    (
                        dokumen.doc_id,
                        urutan,
                        jenis_konten,
                        isi_tersimpan,
                        detik_mulai,
                        detik_selesai,
                        str(media_path),
                        embedding.format_vector_pg(vek),
                    ),
                )
            conn.commit()
    except psycopg.Error as e:
        raise RAGError(f"Gagal menyimpan media korpus ke database: {e}") from e
    return 1


def _baris_ke_hasil(row: tuple, metode: Literal["vector", "keyword"]) -> HasilCariKorpus:
    return HasilCariKorpus(
        chunk_id=int(row[0]),
        doc_id=row[1],
        judul=row[2],
        tanggal_terbit=row[3],
        url=row[4],
        jenis_sumber=row[5],
        jenis_konten=row[6],
        kutipan=row[7],
        skor_kemiripan=round(max(0.0, min(float(row[8] or 0.0), 1.0)), 4),
        detik_mulai=row[9],
        detik_selesai=row[10],
        metode_cari=metode,
    )


def _cari_vector(conn: psycopg.Connection, vektor: list[float], batas: int, ambang_skor: float) -> list[HasilCariKorpus]:
    vec_str = embedding.format_vector_pg(vektor)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.chunk_id, c.doc_id, d.judul, d.tanggal_terbit::text, d.url,
                   d.jenis_sumber, c.jenis_konten, c.isi_teks,
                   1 - (c.embedding <=> %s::vector) AS skor,
                   c.detik_mulai, c.detik_selesai
            FROM netra_korpus_chunk c
            JOIN netra_korpus_dokumen d ON d.doc_id = c.doc_id
            WHERE c.embedding IS NOT NULL
              AND (1 - (c.embedding <=> %s::vector)) >= %s
            ORDER BY c.embedding <=> %s::vector ASC
            LIMIT %s
            """,
            (vec_str, vec_str, ambang_skor, vec_str, batas),
        )
        return [_baris_ke_hasil(r, "vector") for r in cur.fetchall()]


def _cari_keyword(conn: psycopg.Connection, query_teks: str, batas: int) -> list[HasilCariKorpus]:
    bersih = query_teks.strip()
    if not bersih:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.chunk_id, c.doc_id, d.judul, d.tanggal_terbit::text, d.url,
                   d.jenis_sumber, c.jenis_konten, c.isi_teks,
                   LEAST(ts_rank_cd(c.fts, plainto_tsquery('indonesian', %s)), 1.0) AS skor,
                   c.detik_mulai, c.detik_selesai
            FROM netra_korpus_chunk c
            JOIN netra_korpus_dokumen d ON d.doc_id = c.doc_id
            WHERE c.fts @@ plainto_tsquery('indonesian', %s)
            ORDER BY skor DESC
            LIMIT %s
            """,
            (bersih, bersih, batas),
        )
        rows = cur.fetchall()
        if rows:
            return [_baris_ke_hasil(r, "keyword") for r in rows]

        # Fallback terakhir jika kata terlalu spesifik/singkatan tidak lolos stemming FTS
        cur.execute(
            """
            SELECT c.chunk_id, c.doc_id, d.judul, d.tanggal_terbit::text, d.url,
                   d.jenis_sumber, c.jenis_konten, c.isi_teks,
                   0.3 AS skor,
                   c.detik_mulai, c.detik_selesai
            FROM netra_korpus_chunk c
            JOIN netra_korpus_dokumen d ON d.doc_id = c.doc_id
            WHERE c.isi_teks ILIKE %s OR d.judul ILIKE %s
            LIMIT %s
            """,
            (f"%{bersih[:100]}%", f"%{bersih[:100]}%", batas),
        )
        return [_baris_ke_hasil(r, "keyword") for r in cur.fetchall()]


def cari_korpus(
    query_teks: str,
    media_path: Path | None = None,
    batas: int = 5,
    ambang_skor: float = 0.0,
    fallback_aman: bool = True,
    dsn: str | None = None,
) -> list[HasilCariKorpus]:
    """Cari potongan korpus resmi paling relevan (Gemini Embedding 2 + fallback FTS Postgres)."""
    vektor: list[float] | None = None
    try:
        vektor = embedding.embed_multimodal(
            teks=query_teks,
            media_path=media_path,
            task_type="RETRIEVAL_QUERY",
        )
    except embedding.EmbeddingError as e:
        log.warning("Embedding gagal, beralih ke pencarian keyword FTS (%s)", e)

    try:
        with _koneksi(dsn) as conn:
            if vektor is not None:
                return _cari_vector(conn, vektor, batas=batas, ambang_skor=ambang_skor)
            return _cari_keyword(conn, query_teks, batas=batas)
    except (RAGError, psycopg.Error) as e:
        log.warning("Pencarian korpus RAG gagal: %s", e)
        if not fallback_aman:
            raise RAGError(str(e)) from e
        return []

