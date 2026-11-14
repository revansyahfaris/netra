"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import type {
  DrafKlarifikasi,
  HasilVerifikasi,
  KandidatSumber,
  Klaim,
} from "@/lib/api";
import { formatTanggal, LABEL_PERUBAHAN } from "@/lib/format";
import { CopyButton } from "./ui";

/** Ukuran feed Instagram 4:5 */
const LEBAR = 1080;
const TINGGI = 1350;
const SKALA_PRATINJAU = 0.28;
const KUNCI_LOGO = "netra:logo-instansi";

function keDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

const VONIS: Record<string, string> = {
  tanggal_berbeda: "VIDEO LAMA",
  konteks_berbeda: "KONTEKS KELIRU",
  kutipan_tidak_ada: "KUTIPAN PALSU",
  dipotong: "DIPOTONG",
  lainnya: "KELIRU",
};

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

function susunIsi(
  verifikasi: HasilVerifikasi,
  kandidat: KandidatSumber[],
  kartu: string,
) {
  const bukti =
    verifikasi.bukti.find((b) => b.teks_sumber) ?? verifikasi.bukti[0] ?? null;
  const urlSumber =
    bukti?.url ?? verifikasi.sumber_utama ?? kandidat[0]?.url ?? null;
  const k = kandidat.find((x) => x.url === urlSumber) ?? kandidat[0] ?? null;
  const ytId = (urlSumber && idYoutube(urlSumber)) || (k && idYoutube(k.url));
  const sumber = verifikasi.bukti
    .filter(
      (b, i, arr) =>
        arr.findIndex((x) => namaSitus(x.url) === namaSitus(b.url)) === i,
    )
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
    gambar:
      k?.thumbnail_url ||
      (ytId ? `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg` : null),
    sumber,
  };
}

function Slide({
  children,
  refEl,
  latar,
}: {
  children: ReactNode;
  refEl: (el: HTMLDivElement | null) => void;
  latar?: string | null;
}) {
  return (
    <div
      className="shrink-0 overflow-hidden rounded-lg ring-1 ring-slate-200"
      style={{
        width: LEBAR * SKALA_PRATINJAU,
        height: TINGGI * SKALA_PRATINJAU,
      }}
    >
      <div
        style={{
          transform: `scale(${SKALA_PRATINJAU})`,
          transformOrigin: "top left",
        }}
      >
        <div
          ref={refEl}
          style={{
            width: LEBAR,
            height: TINGGI,
            fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          }}
          className="relative flex flex-col bg-[#0b1530] text-white"
        >
          {latar && (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={latar}
                alt=""
                className="absolute inset-0 h-full w-full object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-b from-[#0b1530]/80 via-[#0b1530]/70 to-[#0b1530]/95" />
            </>
          )}
          <div className="relative flex flex-1 flex-col">{children}</div>
        </div>
      </div>
    </div>
  );
}

function Kepala({
  simulasi,
  disetujui,
  nomor,
  logo,
}: {
  simulasi: boolean;
  disetujui: boolean;
  nomor: number;
  logo: string[];
}) {
  return (
    <div className="flex items-center justify-between px-[80px] pt-[72px]">
      <span className="flex items-center text-[30px] font-bold tracking-[0.3em] text-white/90">
        {logo.map((src, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={i}
            src={src}
            alt=""
            className="mr-5 h-[84px] w-auto object-contain"
          />
        ))}
        KLARIFIKASI
        {simulasi && (
          <span className="ml-4 rounded-md bg-white/15 px-3 py-1 text-[22px] tracking-normal">
            SIMULASI
          </span>
        )}
      </span>
      <span className="text-[26px] font-semibold text-white/50">
        {!disetujui && (
          <span className="mr-5 rounded-md bg-amber-400 px-3 py-1 text-[#0b1530]">
            DRAF
          </span>
        )}
        {nomor}/3
      </span>
    </div>
  );
}

function Kaki() {
  return (
    <div className="mt-auto flex items-center justify-between border-t border-white/10 px-[80px] py-[44px] text-[24px] text-white/50">
      <span>Cek dulu sebelum menyebarkan.</span>
      <span className="font-semibold tracking-[0.2em] text-white/70">
        NETRA
      </span>
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
  const [latar, setLatar] = useState<string | null>(null);
  const [latarSemua, setLatarSemua] = useState(false);
  const [video, setVideo] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [logo, setLogo] = useState<string[]>([]);

  // Logo instansi disimpan di browser ini saja, supaya tidak perlu diunggah ulang tiap postingan
  useEffect(() => {
    try {
      const tersimpan = window.localStorage.getItem(KUNCI_LOGO);
      if (tersimpan) setLogo(JSON.parse(tersimpan));
    } catch {
      /* penyimpanan browser tidak tersedia */
    }
  }, []);

  function simpanLogo(baru: string[]) {
    setLogo(baru);
    try {
      window.localStorage.setItem(KUNCI_LOGO, JSON.stringify(baru));
    } catch {
      /* logo terlalu besar untuk disimpan; tetap dipakai selama halaman terbuka */
    }
  }

  async function pilihLatar(file: File | undefined) {
    if (!file) return;
    if (file.type.startsWith("video/")) {
      setVideo(URL.createObjectURL(file));
      return;
    }
    setVideo(null);
    setLatar(await keDataUrl(file));
  }

  function ambilFrame() {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d")?.drawImage(v, 0, 0);
    setLatar(c.toDataURL("image/jpeg", 0.9));
  }

  async function tambahLogo(files: FileList | null) {
    if (!files) return;
    const baru = await Promise.all(
      Array.from(files).slice(0, 3).map(keDataUrl),
    );
    simpanLogo([...logo, ...baru].slice(0, 3));
  }

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
      setGalat(
        "Gagal membuat gambar. Coba lagi, atau ambil tangkapan layar pratinjau.",
      );
    } finally {
      setMengunduh(false);
    }
  }

  return (
    <div className="space-y-4 px-5 py-4">
      <div className="grid gap-3 rounded-lg bg-slate-50 p-3 text-xs ring-1 ring-inset ring-slate-200 sm:grid-cols-2">
        <div>
          <p className="font-semibold text-slate-700">Latar belakang</p>
          <p className="mt-0.5 text-slate-500">
            Gambar, atau video lalu pilih satu frame.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <label className="cursor-pointer rounded-md border border-slate-300 bg-white px-2.5 py-1 font-medium text-slate-700 hover:bg-slate-100">
              Pilih file
              <input
                type="file"
                accept="image/*,video/*"
                className="hidden"
                onChange={(e) => void pilihLatar(e.target.files?.[0])}
              />
            </label>
            {latar && (
              <>
                <label className="flex items-center gap-1 text-slate-600">
                  <input
                    type="checkbox"
                    checked={latarSemua}
                    onChange={(e) => setLatarSemua(e.target.checked)}
                  />
                  semua slide
                </label>
                <button
                  type="button"
                  onClick={() => setLatar(null)}
                  className="text-rose-600 hover:underline"
                >
                  hapus
                </button>
              </>
            )}
          </div>
          {video && (
            <div className="mt-2 space-y-1.5">
              <video
                ref={videoRef}
                src={video}
                controls
                muted
                className="max-h-40 w-full rounded-md bg-black"
              />
              <button
                type="button"
                onClick={ambilFrame}
                className="rounded-md bg-slate-900 px-2.5 py-1 font-medium text-white hover:bg-slate-700"
              >
                Pakai frame ini
              </button>
            </div>
          )}
        </div>
        <div>
          <p className="font-semibold text-slate-700">Logo instansi</p>
          <p className="mt-0.5 text-slate-500">
            Maksimal 3, disimpan di browser ini saja.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <label className="cursor-pointer rounded-md border border-slate-300 bg-white px-2.5 py-1 font-medium text-slate-700 hover:bg-slate-100">
              Tambah logo
              <input
                type="file"
                accept="image/png,image/svg+xml,image/jpeg,image/webp"
                multiple
                className="hidden"
                onChange={(e) => void tambahLogo(e.target.files)}
              />
            </label>
            {logo.map((src, i) => (
              <span
                key={i}
                className="flex items-center gap-1 rounded bg-slate-800 p-1"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={src} alt="" className="h-6 w-auto" />
                <button
                  type="button"
                  onClick={() => simpanLogo(logo.filter((_, j) => j !== i))}
                  className="px-1 text-white/70 hover:text-white"
                  aria-label="Hapus logo"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-2">
        {/* Slide 1: sampul */}
        <Slide refEl={(el) => (refs.current[0] = el)} latar={latar}>
          <Kepala
            simulasi={simulasi}
            disetujui={disetujui}
            nomor={1}
            logo={logo}
          />
          <div className="flex flex-1 flex-col justify-center px-[80px]">
            <span className="w-fit rounded-xl bg-rose-500 px-8 py-4 text-[64px] font-black tracking-wide">
              {vonis}
            </span>
            <p className="mt-[56px] text-[30px] font-semibold uppercase tracking-[0.15em] text-white/50">
              Beredar di media sosial
            </p>
            <p className="mt-6 text-[60px] font-bold leading-[1.2]">
              “{klaim.teks_klaim}”
            </p>
          </div>
          <div className="px-[80px] pb-[64px] text-[30px] font-semibold text-sky-300">
            Geser untuk faktanya →
          </div>
        </Slide>

        {/* Slide 2: sebelum - sesudah */}
        <Slide
          refEl={(el) => (refs.current[1] = el)}
          latar={latarSemua ? latar : null}
        >
          <Kepala
            simulasi={simulasi}
            disetujui={disetujui}
            nomor={2}
            logo={logo}
          />
          <div className="flex flex-1 flex-col justify-center gap-[40px] px-[80px]">
            <div className="rounded-3xl bg-rose-500/15 p-[48px] ring-2 ring-rose-400/40">
              <p className="text-[28px] font-bold tracking-[0.2em] text-rose-300">
                YANG BEREDAR
              </p>
              <p className="mt-5 text-[42px] font-semibold leading-snug">
                “{isi.viral || klaim.teks_klaim}”
              </p>
            </div>
            <div className="rounded-3xl bg-emerald-500/15 p-[48px] ring-2 ring-emerald-400/40">
              <p className="text-[28px] font-bold tracking-[0.2em] text-emerald-300">
                FAKTANYA
              </p>
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
              <p className="mt-6 text-[40px] font-semibold leading-snug">
                {isi.fakta}
              </p>
              {isi.penjelasan && (
                <p className="mt-5 text-[32px] leading-snug text-white/80">
                  {isi.penjelasan}
                </p>
              )}
              <p className="mt-5 text-[28px] text-white/60">
                {[isi.penerbit, isi.tanggal ? formatTanggal(isi.tanggal) : null]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
          </div>
          <div className="h-[60px]" />
        </Slide>

        {/* Slide 3: apa yang diubah + sumber */}
        <Slide
          refEl={(el) => (refs.current[2] = el)}
          latar={latarSemua ? latar : null}
        >
          <Kepala
            simulasi={simulasi}
            disetujui={disetujui}
            nomor={3}
            logo={logo}
          />
          <div className="flex flex-1 flex-col px-[80px] pt-[80px]">
            <p className="text-[30px] font-bold tracking-[0.2em] text-white/50">
              YANG DIUBAH
            </p>
            <div className="mt-8 flex flex-wrap gap-5">
              {verifikasi.perubahan.map((p) => (
                <span
                  key={p}
                  className="rounded-2xl bg-white/10 px-7 py-4 text-[38px] font-semibold"
                >
                  {LABEL_PERUBAHAN[p] ?? p}
                </span>
              ))}
            </div>
            <p className="mt-[80px] text-[30px] font-bold tracking-[0.2em] text-white/50">
              SUMBER
            </p>
            <ul className="mt-8 space-y-6">
              {isi.sumber.map((s) => (
                <li key={s.situs} className="text-[40px] leading-snug">
                  <span className="font-semibold">{s.situs}</span>
                  {s.tanggal && (
                    <span className="text-white/60"> · {s.tanggal}</span>
                  )}
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
          3 slide 1080×1350 (feed Instagram 4:5). Label DRAF hilang setelah
          disetujui petugas.
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
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Caption
          </p>
          <CopyButton teks={caption} label="Salin caption" />
        </div>
        <p className="whitespace-pre-wrap rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-800 ring-1 ring-inset ring-slate-200">
          {caption}
        </p>
      </div>
    </div>
  );
}
