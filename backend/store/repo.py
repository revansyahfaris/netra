"""Repository: satu-satunya pintu masuk penyimpanan untuk API.

API tidak menyimpan apa pun di variabel global lagi. Semua lewat sini supaya data
bertahan setelah restart dan bisa diperiksa ulang.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from schemas import (
    HasilPencarian,
    HasilVerifikasi,
    Klaim,
    KlaimLengkap,
    RiwayatAksi,
)

from .models import AuditRow, KlaimRow, PencarianRow, VerifikasiRow


class TidakDitemukan(Exception):
    """Data yang diminta tidak ada."""


class TidakBoleh(Exception):
    """Aksi tidak sah menurut state machine."""


def _sekarang() -> datetime:
    return datetime.now(timezone.utc)


class Repo:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._s = session_factory

    # ---------- klaim ----------

    def simpan_klaim(self, klaim: Klaim, aktor: str | None = None) -> Klaim:
        data = klaim.model_dump(mode="json")
        with self._s() as ses:
            row = ses.get(KlaimRow, klaim.claim_id)
            if row is None:
                row = KlaimRow(
                    claim_id=klaim.claim_id,
                    status_pipeline=klaim.status_pipeline,
                    skor_prioritas=klaim.skor_prioritas or 0.0,
                    tanggal_ditemukan=klaim.tanggal_ditemukan,
                    data=data,
                    diperbarui=_sekarang(),
                )
                ses.add(row)
                aksi = "klaim_dibuat"
            else:
                lama = Klaim.model_validate(row.data)
                # Jangan turunkan status yang sudah maju hanya karena klaim dikirim ulang
                if klaim.status_pipeline == "baru" and lama.status_pipeline != "baru":
                    klaim = klaim.model_copy(update={"status_pipeline": lama.status_pipeline})
                    data = klaim.model_dump(mode="json")
                row.status_pipeline = klaim.status_pipeline
                row.skor_prioritas = klaim.skor_prioritas or 0.0
                row.tanggal_ditemukan = klaim.tanggal_ditemukan
                row.data = data
                row.diperbarui = _sekarang()
                aksi = "klaim_diperbarui"
            self._catat(ses, klaim.claim_id, aksi, aktor, {"skor": klaim.skor_prioritas})
            ses.commit()
        return klaim

    def ambil_klaim(self, claim_id: str) -> Klaim | None:
        with self._s() as ses:
            row = ses.get(KlaimRow, claim_id)
            return Klaim.model_validate(row.data) if row else None

    def daftar_klaim(self, status: str | None = None, level: str | None = None,
                     urut: str = "prioritas") -> list[Klaim]:
        with self._s() as ses:
            q = select(KlaimRow)
            if status:
                q = q.where(KlaimRow.status_pipeline == status)
            q = q.order_by(KlaimRow.skor_prioritas.desc(), KlaimRow.tanggal_ditemukan.desc())
            hasil = [Klaim.model_validate(r.data) for r in ses.scalars(q)]
        if level:
            hasil = [k for k in hasil if k.level == level]
        return hasil

    # ---------- pencarian ----------

    def simpan_pencarian(self, hasil: HasilPencarian, proses: dict | None = None,
                         aktor: str | None = None) -> HasilPencarian:
        now = _sekarang()
        hasil = hasil.model_copy(update={"diperbarui": now})
        with self._s() as ses:
            row = ses.get(PencarianRow, hasil.claim_id)
            if row is None:
                row = PencarianRow(claim_id=hasil.claim_id)
                ses.add(row)
            row.mode = hasil.mode
            row.data = hasil.model_dump(mode="json")
            row.proses = proses or {}
            row.diperbarui = now
            krow = ses.get(KlaimRow, hasil.claim_id)
            if krow and krow.status_pipeline in ("baru", "dicari"):
                k = Klaim.model_validate(krow.data)
                k = k.model_copy(update={"status_pipeline": "dicari"})
                krow.data = k.model_dump(mode="json")
                krow.status_pipeline = "dicari"
            self._catat(ses, hasil.claim_id, "pencarian", aktor,
                        {"jumlah_kandidat": len(hasil.kandidat), "mode": hasil.mode})
            ses.commit()
        return hasil

    def ambil_pencarian(self, claim_id: str) -> tuple[HasilPencarian, dict] | None:
        with self._s() as ses:
            row = ses.get(PencarianRow, claim_id)
            if not row:
                return None
            return HasilPencarian.model_validate(row.data), row.proses or {}

    # ---------- verifikasi ----------

    def simpan_verifikasi(self, hasil: HasilVerifikasi, aktor: str | None = None) -> HasilVerifikasi:
        now = _sekarang()
        hasil = hasil.model_copy(update={"waktu_verifikasi": hasil.waktu_verifikasi or now})
        with self._s() as ses:
            row = ses.get(VerifikasiRow, hasil.claim_id)
            if row is None:
                row = VerifikasiRow(claim_id=hasil.claim_id)
                ses.add(row)
            row.status = hasil.status
            row.status_persetujuan = hasil.status_persetujuan
            row.perlu_eskalasi = hasil.perlu_eskalasi
            row.data = hasil.model_dump(mode="json")
            row.diperbarui = now
            krow = ses.get(KlaimRow, hasil.claim_id)
            if krow:
                k = Klaim.model_validate(krow.data)
                baru = "menunggu_persetujuan" if hasil.status == "terbukti_diubah" else "diverifikasi"
                k = k.model_copy(update={"status_pipeline": baru})
                krow.data = k.model_dump(mode="json")
                krow.status_pipeline = baru
            self._catat(ses, hasil.claim_id, "verifikasi", aktor,
                        {"status": hasil.status, "perlu_eskalasi": hasil.perlu_eskalasi})
            ses.commit()
        return hasil

    def ambil_verifikasi(self, claim_id: str) -> HasilVerifikasi | None:
        with self._s() as ses:
            row = ses.get(VerifikasiRow, claim_id)
            return HasilVerifikasi.model_validate(row.data) if row else None

    # ---------- persetujuan ----------

    def setujui(self, claim_id: str, keputusan: str, petugas: str,
                catatan: str | None = None) -> HasilVerifikasi:
        if keputusan not in ("disetujui", "ditolak"):
            raise TidakBoleh("Keputusan harus 'disetujui' atau 'ditolak'")
        with self._s() as ses:
            vrow = ses.get(VerifikasiRow, claim_id)
            if vrow is None:
                raise TidakDitemukan("Belum ada hasil verifikasi untuk klaim ini")
            hv = HasilVerifikasi.model_validate(vrow.data)
            if hv.status != "terbukti_diubah":
                raise TidakBoleh("Status ini dieskalasi ke petugas, bukan lewat persetujuan klarifikasi")
            if hv.status_persetujuan != "menunggu":
                raise TidakBoleh(f"Sudah diputuskan: {hv.status_persetujuan}")
            if keputusan == "ditolak" and not (catatan or "").strip():
                raise TidakBoleh("Penolakan wajib disertai catatan")

            now = _sekarang()
            hv = hv.model_copy(update={
                "status_persetujuan": keputusan,
                "catatan_petugas": catatan,
                "disetujui_oleh": petugas,
                "waktu_persetujuan": now,
            })
            vrow.data = hv.model_dump(mode="json")
            vrow.status_persetujuan = keputusan
            vrow.diperbarui = now

            krow = ses.get(KlaimRow, claim_id)
            if krow:
                k = Klaim.model_validate(krow.data)
                k = k.model_copy(update={"status_pipeline": keputusan})
                krow.data = k.model_dump(mode="json")
                krow.status_pipeline = keputusan

            self._catat(ses, claim_id, f"persetujuan_{keputusan}", petugas, {"catatan": catatan})
            ses.commit()
        return hv

    # ---------- audit & dokumen lengkap ----------

    def _catat(self, ses: Session, claim_id: str, aksi: str, aktor: str | None,
               detail: dict | None = None) -> None:
        ses.add(AuditRow(claim_id=claim_id, aksi=aksi, aktor=aktor,
                         waktu=_sekarang(), detail=detail or {}))

    def catat(self, claim_id: str, aksi: str, aktor: str | None = None,
              detail: dict | None = None) -> None:
        with self._s() as ses:
            self._catat(ses, claim_id, aksi, aktor, detail)
            ses.commit()

    def riwayat(self, claim_id: str) -> list[RiwayatAksi]:
        with self._s() as ses:
            q = select(AuditRow).where(AuditRow.claim_id == claim_id).order_by(AuditRow.waktu, AuditRow.id)
            return [RiwayatAksi(aksi=r.aksi, aktor=r.aktor, waktu=r.waktu, detail=r.detail or {})
                    for r in ses.scalars(q)]

    def ambil_lengkap(self, claim_id: str) -> KlaimLengkap | None:
        klaim = self.ambil_klaim(claim_id)
        if klaim is None:
            return None
        pencarian = self.ambil_pencarian(claim_id)
        return KlaimLengkap(
            klaim=klaim,
            pencarian=pencarian[0] if pencarian else None,
            proses_pencarian=pencarian[1] if pencarian else None,
            verifikasi=self.ambil_verifikasi(claim_id),
            riwayat=self.riwayat(claim_id),
        )

    def daftar_lengkap(self, status: str | None = None, level: str | None = None) -> list[KlaimLengkap]:
        return [self.ambil_lengkap(k.claim_id) for k in self.daftar_klaim(status, level)]

    # ---------- statistik & utilitas ----------

    def statistik(self) -> dict:
        with self._s() as ses:
            total = ses.scalar(select(func.count()).select_from(KlaimRow)) or 0
            pipeline = dict(ses.execute(select(KlaimRow.status_pipeline, func.count())
                                        .group_by(KlaimRow.status_pipeline)).all())
            verifikasi = dict(ses.execute(select(VerifikasiRow.status, func.count())
                                          .group_by(VerifikasiRow.status)).all())
            eskalasi = ses.scalar(select(func.count()).select_from(VerifikasiRow)
                                  .where(VerifikasiRow.perlu_eskalasi.is_(True))) or 0
            menunggu = ses.scalar(select(func.count()).select_from(VerifikasiRow)
                                  .where(VerifikasiRow.status_persetujuan == "menunggu")
                                  .where(VerifikasiRow.status == "terbukti_diubah")) or 0
            rows = list(ses.scalars(select(VerifikasiRow)))
        waktu = [r.data.get("waktu_proses_detik") for r in rows if r.data.get("waktu_proses_detik")]
        bukti = sum(len(r.data.get("bukti") or []) for r in rows)
        return {
            "total_klaim": total,
            "per_status_pipeline": pipeline,
            "per_status_verifikasi": verifikasi,
            "perlu_eskalasi": eskalasi,
            "menunggu_persetujuan": menunggu,
            "jumlah_bukti": bukti,
            "rata_rata_waktu_proses_detik": round(sum(waktu) / len(waktu), 1) if waktu else None,
        }

    def hapus_semua(self) -> None:
        with self._s() as ses:
            for model in (AuditRow, VerifikasiRow, PencarianRow, KlaimRow):
                ses.query(model).delete()
            ses.commit()


_repo: Repo | None = None


def get_repo() -> Repo:
    global _repo
    if _repo is None:
        from .db import get_session_factory, init_db
        init_db()
        _repo = Repo(get_session_factory())
    return _repo


def set_repo(repo: Repo | None) -> None:
    """Untuk tes."""
    global _repo
    _repo = repo