"use client";

import { useEffect, useState } from "react";

const KUNCI = "netra:panduan-ditutup";

const LANGKAH = [
  {
    judul: "Pilih klaim",
    isi: "Antrean berisi konten viral dari sistem deteksi, sudah diurutkan menurut prioritas: seberapa sensitif topiknya dan seberapa cepat menyebar.",
  },
  {
    judul: "Periksa paket bukti",
    isi: "Netra melacak sumber paling awal, mencocokkan frame, audio, dan kutipan, lalu menunjukkan bagian mana yang diubah beserta buktinya.",
  },
  {
    judul: "Putuskan sebagai petugas",
    isi: "Setujui atau tolak draf klarifikasi. Tidak ada yang tayang tanpa persetujuan manusia. Setelah disetujui, buka halaman bukti publik.",
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
    <section className="rounded-xl border border-brand-100 bg-brand-50/60 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Panduan singkat</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-900">
            Netra tidak menebak hoaks. Netra membuktikannya.
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Deteksi sudah dikerjakan sistem lain. Netra mengambil alih setelahnya: mencari sumber asli,
            membuktikan apa yang diubah, dan menyiapkan klarifikasi untuk disetujui petugas.
          </p>
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
      <ol className="mt-4 grid gap-3 md:grid-cols-3">
        {LANGKAH.map((l, i) => (
          <li key={l.judul} className="rounded-lg border border-white bg-white/80 p-3">
            <p className="text-sm font-semibold text-slate-900">
              <span className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded-full bg-brand-600 text-[11px] text-white">
                {i + 1}
              </span>
              {l.judul}
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{l.isi}</p>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-slate-500">
        Klaim yang sudah diproses menampilkan hasil tersimpan. Menjalankan ulang pencarian memanggil
        layanan berbayar dan bisa memakan beberapa menit, jadi pada demo publik prosesnya dibatasi.
      </p>
    </section>
  );
}
