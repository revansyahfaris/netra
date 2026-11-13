"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge, Card, Empty, ErrorBox, Skeleton, Stat } from "@/components/ui";
import { api, ApiError, type KlaimLengkap, type Statistik } from "@/lib/api";
import {
  cn,
  formatAngka,
  formatTanggal,
  LABEL_LEVEL,
  LABEL_PIPELINE,
  LABEL_VERIFIKASI,
  persen,
  WARNA_LEVEL,
  WARNA_PIPELINE,
  WARNA_VERIFIKASI,
} from "@/lib/format";

const FILTER_STATUS = [
  { nilai: "", label: "Semua" },
  { nilai: "menunggu_persetujuan", label: "Menunggu persetujuan" },
  { nilai: "diverifikasi", label: "Dieskalasi" },
  { nilai: "disetujui", label: "Disetujui" },
  { nilai: "ditolak", label: "Ditolak" },
  { nilai: "baru", label: "Baru" },
];

export default function HalamanAntrean() {
  const router = useRouter();
  const [data, setData] = useState<KlaimLengkap[] | null>(null);
  const [stat, setStat] = useState<Statistik | null>(null);
  const [galat, setGalat] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [level, setLevel] = useState("");
  const [cari, setCari] = useState("");
  const [menyegarkan, setMenyegarkan] = useState(false);

  const muat = useCallback(async () => {
    setGalat(null);
    try {
      const [antrean, statistik] = await Promise.all([api.antrean(), api.statistik()]);
      setData(antrean);
      setStat(statistik);
    } catch (e) {
      setGalat(e instanceof ApiError ? e.message : "Gagal memuat antrean.");
    }
  }, []);

  useEffect(() => {
    void muat();
  }, [muat]);

  const tersaring = useMemo(() => {
    if (!data) return [];
    const q = cari.trim().toLowerCase();
    return data.filter((item) => {
      if (status && item.klaim.status_pipeline !== status) return false;
      if (level && item.klaim.level !== level) return false;
      if (q) {
        const teks = `${item.klaim.claim_id} ${item.klaim.teks_klaim} ${item.klaim.label_topik ?? ""}`.toLowerCase();
        if (!teks.includes(q)) return false;
      }
      return true;
    });
  }, [data, status, level, cari]);

  async function resetDemo() {
    setMenyegarkan(true);
    try {
      await api.seed();
      await muat();
    } catch (e) {
      setGalat(e instanceof ApiError ? e.message : "Gagal reset data demo.");
    } finally {
      setMenyegarkan(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Antrean klaim</h1>
          <p className="mt-1 text-sm text-slate-500">
            Klaim dari sistem deteksi, diurutkan menurut prioritas. Petugas memutuskan setelah paket
            bukti lengkap.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void muat()}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Segarkan
          </button>
          <button
            type="button"
            onClick={() => void resetDemo()}
            disabled={menyegarkan}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-50 disabled:opacity-60"
            title="Mengembalikan data demo ke kondisi awal"
          >
            {menyegarkan ? "Menyiapkan…" : "Reset data demo"}
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Klaim di antrean" nilai={stat?.total_klaim ?? data?.length ?? "—"} />
        <Stat
          label="Menunggu persetujuan"
          nilai={stat?.menunggu_persetujuan ?? "—"}
          catatan="perlu keputusan petugas"
        />
        <Stat
          label="Dieskalasi"
          nilai={stat?.perlu_eskalasi ?? "—"}
          catatan="tidak bisa dipastikan otomatis"
        />
        <Stat
          label="Bukti terkumpul"
          nilai={stat?.jumlah_bukti ?? "—"}
          catatan={
            stat?.rata_rata_waktu_proses_detik
              ? `rata-rata proses ${stat.rata_rata_waktu_proses_detik}s`
              : undefined
          }
        />
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
          <div className="flex flex-wrap gap-1">
            {FILTER_STATUS.map((f) => (
              <button
                key={f.nilai}
                type="button"
                onClick={() => setStatus(f.nilai)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium transition",
                  status === f.nilai
                    ? "bg-slate-900 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <select
              id="filter-level"
              name="level"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-700"
            >
              <option value="">Semua level</option>
              <option value="tinggi">Tinggi</option>
              <option value="sedang">Sedang</option>
              <option value="rendah">Rendah</option>
            </select>
            <input
              id="cari-klaim"
              name="cari"
              value={cari}
              onChange={(e) => setCari(e.target.value)}
              placeholder="Cari klaim…"
              className="w-44 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs outline-none focus:border-brand-500"
            />
          </div>
        </div>

        {galat && (
          <div className="p-4">
            <ErrorBox pesan={galat} onRetry={() => void muat()} />
          </div>
        )}

        {!galat && data === null && <Skeleton baris={6} />}

        {!galat && data !== null && tersaring.length === 0 && (
          <Empty>Tidak ada klaim yang cocok dengan filter ini.</Empty>
        )}

        {!galat && tersaring.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Prioritas</th>
                  <th className="px-4 py-2.5 font-medium">Klaim</th>
                  <th className="px-4 py-2.5 font-medium">Topik</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Verifikasi</th>
                  <th className="px-4 py-2.5 font-medium">Bukti</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {tersaring.map(({ klaim, verifikasi }) => (
                  <tr
                    key={klaim.claim_id}
                    onClick={() => router.push(`/klaim/${klaim.claim_id}`)}
                    className="cursor-pointer transition hover:bg-slate-50"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-slate-900">
                          {klaim.skor_prioritas != null ? klaim.skor_prioritas.toFixed(2) : "—"}
                        </span>
                        {klaim.level && (
                          <span
                            className={cn(
                              "rounded px-1.5 py-0.5 text-[11px] font-semibold",
                              WARNA_LEVEL[klaim.level],
                            )}
                          >
                            {LABEL_LEVEL[klaim.level]}
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-[11px] text-slate-400">{formatTanggal(klaim.tanggal_ditemukan)}</p>
                    </td>
                    <td className="max-w-md px-4 py-3">
                      <p className="line-clamp-2 font-medium text-slate-800">{klaim.teks_klaim}</p>
                      <p className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
                        <span className="font-mono">{klaim.claim_id}</span>
                        <span>·</span>
                        <span>{klaim.jenis_media}</span>
                        <span>·</span>
                        <span>{formatAngka(klaim.jumlah_share)} share</span>
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs capitalize text-slate-600">{klaim.label_topik ?? "—"}</span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={WARNA_PIPELINE[klaim.status_pipeline]}>
                        {LABEL_PIPELINE[klaim.status_pipeline]}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {verifikasi ? (
                        <div className="space-y-1">
                          <Badge tone={WARNA_VERIFIKASI[verifikasi.status]}>
                            {LABEL_VERIFIKASI[verifikasi.status]}
                          </Badge>
                          {verifikasi.status === "terbukti_diubah" && (
                            <p className="text-[11px] text-slate-400">
                              {verifikasi.status_persetujuan === "menunggu"
                                ? `keyakinan ${persen(verifikasi.keyakinan)}`
                                : verifikasi.status_persetujuan}
                            </p>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">belum</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {verifikasi?.bukti.length ? `${verifikasi.bukti.length} item` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/klaim/${klaim.claim_id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-xs font-medium text-brand-600 hover:text-brand-700"
                      >
                        Buka →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}