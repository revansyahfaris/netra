-- Skema tabel RAG multimodal untuk korpus resmi Netra (Neon PostgreSQL + pgvector)
-- Model embedding: Gemini Embedding 2 (outputDimensionality = 1536)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS netra_korpus_dokumen (
    doc_id TEXT PRIMARY KEY,
    judul TEXT NOT NULL,
    tanggal_terbit DATE,
    url TEXT NOT NULL,
    url_kanonis TEXT,
    jenis_sumber VARCHAR(16) NOT NULL DEFAULT 'resmi',
    jenis_media VARCHAR(16) NOT NULL DEFAULT 'teks',
    cakupan VARCHAR(16) NOT NULL DEFAULT 'resmi',
    kadaluwarsa_pada TIMESTAMPTZ,
    ringkasan TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    dibuat_pada TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE netra_korpus_dokumen
    ADD COLUMN IF NOT EXISTS url_kanonis TEXT;

ALTER TABLE netra_korpus_dokumen
    ADD COLUMN IF NOT EXISTS cakupan VARCHAR(16) NOT NULL DEFAULT 'resmi';

ALTER TABLE netra_korpus_dokumen
    ADD COLUMN IF NOT EXISTS kadaluwarsa_pada TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_netra_korpus_dokumen_url_kanonis
    ON netra_korpus_dokumen (url_kanonis);

CREATE INDEX IF NOT EXISTS ix_netra_korpus_dokumen_cakupan
    ON netra_korpus_dokumen (cakupan, kadaluwarsa_pada);

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

-- Tabel penghubung klaim <-> dokumen/chunk bukti yang dipakai Tier-1 & Tier-2 RAG
CREATE TABLE IF NOT EXISTS netra_klaim_bukti (
    id SERIAL PRIMARY KEY,
    claim_id VARCHAR(64) NOT NULL,
    doc_id TEXT REFERENCES netra_korpus_dokumen(doc_id) ON DELETE SET NULL,
    chunk_id INTEGER REFERENCES netra_korpus_chunk(chunk_id) ON DELETE SET NULL,
    tier VARCHAR(32) NOT NULL DEFAULT 'tier2_rag',
    metode VARCHAR(32) NOT NULL DEFAULT 'rag',
    peran VARCHAR(32) NOT NULL DEFAULT 'pembanding',
    skor DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    url TEXT NOT NULL,
    url_kanonis TEXT,
    cuplikan TEXT,
    catatan TEXT,
    dibuat_pada TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_netra_klaim_bukti_claim_id
    ON netra_klaim_bukti (claim_id);

CREATE INDEX IF NOT EXISTS ix_netra_klaim_bukti_doc_id
    ON netra_klaim_bukti (doc_id);

CREATE INDEX IF NOT EXISTS ix_netra_klaim_bukti_chunk_id
    ON netra_klaim_bukti (chunk_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = 'netra_klaim_bukti'::regclass
          AND c.contype = 'f'
          AND a.attname = 'doc_id'
    ) THEN
        ALTER TABLE netra_klaim_bukti
            ADD CONSTRAINT fk_netra_klaim_bukti_doc_id
            FOREIGN KEY (doc_id) REFERENCES netra_korpus_dokumen(doc_id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = 'netra_klaim_bukti'::regclass
          AND c.contype = 'f'
          AND a.attname = 'chunk_id'
    ) THEN
        ALTER TABLE netra_klaim_bukti
            ADD CONSTRAINT fk_netra_klaim_bukti_chunk_id
            FOREIGN KEY (chunk_id) REFERENCES netra_korpus_chunk(chunk_id) ON DELETE SET NULL;
    END IF;

    IF to_regclass('netra_klaim') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM pg_constraint c
           JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
           WHERE c.conrelid = 'netra_klaim_bukti'::regclass
             AND c.contype = 'f'
             AND a.attname = 'claim_id'
       ) THEN
        ALTER TABLE netra_klaim_bukti
            ADD CONSTRAINT fk_netra_klaim_bukti_claim_id
            FOREIGN KEY (claim_id) REFERENCES netra_klaim(claim_id) ON DELETE CASCADE;
    END IF;
END $$;

