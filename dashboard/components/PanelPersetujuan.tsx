"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type HasilVerifikasi } from "@/lib/api";
import { formatTanggalWaktu, LABEL_VERIFIKASI, WARNA_VERIFIKASI } from "@/lib/format";
import { Badge, ErrorBox } from "./ui";

const KUNCI_PETUGAS = "netra.petugas";

export function PanelPersetujuan({
  claimId,
  verifikasi,
  onSelesai,
}: {
  claimId: string;
  verifikasi: HasilVerifikasi | null;
  onSelesai: () => void;
}) {
  const [petugas, setPetugas] = useState("");
  const [catatan, setCatatan] = useState("");
  const [proses, setProses] = useState<"disetujui" | "ditolak" | null>(null);
  const [galat, setGalat] = useState<string | null>(null);

  useEffect(() => {
    const tersimpan = window.localStorage.getItem(KUNCI_PETUGAS);
    if (tersimpan) setPetugas(tersimpan);
  }, []);

  if (!verifikasi) {
    return (
      <div className="px-5 py-6 text-sm text-slate-500">
        Jalankan verifikasi dulu. Panel persetujuan muncul setelah ada draf klarifikasi.
      </div>
    );
  }

  if (verifikasi.status !== "terbukti_diubah") {
    return (
      <div className="space-y-3 px-5 py-5">
        <Badge tone={WARNA_VERIFIKASI[verifikasi.status]}>{LABEL_VERIFIKASI[verifikasi.status]}</Badge>
        <p className="text-sm text-slate-700">
          Status ini <span className="font-semibold">tidak melewati persetujuan klarifikasi</span>. Klaim
          dieskalasi ke petugas untuk diperiksa manual.
        </p>
        <p className="text-xs text-slate-500">
          Sistem tidak memaksakan klarifikasi saat sumber asli tidak bisa dipastikan.
        </p>
      </div>
    );
  }

  if (verifikasi.status_persetujuan !== "menunggu") {
    const disetujui = verifikasi.status_persetujuan === "disetujui";
    return (
      <div className="space-y-2 px-5 py-5">
        <Badge
          tone={
            disetujui
              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
              : "bg-rose-50 text-rose-700 ring-rose-200"
          }
        >
          {disetujui ? "Disetujui" : "Ditolak"} oleh {verifikasi.disetujui_oleh ?? "petugas"}
        </Badge>
        <p className="text-xs text-slate-500">
          {formatTanggalWaktu(verifikasi.waktu_persetujuan)}
        </p>
        {verifikasi.catatan_petugas && (
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700 ring-1 ring-inset ring-slate-200">
            {verifikasi.catatan_petugas}
          </p>
        )}
        {disetujui && (
          <a
            href={`/bukti/${claimId}`}
            className="inline-block text-sm font-medium text-brand-600 hover:text-brand-700"
          >
            Buka halaman bukti publik →
          </a>
        )}
      </div>
    );
  }

  async function kirim(keputusan: "disetujui" | "ditolak") {
    setGalat(null);
    if (petugas.trim().length < 2) {
      setGalat("Isi nama petugas dulu (minimal 2 karakter).");
      return;
    }
    if (keputusan === "ditolak" && !catatan.trim()) {
      setGalat("Penolakan wajib disertai catatan alasan.");
      return;
    }
    setProses(keputusan);
    try {
      window.localStorage.setItem(KUNCI_PETUGAS, petugas.trim());
      await api.putuskan(claimId, { keputusan, petugas: petugas.trim(), catatan: catatan.trim() || undefined });
      onSelesai();
    } catch (e) {
      setGalat(e instanceof ApiError ? e.message : "Gagal menyimpan keputusan.");
    } finally {
      setProses(null);
    }
  }

  return (
    <div className="space-y-4 px-5 py-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Bertindak sebagai</span>
          <input
            id="nama-petugas"
            name="petugas"
            value={petugas}
            onChange={(e) => setPetugas(e.target.value)}
            placeholder="Nama petugas"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Catatan (wajib bila menolak)</span>
          <input
            id="catatan-petugas"
            name="catatan"
            value={catatan}
            onChange={(e) => setCatatan(e.target.value)}
            placeholder="Mis. sumber belum cukup kuat"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
          />
        </label>
      </div>

      {galat && <ErrorBox pesan={galat} />}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={proses !== null}
          onClick={() => kirim("disetujui")}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {proses === "disetujui" ? "Menyimpan…" : "Setujui klarifikasi"}
        </button>
        <button
          type="button"
          disabled={proses !== null}
          onClick={() => kirim("ditolak")}
          className="rounded-lg border border-rose-300 bg-white px-4 py-2 text-sm font-semibold text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {proses === "ditolak" ? "Menyimpan…" : "Tolak / minta perbaikan"}
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Keputusan tercatat di audit trail. Klarifikasi tidak pernah tayang otomatis.
      </p>
    </div>
  );
}