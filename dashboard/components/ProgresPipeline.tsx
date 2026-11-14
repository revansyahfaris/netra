"use client";

import { useEffect, useState } from "react";

import type { StatusPekerjaanPipeline } from "@/lib/api";
import { cn } from "@/lib/format";

type JenisMedia = "video" | "gambar" | "teks" | string;

interface Tahap {
  kunci: string;
  judul: string;
  ket: string;
  untuk?: JenisMedia[];
}

const TAHAP: Tahap[] = [
  {
    kunci: "ekstraksi",
    judul: "Ekstraksi konten",
    ket: "Unduh media, transkrip audio, teks di layar, keyframe",
    untuk: ["video", "gambar"],
  },
  {
    kunci: "pencarian",
    judul: "Cari sumber",
    ket: "Google, YouTube, dan media berita",
  },
  {
    kunci: "lens",
    judul: "Pencarian gambar",
    ket: "Google Lens pada keyframe",
    untuk: ["video", "gambar"],
  },
  {
    kunci: "frame",
    judul: "Cocokkan frame & audio",
    ket: "Bandingkan rekaman dengan kandidat",
    untuk: ["video"],
  },
  {
    kunci: "analisis",
    judul: "Analisis sumber",
    ket: "Baca isi sumber dan korpus resmi (RAG)",
  },
  {
    kunci: "verifikasi",
    judul: "Verifikasi silang",
    ket: "Tentukan apa yang diubah dan seberapa kuat buktinya",
  },
  {
    kunci: "klarifikasi",
    judul: "Susun hasil",
    ket: "Paket bukti dan draf klarifikasi",
  },
];

/** Format durasi detik menjadi "4m 07s" atau "12s". */
export function formatDurasi(detik: number | null | undefined): string {
  if (detik == null || !Number.isFinite(detik)) return "–";
  const d = Math.max(0, Math.round(detik));
  const m = Math.floor(d / 60);
  const s = d % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

export function ProgresPipeline({
  status,
  jenisMedia,
}: {
  status: StatusPekerjaanPipeline | null;
  jenisMedia: JenisMedia;
}) {
  const [sekarang, setSekarang] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setSekarang(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const daftar = TAHAP.filter((t) => !t.untuk || t.untuk.includes(jenisMedia));
  const riwayat = status?.riwayat_tahap ?? [];
  const mulaiTahap = new Map(
    riwayat.map((r) => [r.tahap, new Date(r.mulai).getTime()]),
  );
  const saatIni = status?.tahap_saat_ini ?? "mulai";
  const idxSaatIni = daftar.findIndex((t) => t.kunci === saatIni);
  const mulaiTotal = status?.dimulai_pada
    ? new Date(status.dimulai_pada).getTime()
    : null;
  const total = mulaiTotal ? (sekarang - mulaiTotal) / 1000 : null;

  function durasiTahap(i: number): number | null {
    const awal = mulaiTahap.get(daftar[i].kunci);
    if (awal == null) return null;
    for (let j = i + 1; j < daftar.length; j++) {
      const berikut = mulaiTahap.get(daftar[j].kunci);
      if (berikut != null) return (berikut - awal) / 1000;
    }
    return (sekarang - awal) / 1000;
  }

  return (
    <div className="px-5 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-600" />
          </span>
          <p className="text-sm font-semibold text-slate-800">
            Netra sedang memverifikasi
          </p>
        </div>
        <p className="font-mono text-sm text-slate-600">
          {formatDurasi(total)}
          <span className="ml-1 font-sans text-xs text-slate-400">
            berjalan
          </span>
        </p>
      </div>
      <p className="mt-0.5 text-xs text-slate-500">
        Biasanya beberapa menit untuk video. Halaman ini boleh ditinggal;
        hasilnya tersimpan otomatis.
      </p>

      <ol className="mt-4 space-y-0">
        {daftar.map((t, i) => {
          const tercapai = mulaiTahap.has(t.kunci);
          const aktif = t.kunci === saatIni;
          const selesai =
            tercapai && !aktif && (idxSaatIni === -1 || i < idxSaatIni);
          const dilewati = !tercapai && idxSaatIni > i;
          const durasi = tercapai ? durasiTahap(i) : null;
          const terakhir = i === daftar.length - 1;
          return (
            <li key={t.kunci} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                    selesai && "bg-emerald-500 text-white",
                    aktif && "bg-brand-600 text-white",
                    dilewati && "bg-slate-100 text-slate-300",
                    !selesai &&
                      !aktif &&
                      !dilewati &&
                      "bg-slate-100 text-slate-400",
                  )}
                >
                  {selesai ? (
                    "✓"
                  ) : aktif ? (
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                  ) : (
                    i + 1
                  )}
                </span>
                {!terakhir && (
                  <span
                    className={cn(
                      "my-1 w-px flex-1",
                      selesai ? "bg-emerald-300" : "bg-slate-200",
                    )}
                  />
                )}
              </div>
              <div className={cn("min-w-0 flex-1", terakhir ? "pb-0" : "pb-3")}>
                <div className="flex items-baseline justify-between gap-2">
                  <p
                    className={cn(
                      "text-sm",
                      aktif
                        ? "font-semibold text-slate-900"
                        : selesai
                          ? "text-slate-700"
                          : "text-slate-400",
                    )}
                  >
                    {t.judul}
                    {dilewati && (
                      <span className="ml-1.5 text-xs font-normal">
                        · dilewati
                      </span>
                    )}
                  </p>
                  {durasi != null && (
                    <span
                      className={cn(
                        "font-mono text-xs",
                        aktif ? "text-brand-700" : "text-slate-400",
                      )}
                    >
                      {formatDurasi(durasi)}
                    </span>
                  )}
                </div>
                {(aktif || selesai) && (
                  <p className="text-xs text-slate-500">{t.ket}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
