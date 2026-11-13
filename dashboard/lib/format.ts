import type { LevelPrioritas, StatusPipeline, StatusVerifikasi } from "./api";

export function cn(...kelas: Array<string | false | null | undefined>): string {
  return kelas.filter(Boolean).join(" ");
}

export const LABEL_PIPELINE: Record<StatusPipeline, string> = {
  baru: "Baru",
  dicari: "Sudah dicari",
  diverifikasi: "Diverifikasi",
  menunggu_persetujuan: "Menunggu persetujuan",
  disetujui: "Disetujui",
  ditolak: "Ditolak",
  dipublikasi: "Dipublikasi",
};

export const WARNA_PIPELINE: Record<StatusPipeline, string> = {
  baru: "bg-slate-100 text-slate-700 ring-slate-200",
  dicari: "bg-sky-50 text-sky-700 ring-sky-200",
  diverifikasi: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  menunggu_persetujuan: "bg-amber-50 text-amber-800 ring-amber-200",
  disetujui: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  ditolak: "bg-rose-50 text-rose-700 ring-rose-200",
  dipublikasi: "bg-brand-50 text-brand-700 ring-brand-100",
};

export const LABEL_VERIFIKASI: Record<StatusVerifikasi, string> = {
  terbukti_diubah: "Terbukti diubah",
  tidak_ditemukan: "Tidak ditemukan sumber",
  belum_bisa_diverifikasi: "Belum bisa diverifikasi",
};

export const WARNA_VERIFIKASI: Record<StatusVerifikasi, string> = {
  terbukti_diubah: "bg-rose-50 text-rose-700 ring-rose-200",
  tidak_ditemukan: "bg-slate-100 text-slate-600 ring-slate-200",
  belum_bisa_diverifikasi: "bg-amber-50 text-amber-800 ring-amber-200",
};

export const LABEL_LEVEL: Record<LevelPrioritas, string> = {
  tinggi: "Tinggi",
  sedang: "Sedang",
  rendah: "Rendah",
};

export const WARNA_LEVEL: Record<LevelPrioritas, string> = {
  tinggi: "bg-rose-600 text-white",
  sedang: "bg-amber-500 text-white",
  rendah: "bg-slate-400 text-white",
};

export const LABEL_PERUBAHAN: Record<string, string> = {
  dipotong: "Video dipotong",
  tanggal_berbeda: "Tanggal digeser",
  kutipan_tidak_ada: "Kutipan tidak ada di sumber",
  konteks_berbeda: "Konteks berbeda",
  lainnya: "Perubahan lain",
};

export const LABEL_METODE: Record<string, string> = {
  rag: "RAG korpus resmi",
  frame_match: "Pencocokan frame",
  ocr: "OCR",
  asr: "Transkrip audio",
  manual: "Pemeriksaan manual",
};

export const LABEL_SUMBER: Record<string, string> = {
  resmi: "Resmi",
  media: "Media",
  pribadi: "Akun pribadi",
};

export const LABEL_JENIS_BUKTI: Record<string, string> = {
  kutipan: "Kutipan",
  frame: "Frame",
  transkrip: "Transkrip",
  metadata: "Metadata",
};

export function formatTanggal(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", year: "numeric" }).format(d);
}

export function formatTanggalWaktu(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

export function formatAngka(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("id-ID", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function persen(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Math.round(n * 100)}%`;
}

export function slugJudul(kandidat: { judul: string | null; url: string }): string {
  if (kandidat.judul) return kandidat.judul;
  try {
    return new URL(kandidat.url).hostname.replace("www.", "");
  } catch {
    return kandidat.url;
  }
}