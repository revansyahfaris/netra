"""Tes Tahap 3 modul Embedding (Gemini Embedding 2) & RAG (Neon pgvector)."""

from datetime import datetime, timedelta, timezone

import httpx
import psycopg
import pytest

import config
from ai import (
    TTL_TEMUAN_DEFAULT_HARI,
    DokumenKorpus,
    EmbeddingError,
    HasilCariKorpus,
    RAGError,
    bersihkan_temuan_kadaluwarsa,
    cari_korpus,
    doc_id_dari_url,
    embed_multimodal,
    embed_teks,
    format_vector_pg,
    indeks_dokumen_teks,
    normalisasi_url,
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
    def __init__(self, rows=None, rowcount=0):
        self.queries = []
        self._rows = rows or []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, rows=None, rowcount=0):
        self.cur = _FakeCursor(rows=rows, rowcount=rowcount)
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


def test_normalisasi_url_artikel_dan_platform_video():
    # Variasi artikel berita/resmi: http vs https, www/m, trailing slash, tracking, urutan query
    u1 = "http://www.tniad.mil.id/berita/rilis-kasad/?utm_source=wa&fbclid=xyz&b=2&a=1#atas"
    u2 = "HTTPS://m.tniad.mil.id/berita/rilis-kasad?a=1&b=2&gclid=999"
    assert normalisasi_url(u1) == "https://tniad.mil.id/berita/rilis-kasad?a=1&b=2"
    assert normalisasi_url(u1) == normalisasi_url(u2)

    # Query berbeda tidak boleh dianggap sama
    assert normalisasi_url("https://berita.id/artikel?id=10") != normalisasi_url("https://berita.id/artikel?id=20")

    # Variasi YouTube mengarah ke satu URL kanonis (ID video tetap case-sensitive)
    yt_varian = [
        "https://www.youtube.com/watch?v=AbC123xyZ&feature=share&t=42s",
        "http://m.youtube.com/watch?v=AbC123xyZ&si=tracker&list=PL99",
        "https://youtu.be/AbC123xyZ?si=share&t=15",
        "https://youtube.com/shorts/AbC123xyZ/",
        "https://www.youtube.com/embed/AbC123xyZ",
        "https://www.youtube.com/live/AbC123xyZ?pp=ygU",
    ]
    kanonis_yt = {normalisasi_url(u) for u in yt_varian}
    assert kanonis_yt == {"https://youtube.com/watch?v=AbC123xyZ"}
    assert normalisasi_url("https://youtu.be/abc123xyz") != "https://youtube.com/watch?v=AbC123xyZ"

    # TikTok, Instagram, X/Twitter, Facebook, dan link lokal
    assert (
        normalisasi_url("https://www.tiktok.com/@dispenad/video/740000111?is_from_webapp=1&sender_device=pc")
        == normalisasi_url("https://m.tiktok.com/@dispenad/video/740000111/")
        == "https://tiktok.com/@dispenad/video/740000111"
    )
    assert normalisasi_url("https://vm.tiktok.com/ZM999/?_r=1") == "https://vm.tiktok.com/ZM999"
    assert (
        normalisasi_url("https://www.instagram.com/reels/Cabc123/?igsh=xyz")
        == normalisasi_url("https://instagram.com/reel/Cabc123")
        == "https://instagram.com/reel/Cabc123"
    )
    assert (
        normalisasi_url("https://twitter.com/tni_ad/status/123456?s=20&t=abc")
        == normalisasi_url("https://mobile.x.com/tni_ad/status/123456/")
        == "https://x.com/tni_ad/status/123456"
    )
    assert (
        normalisasi_url("https://m.facebook.com/watch/?v=998877&fbclid=aaa&mibextid=bbb")
        == "https://facebook.com/watch?v=998877"
    )
    assert normalisasi_url("http://localhost:8100/health/") == "http://localhost:8100/health"


def test_doc_id_deterministik_dan_dokumen_korpus(monkeypatch):
    from pydantic import ValidationError

    id_a = doc_id_dari_url("https://youtu.be/AbC123xyZ?si=1&t=30")
    id_b = doc_id_dari_url("http://www.youtube.com/watch?v=AbC123xyZ&feature=share")
    assert id_a == id_b
    assert id_a.startswith("doc_") and len(id_a) == 28

    dok1 = DokumenKorpus(judul="Video A", url="https://youtu.be/AbC123xyZ?si=1")
    dok2 = DokumenKorpus(judul="Video A (sama)", url="https://www.youtube.com/watch?v=AbC123xyZ/")
    assert dok1.doc_id == dok2.doc_id == id_a
    assert dok1.url_kanonis == "https://youtube.com/watch?v=AbC123xyZ"

    with pytest.raises(ValidationError):
        DokumenKorpus(judul="Kosong", url="   ")

    fake_conn = _FakeConn()
    monkeypatch.setattr("ai.rag.embedding.embed_teks", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: fake_conn)
    indeks_dokumen_teks(dok1, "Isi keterangan resmi kejadian.")
    upsert_dok = next(q for q in fake_conn.cur.queries if "INSERT INTO netra_korpus_dokumen" in q[0])
    assert upsert_dok[1][0] == id_a
    assert upsert_dok[1][4] == "https://youtube.com/watch?v=AbC123xyZ"


def test_cakupan_dan_ttl_dokumen_korpus(monkeypatch):
    dok_resmi = DokumenKorpus(judul="Rilis Resmi", url="https://tniad.mil.id/rilis-1")
    assert dok_resmi.cakupan == "resmi"
    assert dok_resmi.kadaluwarsa_pada is None

    sebelum = datetime.now(timezone.utc)
    dok_temuan = DokumenKorpus(
        judul="Berita Panen",
        url="https://news.example.id/berita?utm_source=x",
        jenis_sumber="media",
        cakupan="temuan",
    )
    assert dok_temuan.cakupan == "temuan"
    assert dok_temuan.kadaluwarsa_pada is not None
    assert dok_temuan.kadaluwarsa_pada >= sebelum + timedelta(days=TTL_TEMUAN_DEFAULT_HARI - 1)

    # Naive datetime dinormalisasi ke UTC, sedangkan None eksplisit tetap dipertahankan
    dok_naive = DokumenKorpus(
        judul="Naive TTL",
        url="https://news.example.id/naive",
        cakupan="temuan",
        kadaluwarsa_pada=datetime(2026, 12, 1, 10, 0, 0),
    )
    assert dok_naive.kadaluwarsa_pada.tzinfo == timezone.utc

    dok_temuan_permanen = DokumenKorpus(
        judul="Temuan tanpa TTL",
        url="https://news.example.id/tanpa-ttl",
        cakupan="temuan",
        kadaluwarsa_pada=None,
    )
    assert dok_temuan_permanen.kadaluwarsa_pada is None

    fake_conn = _FakeConn()
    monkeypatch.setattr("ai.rag.embedding.embed_teks", lambda *a, **kw: [0.1, 0.2])
    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: fake_conn)
    indeks_dokumen_teks(dok_temuan, "Potongan isi berita pembanding.")

    sql_upsert, params_upsert = next(
        q for q in fake_conn.cur.queries if "INSERT INTO netra_korpus_dokumen" in q[0]
    )
    assert "WHEN netra_korpus_dokumen.cakupan = 'resmi' THEN 'resmi'" in sql_upsert
    assert params_upsert[9] == "temuan"
    assert params_upsert[10] == dok_temuan.kadaluwarsa_pada


def test_filter_cakupan_dan_kadaluwarsa_di_cari_korpus(monkeypatch):
    baris_temuan = (
        7,
        "doc_abc",
        "Video Latihan 2021",
        "2021-05-01",
        "https://youtube.com/watch?v=abc",
        "media",
        "video",
        "Rekaman latihan lapangan lama.",
        0.8421,
        12.0,
        45.0,
        "temuan",
    )
    fake_conn = _FakeConn(rows=[baris_temuan])
    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: fake_conn)
    monkeypatch.setattr("ai.rag.embedding.embed_multimodal", lambda **kw: [0.2, 0.3])

    hasil = cari_korpus("latihan gabungan", cakupan="temuan", batas=4)
    assert len(hasil) == 1
    assert hasil[0].cakupan == "temuan"

    sql_vec, params_vec = fake_conn.cur.queries[-1]
    assert "d.cakupan = ANY(%s)" in sql_vec
    assert "d.kadaluwarsa_pada > NOW()" in sql_vec
    assert ["temuan"] in params_vec

    # Menyertakan dokumen kedaluwarsa + multi cakupan pada fallback keyword
    def fail_embed(**kw):
        raise EmbeddingError("mati")

    monkeypatch.setattr("ai.rag.embedding.embed_multimodal", fail_embed)
    cari_korpus(
        "latihan gabungan",
        cakupan=("resmi", "temuan", "resmi"),
        sertakan_kadaluwarsa=True,
    )
    sql_kw, params_kw = fake_conn.cur.queries[-1]
    assert "d.cakupan = ANY(%s)" in sql_kw
    assert "d.kadaluwarsa_pada > NOW()" not in sql_kw
    assert ["resmi", "temuan"] in params_kw

    # Validasi nilai cakupan yang tidak dikenal/kosong
    with pytest.raises(ValueError):
        cari_korpus("uji", cakupan="asing")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        cari_korpus("uji", cakupan=[])


def test_bersihkan_temuan_kadaluwarsa_dan_skema(monkeypatch):
    from pathlib import Path

    fake_conn = _FakeConn(rowcount=3)
    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: fake_conn)
    terhapus = bersihkan_temuan_kadaluwarsa()
    assert terhapus == 3
    assert fake_conn.committed is True
    sql_del, _ = fake_conn.cur.queries[0]
    assert "DELETE FROM netra_korpus_dokumen" in sql_del
    assert "cakupan = 'temuan'" in sql_del

    schema_sql = (Path(__file__).resolve().parents[1] / "ai" / "schema_rag.sql").read_text(
        encoding="utf-8"
    )
    assert "cakupan VARCHAR(16)" in schema_sql
    assert "kadaluwarsa_pada TIMESTAMPTZ" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS netra_klaim_bukti" in schema_sql
    assert "DROP CONSTRAINT IF EXISTS fk_netra_klaim_bukti_doc_id" in schema_sql
    assert "ADD CONSTRAINT fk_netra_klaim_bukti_doc_id" not in schema_sql


def test_embed_multimodal_banyak_keyframe_dan_dokumen_masih_aktif(tmp_path, monkeypatch):
    from ai import dokumen_masih_aktif

    kf1 = tmp_path / "kf1.jpg"
    kf2 = tmp_path / "kf2.jpg"
    kf1.write_bytes(b"\xff\xd8\xff\xe0kf1")
    kf2.write_bytes(b"\xff\xd8\xff\xe0kf2")

    tertangkap = {}

    def fake_embed_parts(parts, **kw):
        tertangkap["parts"] = parts
        return [0.4, 0.5]

    monkeypatch.setattr("ai.embedding.embed_parts", fake_embed_parts)
    vek = embed_multimodal(teks="rapat koordinasi", media_paths=[kf1, kf2])
    assert vek == [0.4, 0.5]
    assert sum(1 for p in tertangkap["parts"] if "inlineData" in p) == 2
    assert any("text" in p for p in tertangkap["parts"])

    # dokumen_masih_aktif mengembalikan True jika baris ditemukan, False jika kosong/error DB
    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: _FakeConn(rows=[(1,)]))
    assert dokumen_masih_aktif("doc_aktif") is True

    monkeypatch.setattr("ai.rag._koneksi", lambda dsn=None: _FakeConn(rows=[]))
    assert dokumen_masih_aktif("doc_kosong") is False

    def db_err(dsn=None):
        raise RAGError("db mati")

    monkeypatch.setattr("ai.rag._koneksi", db_err)
    assert dokumen_masih_aktif("doc_err") is False


