"use client";

import { useRef, useState } from "react";

import type { HasilVerifikasi, KandidatSumber, Klaim } from "@/lib/api";
import { formatTanggal, LABEL_PERUBAHAN } from "@/lib/format";

function idYoutube(url: string): string | null {
  const m = url.match(
    /(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([\w-]{11})/,
  );
  return m ? m[1] : null;
}

function namaSitus(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Pilih isi kartu "Faktanya": bukti dengan teks sumber, lalu kandidat teratas yang cocok. */
function susunFakta(verifikasi: HasilVerifikasi, kandidat: KandidatSumber[]) {
  const bukti =
    verifikasi.bukti.find((b) => b.teks_sumber) ?? verifikasi.bukti[0] ?? null;
  const urlSumber =
    bukti?.url ?? verifikasi.sumber_utama ?? kandidat[0]?.url ?? null;
  const k = kandidat.find((x) => x.url === urlSumber) ?? kandidat[0] ?? null;
  const ytId = (urlSumber && idYoutube(urlSumber)) || (k && idYoutube(k.url));
  return {
    teks: bukti?.teks_sumber || k?.judul || verifikasi.ringkasan || "",
    teksViral: bukti?.teks_viral || null,
    url: urlSumber,
    penerbit: k?.uploader || (urlSumber ? namaSitus(urlSumber) : null),
    tanggal: k?.tanggal_unggah ?? null,
    cuplikan: bukti?.cuplikan || k?.cuplikan || null,
    gambar:
      k?.thumbnail_url ||
      (ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null),
  };
}

export function SebelumSesudah({
  klaim,
  verifikasi,
  kandidat,
  simulasi = false,
}: {
  klaim: Klaim;
  verifikasi: HasilVerifikasi;
  kandidat: KandidatSumber[];
  /** true untuk kasus demo sintetis: kartu diberi label SIMULASI agar tidak dikira klarifikasi asli */
  simulasi?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [mengunduh, setMengunduh] = useState(false);
  const [galat, setGalat] = useState<string | null>(null);
  const [gambarGagal, setGambarGagal] = useState(false);

  const fakta = susunFakta(verifikasi, kandidat);
  const disetujui = verifikasi.status_persetujuan === "disetujui";

  async function unduh() {
    if (!ref.current) return;
    setMengunduh(true);
    setGalat(null);
    try {
      const { toPng } = await import("html-to-image");
      const dataUrl = await toPng(ref.current, {
        pixelRatio: 2,
        cacheBust: true,
        backgroundColor: "#ffffff",
        // Gambar dari domain lain yang menolak CORS diganti kotak kosong, bukan menggagalkan unduhan
        imagePlaceholder:
          "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='9'%3E%3Crect width='16' height='9' fill='%23e2e8f0'/%3E%3C/svg%3E",
      });
      const a = document.createElement("a");
      a.href = dataUrl;
      a.download = `netra-${klaim.claim_id}-sebelum-sesudah.png`;
      a.click();
    } catch {
      setGalat(
        "Gagal membuat gambar. Coba lagi, atau ambil tangkapan layar kartu ini.",
      );
    } finally {
      setMengunduh(false);
    }
  }

  return (
    <div className="px-5 py-4">
      <div className="mx-auto max-w-3xl">
        <div
          ref={ref}
          className="relative w-full overflow-hidden rounded-xl bg-white ring-1 ring-slate-200"
        >
          <div className="flex items-center justify-between bg-slate-900 px-5 py-3">
            <span className="text-sm font-semibold tracking-[0.2em] text-white">
              KLARIFIKASI
              {simulasi && (
                <span className="ml-2 rounded bg-white/15 px-1.5 py-0.5 text-[10px] tracking-normal">
                  SIMULASI
                </span>
              )}
            </span>
            <span
              className={
                disetujui
                  ? "rounded-full bg-emerald-500/20 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-200"
                  : "rounded-full bg-amber-400/20 px-2.5 py-0.5 text-[11px] font-semibold text-amber-200"
              }
            >
              {disetujui ? "Disetujui petugas" : "DRAF · belum disetujui"}
            </span>
          </div>

          <div className="grid sm:grid-cols-2">
            <div className="border-b border-slate-200 bg-rose-50/60 p-5 sm:border-b-0 sm:border-r">
              <p className="text-[11px] font-bold uppercase tracking-wider text-rose-700">
                Yang beredar
              </p>
              <p className="mt-3 text-base font-semibold leading-snug text-slate-900">
                “{fakta.teksViral || klaim.teks_klaim}”
              </p>
              <p className="mt-3 text-xs text-slate-500">
                Media sosial · {formatTanggal(klaim.tanggal_ditemukan)}
              </p>
            </div>

            <div className="bg-emerald-50/60 p-5">
              <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
                Faktanya
              </p>
              {fakta.gambar && !gambarGagal && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={fakta.gambar}
                  alt="Cuplikan sumber asli"
                  crossOrigin="anonymous"
                  onError={() => setGambarGagal(true)}
                  className="mt-3 aspect-video w-full rounded-md object-cover ring-1 ring-slate-200"
                />
              )}
              <p className="mt-3 text-sm leading-relaxed text-slate-800">
                {fakta.teks}
              </p>
              <p className="mt-3 text-xs text-slate-500">
                {[
                  fakta.penerbit,
                  fakta.tanggal ? formatTanggal(fakta.tanggal) : null,
                  fakta.cuplikan,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
          </div>

          {(verifikasi.perubahan.length > 0 || fakta.url) && (
            <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 px-5 py-3 text-xs text-slate-600">
              {verifikasi.perubahan.map((p) => (
                <span
                  key={p}
                  className="rounded-full bg-slate-100 px-2.5 py-0.5 font-medium text-slate-700"
                >
                  {LABEL_PERUBAHAN[p] ?? p}
                </span>
              ))}
              {fakta.url && (
                <span className="ml-auto text-slate-400">
                  Sumber: {namaSitus(fakta.url)}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mx-auto mt-3 flex max-w-3xl flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">
          Disusun dari bukti terverifikasi. Bagikan hanya setelah disetujui
          petugas.
        </p>
        <button
          type="button"
          onClick={() => void unduh()}
          disabled={mengunduh}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          {mengunduh ? "Menyiapkan…" : "Unduh PNG"}
        </button>
      </div>
      {galat && <p className="mt-2 text-xs text-rose-600">{galat}</p>}
    </div>
  );
}
