"""Tabel penyimpanan Netra.

Pola: kolom yang sering difilter jadi kolom biasa, sisanya snapshot JSON utuh.
Dengan begitu kontrak data bisa berubah tanpa migrasi besar.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class KlaimRow(Base):
    __tablename__ = "netra_klaim"

    claim_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status_pipeline: Mapped[str] = mapped_column(String(32), index=True, default="baru")
    skor_prioritas: Mapped[float] = mapped_column(Float, index=True, default=0.0)
    tanggal_ditemukan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    diperbarui: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PencarianRow(Base):
    __tablename__ = "netra_pencarian"

    claim_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("netra_klaim.claim_id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(16), default="demo")
    data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    proses: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    diperbarui: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerifikasiRow(Base):
    __tablename__ = "netra_verifikasi"

    claim_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("netra_klaim.claim_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    status_persetujuan: Mapped[str] = mapped_column(String(16), index=True, default="menunggu")
    perlu_eskalasi: Mapped[bool] = mapped_column(default=False)
    data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    diperbarui: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KlaimBuktiRow(Base):
    __tablename__ = "netra_klaim_bukti"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("netra_klaim.claim_id", ondelete="CASCADE"), index=True
    )
    doc_id: Mapped[str | None] = mapped_column(String(128), index=True)
    chunk_id: Mapped[int | None] = mapped_column(Integer, index=True)
    tier: Mapped[str] = mapped_column(String(32), default="tier2_rag")
    metode: Mapped[str] = mapped_column(String(32), default="rag")
    peran: Mapped[str] = mapped_column(String(32), default="pembanding")
    skor: Mapped[float] = mapped_column(Float, default=0.0)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_kanonis: Mapped[str | None] = mapped_column(Text)
    cuplikan: Mapped[str | None] = mapped_column(Text)
    catatan: Mapped[str | None] = mapped_column(Text)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditRow(Base):
    __tablename__ = "netra_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(String(64), index=True)
    aksi: Mapped[str] = mapped_column(String(64))
    aktor: Mapped[str | None] = mapped_column(String(128))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)