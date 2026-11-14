"""Tahap 3 (Tier-2 Search / RAG): Korpus Resmi Multimodal di Neon pgvector.

Mengindeks dokumen teks (chunk 300-500 kata) serta aset gambar/video resmi (<= 120 detik)
menggunakan Gemini Embedding 2, serta menyediakan retriever semantik dengan fallback
Full-Text Search (FTS) PostgreSQL Bahasa Indonesia jika embedding API gagal.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import BaseModel, Field, model_validator

import config
from url_kanonis import doc_id_dari_url, normalisasi_url

from . import ekstraksi, embedding

log = logging.getLogger("netra.ai.rag")

SCHEMA_PATH = Path(__file__).parent / "schema_rag.sql"
EKSTENSI_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
CakupanKorpus = Literal["resmi", "temuan"]
TTL_TEMUAN_DEFAULT_HARI = 90


class RAGError(Exception):
    pass


class DokumenKorpus(BaseModel):
    doc_id: str | None = None
    judul: str
    url: str
    url_kanonis: str | None = None
    tanggal_terbit: date | str | None = None
    jenis_sumber: Literal["resmi", "media", "pribadi"] = "resmi"
    jenis_media: Literal["teks", "gambar", "video"] = "teks"
    cakupan: CakupanKorpus = "resmi"
    kadaluwarsa_pada: datetime | None = None
    ringkasan: str | None = None
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _isi_identitas_url(self) -> DokumenKorpus:
        if not self.url_kanonis or not self.url_kanonis.strip():
            self.url_kanonis = normalisasi_url(self.url)
        if not self.doc_id or not self.doc_id.strip():
            self.doc_id = doc_id_dari_url(self.url)
        else:
            self.doc_id = self.doc_id.strip()

        if self.kadaluwarsa_pada is not None:
            if self.kadaluwarsa_pada.tzinfo is None:
                self.kadaluwarsa_pada = self.kadaluwarsa_pada.replace(tzinfo=timezone.utc)
        elif self.cakupan == "temuan" and "kadaluwarsa_pada" not in self.model_fields_set:
            self.kadaluwarsa_pada = datetime.now(timezone.utc) + timedelta(days=TTL_TEMUAN_DEFAULT_HARI)
        return self


class HasilCariKorpus(BaseModel):
    chunk_id: int
    doc_id: str
    judul: str
    tanggal_terbit: str | None = None
    url: str
    jenis_sumber: str
    cakupan: CakupanKorpus = "resmi"
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
    kanonis = dok.url_kanonis or normalisasi_url(dok.url)
    doc_id = dok.doc_id or doc_id_dari_url(dok.url)
    cur.execute(
        """
        INSERT INTO netra_korpus_dokumen
            (doc_id, judul, tanggal_terbit, url, url_kanonis, jenis_sumber, jenis_media, ringkasan, metadata, cakupan, kadaluwarsa_pada)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (doc_id) DO UPDATE SET
            judul = EXCLUDED.judul,
            tanggal_terbit = EXCLUDED.tanggal_terbit,
            url = EXCLUDED.url,
            url_kanonis = EXCLUDED.url_kanonis,
            jenis_sumber = EXCLUDED.jenis_sumber,
            jenis_media = EXCLUDED.jenis_media,
            ringkasan = EXCLUDED.ringkasan,
            metadata = EXCLUDED.metadata,
            cakupan = CASE
                WHEN netra_korpus_dokumen.cakupan = 'resmi' THEN 'resmi'
                ELSE EXCLUDED.cakupan
            END,
            kadaluwarsa_pada = CASE
                WHEN EXCLUDED.cakupan = 'resmi' THEN EXCLUDED.kadaluwarsa_pada
                WHEN netra_korpus_dokumen.cakupan = 'resmi' THEN netra_korpus_dokumen.kadaluwarsa_pada
                ELSE EXCLUDED.kadaluwarsa_pada
            END
        """,
        (
            doc_id,
            dok.judul,
            tgl,
            dok.url,
            kanonis,
            dok.jenis_sumber,
            dok.jenis_media,
            dok.ringkasan,
            json.dumps(dok.metadata),
            dok.cakupan,
            dok.kadaluwarsa_pada,
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
    media_path: Path | None = None,
    teks_pendamping: str = "",
    detik_mulai: float | None = None,
    detik_selesai: float | None = None,
    urutan: int = 0,
    dsn: str | None = None,
    media_paths: Sequence[Path] | None = None,
) -> int:
    """Indeks aset gambar, keyframe, atau klip video (<= 120 detik) ke Neon pgvector."""
    daftar_keyframe = [Path(p) for p in (media_paths or ()) if Path(p).exists()]
    if media_path is None and not daftar_keyframe:
        raise RAGError("Minimal media_path atau media_paths harus tersedia untuk indeks media")

    sumber_embed: Path | None = media_path
    adalah_video = dokumen.jenis_media == "video" or (
        media_path is not None and media_path.suffix.lower() in EKSTENSI_VIDEO
    )
    if media_path is not None:
        if not media_path.exists():
            raise RAGError(f"File media korpus tidak ditemukan: {media_path}")
        if adalah_video and not daftar_keyframe:
            durasi = ekstraksi.durasi_video(media_path)
            if durasi is not None and durasi > ekstraksi.MAKS_DETIK_EMBEDDING:
                mulai = max(0.0, detik_mulai or 0.0)
                sumber_embed = ekstraksi.potong_segmen(
                    media_path,
                    mulai_detik=mulai,
                    durasi_maks=ekstraksi.MAKS_DETIK_EMBEDDING,
                )
        elif adalah_video and daftar_keyframe:
            # Utamakan keyframe + teks STT/OCR untuk menekan ukuran payload & token
            sumber_embed = None

    konteks_teks = "\n".join(t for t in (dokumen.judul, teks_pendamping.strip()) if t)
    vek = embedding.embed_multimodal(
        teks=konteks_teks,
        media_path=sumber_embed,
        media_paths=daftar_keyframe or None,
        task_type="RETRIEVAL_DOCUMENT",
    )

    jenis_konten = "video" if adalah_video else "gambar"
    isi_tersimpan = teks_pendamping.strip() or dokumen.judul
    lokasi_utama = str(media_path or daftar_keyframe[0])

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
                        lokasi_utama,
                        embedding.format_vector_pg(vek),
                    ),
                )
            conn.commit()
    except psycopg.Error as e:
        raise RAGError(f"Gagal menyimpan media korpus ke database: {e}") from e
    return 1


def _normalisasi_filter_cakupan(
    cakupan: CakupanKorpus | Sequence[CakupanKorpus] | None,
) -> list[CakupanKorpus] | None:
    if cakupan is None:
        return None
    daftar = [cakupan] if isinstance(cakupan, str) else list(cakupan)
    if not daftar:
        raise ValueError("Filter cakupan tidak boleh kosong jika diberikan")
    sah = {"resmi", "temuan"}
    for item in daftar:
        if item not in sah:
            raise ValueError(f"Cakupan tidak dikenal: {item!r} (pilih 'resmi' atau 'temuan')")
    return list(dict.fromkeys(daftar))


def _klausul_filter_dokumen(
    cakupan_list: list[CakupanKorpus] | None,
    sertakan_kadaluwarsa: bool,
) -> tuple[str, list]:
    klausa: list[str] = []
    params: list = []
    if cakupan_list is not None:
        klausa.append("d.cakupan = ANY(%s)")
        params.append(cakupan_list)
    if not sertakan_kadaluwarsa:
        klausa.append("(d.kadaluwarsa_pada IS NULL OR d.kadaluwarsa_pada > NOW())")
    if not klausa:
        return "", []
    return " AND " + " AND ".join(klausa), params


def _baris_ke_hasil(row: tuple, metode: Literal["vector", "keyword"]) -> HasilCariKorpus:
    cakupan_val = row[11] if len(row) > 11 and row[11] in ("resmi", "temuan") else "resmi"
    return HasilCariKorpus(
        chunk_id=int(row[0]),
        doc_id=row[1],
        judul=row[2],
        tanggal_terbit=row[3],
        url=row[4],
        jenis_sumber=row[5],
        cakupan=cakupan_val,
        jenis_konten=row[6],
        kutipan=row[7],
        skor_kemiripan=round(max(0.0, min(float(row[8] or 0.0), 1.0)), 4),
        detik_mulai=row[9],
        detik_selesai=row[10],
        metode_cari=metode,
    )


def _cari_vector(
    conn: psycopg.Connection,
    vektor: list[float],
    batas: int,
    ambang_skor: float,
    cakupan_list: list[CakupanKorpus] | None = None,
    sertakan_kadaluwarsa: bool = False,
) -> list[HasilCariKorpus]:
    vec_str = embedding.format_vector_pg(vektor)
    klausa_filter, params_filter = _klausul_filter_dokumen(cakupan_list, sertakan_kadaluwarsa)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.chunk_id, c.doc_id, d.judul, d.tanggal_terbit::text, d.url,
                   d.jenis_sumber, c.jenis_konten, c.isi_teks,
                   1 - (c.embedding <=> %s::vector) AS skor,
                   c.detik_mulai, c.detik_selesai, d.cakupan
            FROM netra_korpus_chunk c
            JOIN netra_korpus_dokumen d ON d.doc_id = c.doc_id
            WHERE c.embedding IS NOT NULL
              AND (1 - (c.embedding <=> %s::vector)) >= %s{klausa_filter}
            ORDER BY c.embedding <=> %s::vector ASC
            LIMIT %s
            """,
            (vec_str, vec_str, ambang_skor, *params_filter, vec_str, batas),
        )
        return [_baris_ke_hasil(r, "vector") for r in cur.fetchall()]


def _cari_keyword(
    conn: psycopg.Connection,
    query_teks: str,
    batas: int,
    cakupan_list: list[CakupanKorpus] | None = None,
    sertakan_kadaluwarsa: bool = False,
) -> list[HasilCariKorpus]:
    bersih = query_teks.strip()
    if not bersih:
        return []
    klausa_filter, params_filter = _klausul_filter_dokumen(cakupan_list, sertakan_kadaluwarsa)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.chunk_id, c.doc_id, d.judul, d.tanggal_terbit::text, d.url,
                   d.jenis_sumber, c.jenis_konten, c.isi_teks,
                   LEAST(ts_rank_cd(c.fts, plainto_tsquery('indonesian', %s)), 1.0) AS skor,
                   c.detik_mulai, c.detik_selesai, d.cakupan
            FROM netra_korpus_chunk c
            JOIN netra_korpus_dokumen d ON d.doc_id = c.doc_id
            WHERE c.fts @@ plainto_tsquery('indonesian', %s){klausa_filter}
            ORDER BY skor DESC
            LIMIT %s
            """,
            (bersih, bersih, *params_filter, batas),
        )
        rows = cur.fetchall()
        if rows:
            return [_baris_ke_hasil(r, "keyword") for r in rows]

        # Fallback terakhir jika kata terlalu spesifik/singkatan tidak lolos stemming FTS
        cur.execute(
            f"""
            SELECT c.chunk_id, c.doc_id, d.judul, d.tanggal_terbit::text, d.url,
                   d.jenis_sumber, c.jenis_konten, c.isi_teks,
                   0.3 AS skor,
                   c.detik_mulai, c.detik_selesai, d.cakupan
            FROM netra_korpus_chunk c
            JOIN netra_korpus_dokumen d ON d.doc_id = c.doc_id
            WHERE (c.isi_teks ILIKE %s OR d.judul ILIKE %s){klausa_filter}
            LIMIT %s
            """,
            (f"%{bersih[:100]}%", f"%{bersih[:100]}%", *params_filter, batas),
        )
        return [_baris_ke_hasil(r, "keyword") for r in cur.fetchall()]


def cari_korpus(
    query_teks: str,
    media_path: Path | None = None,
    batas: int = 5,
    ambang_skor: float = 0.0,
    fallback_aman: bool = True,
    dsn: str | None = None,
    cakupan: CakupanKorpus | Sequence[CakupanKorpus] | None = None,
    sertakan_kadaluwarsa: bool = False,
    media_paths: Sequence[Path] | None = None,
) -> list[HasilCariKorpus]:
    """Cari potongan korpus paling relevan (Gemini Embedding 2 + fallback FTS Postgres)."""
    cakupan_list = _normalisasi_filter_cakupan(cakupan)
    vektor: list[float] | None = None
    try:
        vektor = embedding.embed_multimodal(
            teks=query_teks,
            media_path=media_path,
            media_paths=media_paths,
            task_type="RETRIEVAL_QUERY",
        )
    except embedding.EmbeddingError as e:
        log.warning("Embedding gagal, beralih ke pencarian keyword FTS (%s)", e)

    try:
        with _koneksi(dsn) as conn:
            if vektor is not None:
                return _cari_vector(
                    conn,
                    vektor,
                    batas=batas,
                    ambang_skor=ambang_skor,
                    cakupan_list=cakupan_list,
                    sertakan_kadaluwarsa=sertakan_kadaluwarsa,
                )
            return _cari_keyword(
                conn,
                query_teks,
                batas=batas,
                cakupan_list=cakupan_list,
                sertakan_kadaluwarsa=sertakan_kadaluwarsa,
            )
    except (RAGError, psycopg.Error) as e:
        log.warning("Pencarian korpus RAG gagal: %s", e)
        if not fallback_aman:
            raise RAGError(str(e)) from e
        return []


def dokumen_masih_aktif(doc_id: str, dsn: str | None = None) -> bool:
    """Periksa apakah dokumen sudah terindeks dengan chunk aktif dan belum kedaluwarsa."""
    if not doc_id or not doc_id.strip():
        return False
    try:
        with _koneksi(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM netra_korpus_dokumen d
                    WHERE d.doc_id = %s
                      AND (d.kadaluwarsa_pada IS NULL OR d.kadaluwarsa_pada > NOW())
                      AND EXISTS (
                          SELECT 1 FROM netra_korpus_chunk c WHERE c.doc_id = d.doc_id
                      )
                    LIMIT 1
                    """,
                    (doc_id.strip(),),
                )
                return cur.fetchone() is not None
    except (RAGError, psycopg.Error) as e:
        log.debug("Pengecekan cache RAG dilewati: %s", e)
        return False


def bersihkan_temuan_kadaluwarsa(dsn: str | None = None) -> int:
    """Hapus dokumen korpus `temuan` yang melewati `kadaluwarsa_pada` (chunk ikut terhapus cascade)."""
    try:
        with _koneksi(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM netra_korpus_dokumen
                    WHERE cakupan = 'temuan'
                      AND kadaluwarsa_pada IS NOT NULL
                      AND kadaluwarsa_pada <= NOW()
                    """
                )
                jumlah = cur.rowcount or 0
            conn.commit()
            return max(0, int(jumlah))
    except psycopg.Error as e:
        raise RAGError(f"Gagal membersihkan temuan kedaluwarsa: {e}") from e

