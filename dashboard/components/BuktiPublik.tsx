"use client";

import { useEffect, useState } from "react";

import {
  Badge,
  Card,
  Empty,
  ErrorBox,
  Skeleton,
} from "@/components/ui";
import { api, ApiError, type BuktiPublik } from "@/lib/api";
import {
  formatTanggal,
  formatTanggalWaktu,
  LABEL_JENIS_BUKTI,
  LABEL_METODE,
  LABEL_PERUBAHAN,
  LABEL_VERIFIKASI,
  persen,
} from "@/lib/format";

export function HalamanBukti({ id }: { id: string }) {
  const [data, setData] = useState<BuktiPublik | null>(null);
  const [galat, setGalat] = useState<string | null>(null);

  useEffect(() => {
    api
      .buktiPublik(id)
      .then(setData)
      .catch((e) => setGalat(e instanceof ApiError ? e.message : "Gagal memuat halaman bukti."));
  }, [id]);

  if (galat) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-12">
        <ErrorBox pesan={galat} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-12">
        <Card>
          <Skeleton baris={8} />
        </Card>
      </div>
    );
  }

  const status = data.status;

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-5 py-4">
          <div>
            <p className="text-base font-semibold tracking-[0.2em] text-slate-900">NETRA</p>
            <p className="text-xs text-slate-500">Halaman bukti publik</p>
          </div>
          {data.simulasi && (
            <span className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-800">
              SIMULASI
            </span>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-4 px-5 py-8">
        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 bg-slate-50 px-6 py-4">
            <div className="flex flex-wrap items-center gap-2">
              {status ? (
                <Badge
                  tone={
                    status === "terbukti_diubah"
                      ? "bg-rose-600 text-white ring-rose-600"
                      : "bg-amber-500 text-white ring-amber-500"
                  }
                >
                  {LABEL_VERIFIKASI[status]}
                </Badge>
              ) : (
                <Badge tone="bg-slate-200 text-slate-700 ring-slate-200">Belum diverifikasi</Badge>
              )}
              {!data.disetujui && (
                <Badge tone="bg-slate-100 text-slate-600 ring-slate-200">
                  draf belum disetujui petugas
                </Badge>
              )}
              <span className="ml-auto font-mono text-xs text-slate-400">{data.claim_id}</span>
            </div>
          </div>

          <div className="px-6 py-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Klaim yang beredar</p>
            <p className="mt-1 text-lg font-medium leading-snug text-slate-900">{data.teks_klaim}</p>
            <p className="mt-2 text-xs text-slate-500">
              {data.jenis_media} · ditemukan {formatTanggal(data.tanggal_ditemukan)}
              {data.media_url ? " · konten viral ditautkan di sumber di bawah" : ""}
            </p>
          </div>

          {data.ringkasan && (
            <div className="border-t border-slate-100 px-6 py-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Fakta</p>
              <p className="mt-1 text-sm leading-relaxed text-slate-800">{data.ringkasan}</p>
              {data.perubahan.length > 0 && (
                <ul className="mt-3 flex flex-wrap gap-1.5">
                  {data.perubahan.map((p) => (
                    <li
                      key={p}
                      className="rounded-full bg-rose-50 px-2.5 py-0.5 text-xs font-medium text-rose-700 ring-1 ring-inset ring-rose-200"
                    >
                      {LABEL_PERUBAHAN[p] ?? p}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {data.bukti.length > 0 && (
            <div className="border-t border-slate-100 px-6 py-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Bukti</p>
              <ul className="mt-2 space-y-3">
                {data.bukti.map((b, i) => (
                  <li key={`${b.url}-${i}`} className="rounded-lg border border-slate-200 px-3 py-2.5">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">
                        {LABEL_JENIS_BUKTI[b.jenis] ?? b.jenis}
                      </span>
                      {b.cuplikan && <span className="font-mono">{b.cuplikan}</span>}
                      <a
                        href={b.url}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-auto truncate text-brand-600 hover:underline"
                      >
                        {new URL(b.url).hostname.replace("www.", "")}
                      </a>
                    </div>
                    {b.teks_sumber && (
                      <p className="mt-1 text-sm text-slate-700">
                        <span className="font-medium">Sumber asli:</span> {b.teks_sumber}
                      </p>
                    )}
                    {b.teks_viral && (
                      <p className="mt-0.5 text-sm text-slate-500">
                        <span className="font-medium">Konten viral:</span> {b.teks_viral}
                      </p>
                    )}
                    {b.catatan && <p className="mt-1 text-xs text-slate-500">{b.catatan}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.sumber_utama && (
            <div className="border-t border-slate-100 px-6 py-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sumber asli</p>
              <a
                href={data.sumber_utama}
                target="_blank"
                rel="noreferrer"
                className="mt-1 block break-all text-sm text-brand-600 hover:underline"
              >
                {data.sumber_utama}
              </a>
            </div>
          )}

          <div className="border-t border-slate-100 bg-slate-50 px-6 py-4 text-xs text-slate-500">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              {data.metode.map((m) => (
                <span key={m}>{LABEL_METODE[m] ?? m}</span>
              ))}
              {data.keyakinan != null && <span>keyakinan {persen(data.keyakinan)}</span>}
              {data.waktu_verifikasi && <span>diverifikasi {formatTanggalWaktu(data.waktu_verifikasi)}</span>}
              {data.waktu_persetujuan && <span>disetujui {formatTanggalWaktu(data.waktu_persetujuan)}</span>}
            </div>
          </div>
        </Card>

        {data.klarifikasi && (
          <Card>
            <div className="px-6 py-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Klarifikasi resmi</p>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                {data.klarifikasi.pendek}
              </p>
            </div>
          </Card>
        )}

        {!data.disetujui && (
          <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
            Klarifikasi untuk klaim ini belum disetujui petugas. Halaman ini menampilkan bukti yang sudah
            terkumpul, bukan pernyataan resmi.
          </p>
        )}

        {status !== "terbukti_diubah" && status != null && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
            Sumber asli belum bisa dipastikan. Klaim ini dieskalasi ke petugas untuk pemeriksaan manual;
            sistem tidak memaksakan klarifikasi.
          </p>
        )}

        <p className="pt-2 text-center text-xs text-slate-400">
          Netra · prototipe Dispenad · halaman ini hanya menampilkan data yang layak publik
        </p>
      </main>
    </div>
  );
}