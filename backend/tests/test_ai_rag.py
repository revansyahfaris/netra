"""Tes Tahap 3 modul Embedding (Gemini Embedding 2) & RAG (Neon pgvector)."""

import httpx
import psycopg
import pytest

import config
from ai import (
    DokumenKorpus,
    EmbeddingError,
    HasilCariKorpus,
    RAGError,
    cari_korpus,
    embed_multimodal,
    embed_teks,
    format_vector_pg,
    indeks_dokumen_teks,
    potong_teks,
)


def test_potong_teks_chunking_dengan_overlap():
    teks = " ".join(f"kata{i}" for i in range(700))
    chunks = potong_teks(teks, target_kata=350, overlap_kata=50)
    assert len(chunks) == 3
    assert len(chunks[0].split()) == 350
    assert chunks[0].split()[-50:] == chunks[1].split()[:50]


def test_potong_teks_pendek_dan_kosong():
    assert potong_teks("   ") == []
    assert potong_teks("satu dua tiga", target_kata=350) == ["satu dua tiga"]


def test_format_vector_pg():
    assert format_vector_pg([0.5, -0.25]) == "[0.50000000,-0.25000000]"


def test_embed_teks_kirim_payload_dan_dimensi(monkeypatch):
    tangkapan = {}

    def fake_post(url, params=None, **kwargs):
        tangkapan["url"] = url
        tangkapan["body"] = kwargs["json"]
        return httpx.Response(
            200,
            json={"embedding": {"values": [0.1, 0.2, 0.3]}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(config, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
    monkeypatch.setattr(config, "EMBEDDING_DIM", 1536)
    monkeypatch.setattr("httpx.post", fake_post)

    vek = embed_teks("Kasad menegaskan TNI netral.", task_type="RETRIEVAL_DOCUMENT")
    assert vek == [0.1, 0.2, 0.3]
    assert "gemini-embedding-2:embedContent" in tangkapan["url"]
    assert tangkapan["body"]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert tangkapan["body"]["outputDimensionality"] == 1536


def test_embed_multimodal_gambar_dan_teks(tmp_path, monkeypatch):
    img = tmp_path / "rilis.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0dummy")
    tangkapan = {}

    def fake_post(url, params=None, **kwargs):
        tangkapan["parts"] = kwargs["json"]["content"]["parts"]
        return httpx.Response(
            200,
            json={"embedding": {"values": [0.4, 0.5]}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy")
    monkeypatch.setattr("httpx.post", fake_post)

    vek = embed_multimodal(teks="Rilis resmi", media_path=img, task_type="RETRIEVAL_QUERY")
    assert vek == [0.4, 0.5]
    assert tangkapan["parts"][0]["inlineData"]["mimeType"] == "image/jpeg"
    assert tangkapan["parts"][1] == {"text": "Rilis resmi"}


def test_embed_gagal_saat_api_key_kosong(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(EmbeddingError):
        embed_teks("uji")


class _FakeCursor:
    def __init__(self, rows=None):
        self.queries = []
        self._rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows=None):
        self.cur = _FakeCursor(rows=rows)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def test_indeks_dokumen_teks_simpan_chunk(monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr("ai.rag.embedding.embed_teks", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: fake_conn)

    dok = DokumenKorpus(
        doc_id="dok_001",
        judul="Siaran Pers Resmi TNI AD",
        url="https://tniad.mil.id/siaran-pers",
        tanggal_terbit="2026-11-08",
    )
    teks = " ".join(["netralitas"] * 400)
    jumlah = indeks_dokumen_teks(dok, teks, target_kata=350, overlap_kata=50)

    assert jumlah == 2
    assert fake_conn.committed is True
    insert_chunks = [q for q in fake_conn.cur.queries if "INSERT INTO netra_korpus_chunk" in q[0]]
    assert len(insert_chunks) == 2


def test_cari_korpus_vector_dan_fallback_keyword(monkeypatch):
    sample_row = (
        1,
        "dok_001",
        "Siaran Pers Resmi",
        "2026-11-08",
        "https://tniad.mil.id/siaran",
        "resmi",
        "teks",
        "TNI AD tegak lurus pada supremasi sipil.",
        0.9123,
        None,
        None,
    )
    fake_conn = _FakeConn(rows=[sample_row])
    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: fake_conn)

    # 1. Jalur vector sukses
    monkeypatch.setattr("ai.rag.embedding.embed_multimodal", lambda **kw: [0.1, 0.2])
    hasil_vec = cari_korpus("Kasad ambil alih pemerintahan", batas=3)
    assert len(hasil_vec) == 1
    assert isinstance(hasil_vec[0], HasilCariKorpus)
    assert hasil_vec[0].metode_cari == "vector"
    assert hasil_vec[0].skor_kemiripan == 0.9123

    # 2. Embedding gagal -> otomatis fallback ke keyword FTS Postgres
    def fail_embed(**kw):
        raise EmbeddingError("api mati")

    monkeypatch.setattr("ai.rag.embedding.embed_multimodal", fail_embed)
    hasil_kw = cari_korpus("supremasi sipil", batas=3)
    assert len(hasil_kw) == 1
    assert hasil_kw[0].metode_cari == "keyword"


def test_cari_korpus_fallback_aman_saat_db_error(monkeypatch):
    monkeypatch.setattr("ai.rag.embedding.embed_multimodal", lambda **kw: [0.1, 0.2])

    def fail_conn(dsn=None):
        raise RAGError("koneksi putus")

    monkeypatch.setattr("ai.rag._koneksi", fail_conn)
    assert cari_korpus("tes", fallback_aman=True) == []
    with pytest.raises(RAGError):
        cari_korpus("tes", fallback_aman=False)

