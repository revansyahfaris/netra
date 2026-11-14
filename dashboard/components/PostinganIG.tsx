"use client";

import { useRef, useState, type ReactNode } from "react";

import type { DrafKlarifikasi, HasilVerifikasi, KandidatSumber, Klaim } from "@/lib/api";
import { formatTanggal, LABEL_PERUBAHAN } from "@/lib/format";
import { CopyButton } from "./ui";

/** Ukuran feed Instagram 4:5 */
const LEBAR = 1080;
const TINGGI = 1350;
const SKALA_PRATINJAU = 0.28;

const VONIS: Record<string, string> = {
  tanggal_berbeda: "VIDEO LAMA",
  konteks_berbeda: "KONTEKS KELIRU",
  kutipan_tidak_ada: "KUTIPAN PALSU",
  dipotong: "DIPOTONG",
  lainnya: "KELIRU",
};

function idYoutube(url: string): string | null {
  const m = url.match(/(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([\w-]{11})/);
  return m ? m[1] : null;
}

function namaSitus(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function susunIsi(verifikasi: HasilVerifikasi, kandidat: KandidatSumber[], kartu: string) {
  const bukti = verifikasi.bukti.find((b) => b.teks_sumber) ?? verifikasi.bukti[0] ?? null;
  const urlSumber = bukti?.url ?? verifikasi.sumber_utama ?? kandidat[0]?.url ?? null;
  const k = kandidat.find((x) => x.url === urlSumber) ?? kandidat[0] ?? null;
  const ytId = (urlSumber && idYoutube(urlSumber)) || (k && idYoutube(k.url));
  const sumber = verifikasi.bukti
    .filter((b, i, arr) => arr.findIndex((x) => namaSitus(x.url) === namaSitus(b.url)) === i)
    .slice(0, 3)
    .map((b) => {
      const kk = kandidat.find((x) => x.url === b.url);
      return {
        situs: kk?.uploader || namaSitus(b.url),
        tanggal: kk?.tanggal_unggah ? formatTanggal(kk.tanggal_unggah) : null,
      };
    });
  return {
    fakta: bukti?.teks_sumber || k?.judul || verifikasi.ringkasan || "",
    // Teks kartu dari draf klarifikasi memang ditulis untuk publik (tanpa jargon internal)
    penjelasan: kartu || null,
    viral: bukti?.teks_viral || null,
    penerbit: k?.uploader || (urlSumber ? namaSitus(urlSumber) : null),
    tanggal: k?.tanggal_unggah ?? null,
    gambar: k?.thumbnail_url || (ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null),
    sumber,
  };
}

function Slide({ children, refEl }: { children: ReactNode; refEl: (el: HTMLDivElement | null) => void }) {
  return (
    <div
      className="shrink-0 overflow-hidden rounded-lg ring-1 ring-slate-200"
      style={{ width: LEBAR * SKALA_PRATINJAU, height: TINGGI * SKALA_PRATINJAU }}
    >
      <div style={{ transform: `scale(${SKALA_PRATINJAU})`, transformOrigin: "top left" }}>
        <div
          ref={refEl}
          style={{ width: LEBAR, height: TINGGI, fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif" }}
          className="relative flex flex-col bg-[#0b1530] text-white"
        >
          {children}
        </div>
      </div>
    </div>
  );
}

function Kepala({ simulasi, disetujui, nomor }: { simulasi: boolean; disetujui: boolean; nomor: number }) {
  return (
    <div className="flex items-center justify-between px-[80px] pt-[72px]">
      <span className="text-[30px] font-bold tracking-[0.3em] text-white/90">
        KLARIFIKASI
        {simulasi && (
          <span className="ml-4 rounded-md bg-white/15 px-3 py-1 text-[22px] tracking-normal">SIMULASI</span>
        )}
      </span>
      <span className="text-[26px] font-semibold text-white/50">
        {!disetujui && <span className="mr-5 rounded-md bg-amber-400 px-3 py-1 text-[#0b1530]">DRAF</span>}
        {nomor}/3
      </span>
    </div>
  );
}

function Kaki() {
  return (
    <div className="mt-auto flex items-center justify-between border-t border-white/10 px-[80px] py-[44px] text-[24px] text-white/50">
      <span>Cek dulu sebelum menyebarkan.</span>
      <span className="font-semibold tracking-[0.2em] text-white/70">NETRA</span>
    </div>
  );
}

export function PostinganIG({
  klaim,
  verifikasi,
  kandidat,
  draf,
  simulasi = false,
}: {
  klaim: Klaim;
  verifikasi: HasilVerifikasi;
  kandidat: KandidatSumber[];
  draf: DrafKlarifikasi;
  /** true untuk kasus demo sintetis, supaya gambar tidak dikira klarifikasi resmi */
  simulasi?: boolean;
}) {
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const [mengunduh, setMengunduh] = useState(false);
  const [galat, setGalat] = useState<string | null>(null);
  const [gambarGagal, setGambarGagal] = useState(false);

  const isi = susunIsi(verifikasi, kandidat, draf.kartu);
  const disetujui = verifikasi.status_persetujuan === "disetujui";
  const vonis = VONIS[verifikasi.perubahan[0] ?? "lainnya"] ?? "KELIRU";
  const caption = `${draf.pendek}\n\nSumber: ${isi.sumber.map((s) => s.situs).join(", ") || "-"}\n\n#CekFakta #Klarifikasi #SaringSebelumSharing`;

  async function unduh() {
    setMengunduh(true);
    setGalat(null);
    try {
      const { toPng } = await import("html-to-image");
      for (const [i, el] of refs.current.entries()) {
        if (!el) continue;
        const dataUrl = await toPng(el, {
          width: LEBAR,
          height: TINGGI,
          pixelRatio: 1,
          cacheBust: true,
          imagePlaceholder:
            "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='9'%3E%3Crect width='16' height='9' fill='%23334155'/%3E%3C/svg%3E",
        });
        const a = document.createElement("a");
        a.href = dataUrl;
        a.download = `netra-${klaim.claim_id}-${i + 1}.png`;
        a.click();
        await new Promise((r) => setTimeout(r, 300));
      }
    } catch {
      setGalat("Gagal membuat gambar. Coba lagi, atau ambil tangkapan layar pratinjau.");
    } finally {
      setMengunduh(false);
    }
  }

  return (
    <div className="space-y-4 px-5 py-4">
      <div className="flex gap-3 overflow-x-auto pb-2">
        {/* Slide 1: sampul */}
        <Slide refEl={(el) => (refs.current[0] = el)}>
          <Kepala simulasi={simulasi} disetujui={disetujui} nomor={1} />
          <div className="flex flex-1 flex-col justify-center px-[80px]">
            <span className="w-fit rounded-xl bg-rose-500 px-8 py-4 text-[64px] font-black tracking-wide">
              {vonis}
            </span>
            <p className="mt-[56px] text-[30px] font-semibold uppercase tracking-[0.15em] text-white/50">
              Beredar di media sosial
            </p>
            <p className="mt-6 text-[60px] font-bold leading-[1.2]">“{klaim.teks_klaim}”</p>
          </div>
          <div className="px-[80px] pb-[64px] text-[30px] font-semibold text-sky-300">Geser untuk faktanya →</div>
        </Slide>

        {/* Slide 2: sebelum - sesudah */}
        <Slide refEl={(el) => (refs.current[1] = el)}>
          <Kepala simulasi={simulasi} disetujui={disetujui} nomor={2} />
          <div className="flex flex-1 flex-col justify-center gap-[40px] px-[80px]">
            <div className="rounded-3xl bg-rose-500/15 p-[48px] ring-2 ring-rose-400/40">
              <p className="text-[28px] font-bold tracking-[0.2em] text-rose-300">YANG BEREDAR</p>
              <p className="mt-5 text-[42px] font-semibold leading-snug">“{isi.viral || klaim.teks_klaim}”</p>
            </div>
            <div className="rounded-3xl bg-emerald-500/15 p-[48px] ring-2 ring-emerald-400/40">
              <p className="text-[28px] font-bold tracking-[0.2em] text-emerald-300">FAKTANYA</p>
              {isi.gambar && !gambarGagal && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={isi.gambar}
                  alt=""
                  crossOrigin="anonymous"
                  onError={() => setGambarGagal(true)}
                  className="mt-6 aspect-video w-full rounded-2xl object-cover"
                />
              )}
              <p className="mt-6 text-[40px] font-semibold leading-snug">{isi.fakta}</p>
              {isi.penjelasan && (
                <p className="mt-5 text-[32px] leading-snug text-white/80">{isi.penjelasan}</p>
              )}
              <p className="mt-5 text-[28px] text-white/60">
                {[isi.penerbit, isi.tanggal ? formatTanggal(isi.tanggal) : null].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>
          <div className="h-[60px]" />
        </Slide>

        {/* Slide 3: apa yang diubah + sumber */}
        <Slide refEl={(el) => (refs.current[2] = el)}>
          <Kepala simulasi={simulasi} disetujui={disetujui} nomor={3} />
          <div className="flex flex-1 flex-col px-[80px] pt-[80px]">
            <p className="text-[30px] font-bold tracking-[0.2em] text-white/50">YANG DIUBAH</p>
            <div className="mt-8 flex flex-wrap gap-5">
              {verifikasi.perubahan.map((p) => (
                <span key={p} className="rounded-2xl bg-white/10 px-7 py-4 text-[38px] font-semibold">
                  {LABEL_PERUBAHAN[p] ?? p}
                </span>
              ))}
            </div>
            <p className="mt-[80px] text-[30px] font-bold tracking-[0.2em] text-white/50">SUMBER</p>
            <ul className="mt-8 space-y-6">
              {isi.sumber.map((s) => (
                <li key={s.situs} className="text-[40px] leading-snug">
                  <span className="font-semibold">{s.situs}</span>
                  {s.tanggal && <span className="text-white/60"> · {s.tanggal}</span>}
                </li>
              ))}
            </ul>
            <p className="mt-auto pb-[48px] text-[34px] leading-snug text-white/80">
              Temukan konten mencurigakan? Laporkan, jangan disebarkan.
            </p>
          </div>
          <Kaki />
        </Slide>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">
          3 slide 1080×1350 (feed Instagram 4:5). Label DRAF hilang setelah disetujui petugas.
        </p>
        <button
          type="button"
          onClick={() => void unduh()}
          disabled={mengunduh}
          className="rounded-md bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-60"
        >
          {mengunduh ? "Menyiapkan…" : "Unduh 3 slide (PNG)"}
        </button>
      </div>
      {galat && <p className="text-xs text-rose-600">{galat}</p>}

      <div>
        <div className="mb-1 flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Caption</p>
          <CopyButton teks={caption} label="Salin caption" />
        </div>
        <p className="whitespace-pre-wrap rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-800 ring-1 ring-inset ring-slate-200">
          {caption}
        </p>
      </div>
    </div>
  );
}
