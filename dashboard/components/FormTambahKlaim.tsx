"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type JenisMedia, type Klaim } from "@/lib/api";
import { cn } from "@/lib/format";

const PILIHAN_MEDIA: Array<{ nilai: JenisMedia; label: string }> = [
  { nilai: "video", label: "Video" },
  { nilai: "gambar", label: "Gambar" },
  { nilai: "teks", label: "Teks" },
];

function buatClaimId(): string {
  const d = new Date();
  const ymd = `${String(d.getFullYear()).slice(-2)}${String(d.getMonth() + 1).padStart(2, "0")}${String(
    d.getDate(),
  ).padStart(2, "0")}`;
  const acak = Math.random().toString(36).slice(2, 6);
  return `m-${ymd}-${acak}`;
}

function sekarangDatetimeLocal(): string {
  const d = new Date();
  const offsetMs = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - offsetMs).toISOString().slice(0, 16);
}

function parseNonNegatif(nilai: string): number {
  const angka = Number(nilai);
  if (!Number.isFinite(angka) || angka < 0) return 0;
  return Math.floor(angka);
}

export function FormTambahKlaim({
  terbuka,
  onTutup,
  onTersimpan,
}: {
  terbuka: boolean;
  onTutup: () => void;
  onTersimpan: (klaim: Klaim, bukaDetail: boolean) => void;
}) {
  const [claimId, setClaimId] = useState("");
  const [teksKlaim, setTeksKlaim] = useState("");
  const [jenisMedia, setJenisMedia] = useState<JenisMedia>("video");
  const [mediaUrl, setMediaUrl] = useState("");
  const [tanggalDitemukan, setTanggalDitemukan] = useState("");
  const [jumlahShare, setJumlahShare] = useState("0");
  const [jumlahView, setJumlahView] = useState("0");
  const [lajuSebar, setLajuSebar] = useState("0");
  const [pengikut, setPengikut] = useState("0");
  const [proses, setProses] = useState(false);
  const [galat, setGalat] = useState<string | null>(null);

  useEffect(() => {
    if (!terbuka) return;
    setClaimId(buatClaimId());
    setTeksKlaim("");
    setJenisMedia("video");
    setMediaUrl("");
    setTanggalDitemukan(sekarangDatetimeLocal());
    setJumlahShare("0");
    setJumlahView("0");
    setLajuSebar("0");
    setPengikut("0");
    setGalat(null);
  }, [terbuka]);

  useEffect(() => {
    if (!terbuka) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && !proses) onTutup();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [terbuka, proses, onTutup]);

  if (!terbuka) return null;

  async function kirim(bukaDetail: boolean) {
    setGalat(null);
    const teks = teksKlaim.trim();
    if (teks.length < 5) {
      setGalat("Isi teks klaim minimal 5 karakter.");
      return;
    }

    const id = claimId.trim();
    if (!id) {
      setGalat("ID klaim tidak boleh kosong.");
      return;
    }

    const urlBersih = mediaUrl.trim();
    if (urlBersih) {
      try {
        const parsed = new URL(urlBersih);
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
          setGalat("URL media harus diawali http:// atau https://.");
          return;
        }
      } catch {
        setGalat("Format URL media tidak valid.");
        return;
      }
    }

    const tanggalIso = tanggalDitemukan
      ? new Date(tanggalDitemukan).toISOString()
      : new Date().toISOString();

    setProses(true);
    try {
      const hasil = await api.tambahKlaim({
        claim_id: id,
        teks_klaim: teks,
        jenis_media: jenisMedia,
        media_url: urlBersih || null,
        tanggal_ditemukan: tanggalIso,
        jumlah_share: parseNonNegatif(jumlahShare),
        jumlah_view: parseNonNegatif(jumlahView),
        laju_sebar: parseNonNegatif(lajuSebar),
        pengikut_pengunggah: parseNonNegatif(pengikut),
        sumber_masuk: "manual",
      });
      onTersimpan(hasil, bukaDetail);
    } catch (e) {
      setGalat(e instanceof ApiError ? e.message : "Gagal menyimpan klaim.");
    } finally {
      setProses(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={() => {
        if (!proses) onTutup();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="judul-tambah-klaim"
    >
      <div
        className="w-full max-w-xl rounded-xl border border-slate-200 bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div>
            <h2 id="judul-tambah-klaim" className="text-base font-semibold text-slate-900">
              Tambah klaim manual
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Klaim akan dinilai prioritasnya lalu masuk antrean untuk diverifikasi.
            </p>
          </div>
          <button
            type="button"
            onClick={onTutup}
            disabled={proses}
            className="rounded-md px-2 py-1 text-sm text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label="Tutup dialog"
          >
            ✕
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void kirim(true);
          }}
          className="space-y-4 px-5 py-4"
        >
          <div>
            <span className="mb-1.5 block text-xs font-medium text-slate-700">Jenis media</span>
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
              {PILIHAN_MEDIA.map((m) => (
                <button
                  key={m.nilai}
                  type="button"
                  aria-pressed={jenisMedia === m.nilai}
                  onClick={() => setJenisMedia(m.nilai)}
                  className={cn(
                    "rounded-md px-3.5 py-1.5 text-xs font-medium transition",
                    jenisMedia === m.nilai
                      ? "bg-slate-900 text-white shadow-sm"
                      : "text-slate-600 hover:text-slate-900",
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label htmlFor="teks-klaim" className="mb-1 block text-xs font-medium text-slate-700">
              Teks / narasi klaim <span className="text-rose-500">*</span>
            </label>
            <textarea
              id="teks-klaim"
              rows={3}
              value={teksKlaim}
              onChange={(e) => setTeksKlaim(e.target.value)}
              placeholder="Contoh: Video prajurit TNI ... disebut terjadi minggu ini di ..."
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-500"
              required
            />
          </div>

          <div>
            <label htmlFor="media-url" className="mb-1 block text-xs font-medium text-slate-700">
              URL media viral {jenisMedia === "teks" ? "(opsional)" : "(disarankan untuk Lens/STT/OCR)"}
            </label>
            <input
              id="media-url"
              type="url"
              value={mediaUrl}
              onChange={(e) => setMediaUrl(e.target.value)}
              placeholder="https://..."
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-500"
            />
            <p className="mt-1 text-[11px] text-slate-400">
              Kosongkan jika hanya ingin mencari berdasarkan teks klaim.
            </p>
          </div>

          <details className="rounded-lg border border-slate-200 bg-slate-50/70 px-3.5 py-2.5">
            <summary className="cursor-pointer select-none text-xs font-medium text-slate-700">
              ID klaim, waktu &amp; sinyal penyebaran (opsional — otomatis diisi)
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="claim-id" className="mb-1 block text-[11px] font-medium text-slate-600">
                  ID klaim
                </label>
                <input
                  id="claim-id"
                  type="text"
                  value={claimId}
                  onChange={(e) => setClaimId(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs text-slate-800 outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label
                  htmlFor="tanggal-ditemukan"
                  className="mb-1 block text-[11px] font-medium text-slate-600"
                >
                  Tanggal ditemukan
                </label>
                <input
                  id="tanggal-ditemukan"
                  type="datetime-local"
                  value={tanggalDitemukan}
                  onChange={(e) => setTanggalDitemukan(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-brand-500"
                />
              </div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <div>
                <label htmlFor="jumlah-share" className="mb-1 block text-[11px] font-medium text-slate-600">
                  Share
                </label>
                <input
                  id="jumlah-share"
                  type="number"
                  min={0}
                  value={jumlahShare}
                  onChange={(e) => setJumlahShare(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label htmlFor="jumlah-view" className="mb-1 block text-[11px] font-medium text-slate-600">
                  View
                </label>
                <input
                  id="jumlah-view"
                  type="number"
                  min={0}
                  value={jumlahView}
                  onChange={(e) => setJumlahView(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label htmlFor="laju-sebar" className="mb-1 block text-[11px] font-medium text-slate-600">
                  Laju / jam
                </label>
                <input
                  id="laju-sebar"
                  type="number"
                  min={0}
                  value={lajuSebar}
                  onChange={(e) => setLajuSebar(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <label htmlFor="pengikut" className="mb-1 block text-[11px] font-medium text-slate-600">
                  Pengikut akun
                </label>
                <input
                  id="pengikut"
                  type="number"
                  min={0}
                  value={pengikut}
                  onChange={(e) => setPengikut(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none focus:border-brand-500"
                />
              </div>
            </div>
          </details>

          {galat && (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {galat}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-3">
            <button
              type="button"
              onClick={onTutup}
              disabled={proses}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              Batal
            </button>
            <button
              type="button"
              onClick={() => void kirim(false)}
              disabled={proses}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Simpan ke antrean
            </button>
            <button
              type="submit"
              disabled={proses}
              className="rounded-lg bg-brand-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {proses ? "Menyimpan…" : "Simpan & buka klaim"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
