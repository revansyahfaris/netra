"use client";

import { useEffect, useState } from "react";

const KUNCI = "netra:panduan-ditutup";

const LANGKAH = [
  {
    judul: "Pilih klaim",
    isi: "Konten viral dari sistem deteksi, diurutkan menurut sensitivitas dan kecepatan sebar.",
  },
  {
    judul: "Periksa paket bukti",
    isi: "Sumber paling awal, kecocokan frame dan audio, serta bagian yang diubah.",
  },
  {
    judul: "Putuskan sebagai petugas",
    isi: "Tidak ada klarifikasi yang tayang tanpa persetujuan manusia.",
  },
];

export function PanduanPanelis() {
  const [tampil, setTampil] = useState(false);

  useEffect(() => {
    try {
      setTampil(window.localStorage.getItem(KUNCI) !== "1");
    } catch {
      setTampil(true);
    }
  }, []);

  function tutup() {
    setTampil(false);
    try {
      window.localStorage.setItem(KUNCI, "1");
    } catch {
      /* penyimpanan browser tidak tersedia, cukup sembunyikan */
    }
  }

  if (!tampil) return null;

  return (
    <section className="rounded-xl border border-brand-100 bg-brand-50/60 px-5 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Panduan singkat</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-900">
            Netra tidak menebak hoaks. Netra membuktikannya.
          </h2>

        </div>
        <button
          type="button"
          onClick={tutup}
          className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-slate-500 hover:bg-white hover:text-slate-700"
          aria-label="Tutup panduan"
        >
          Tutup
        </button>
      </div>
      <ol className="mt-3 grid gap-2 md:grid-cols-3">
        {LANGKAH.map((l, i) => (
          <li key={l.judul} className="flex gap-2 text-xs leading-relaxed text-slate-600" title={l.isi}>
            <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-600 text-[11px] font-semibold text-white">
              {i + 1}
            </span>
            <span>
              <span className="font-semibold text-slate-900">{l.judul}.</span> {l.isi}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
