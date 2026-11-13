-- Skema tabel RAG multimodal untuk korpus resmi Netra (Neon PostgreSQL + pgvector)
-- Model embedding: Gemini Embedding 2 (outputDimensionality = 1536)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS netra_korpus_dokumen (
    doc_id TEXT PRIMARY KEY,
    judul TEXT NOT NULL,
    tanggal_terbit DATE,
    url TEXT NOT NULL,
    jenis_sumber VARCHAR(16) NOT NULL DEFAULT 'resmi',
    jenis_media VARCHAR(16) NOT NULL DEFAULT 'teks',
    ringkasan TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    dibuat_pada TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS netra_korpus_chunk (
    chunk_id SERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES netra_korpus_dokumen(doc_id) ON DELETE CASCADE,
    urutan INTEGER NOT NULL DEFAULT 0,
    jenis_konten VARCHAR(16) NOT NULL DEFAULT 'teks',
    isi_teks TEXT NOT NULL DEFAULT '',
    detik_mulai DOUBLE PRECISION,
    detik_selesai DOUBLE PRECISION,
    lokasi_media TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536),
    fts tsvector GENERATED ALWAYS AS (
        to_tsvector('indonesian', COALESCE(isi_teks, ''))
    ) STORED,
    dibuat_pada TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (doc_id, urutan)
);

CREATE INDEX IF NOT EXISTS ix_netra_korpus_chunk_doc_id
    ON netra_korpus_chunk (doc_id);

CREATE INDEX IF NOT EXISTS ix_netra_korpus_chunk_fts
    ON netra_korpus_chunk USING GIN (fts);

CREATE INDEX IF NOT EXISTS ix_netra_korpus_chunk_embedding_hnsw
    ON netra_korpus_chunk USING hnsw (embedding vector_cosine_ops);

