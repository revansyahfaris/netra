/** Klien API Netra. Semua tipe mengikuti backend/schemas.py (kontrak v2). */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/+$/, "") || "/api";

export type LevelPrioritas = "tinggi" | "sedang" | "rendah";
export type JenisMedia = "video" | "gambar" | "teks";
export type StatusPipeline =
  | "baru"
  | "dicari"
  | "diverifikasi"
  | "menunggu_persetujuan"
  | "disetujui"
  | "ditolak"
  | "dipublikasi";
export type StatusVerifikasi = "terbukti_diubah" | "tidak_ditemukan" | "belum_bisa_diverifikasi";
export type StatusPersetujuan = "menunggu" | "disetujui" | "ditolak";

export interface Klaim {
  claim_id: string;
  teks_klaim: string;
  media_url: string | null;
  jenis_media: JenisMedia;
  tanggal_ditemukan: string;
  jumlah_share: number;
  jumlah_view: number;
  laju_sebar: number;
  pengikut_pengunggah: number;
  skor_prioritas: number | null;
  level: LevelPrioritas | null;
  label_topik: string | null;
  alasan: string | null;
  status_pipeline: StatusPipeline;
  sumber_masuk: "deteksi" | "manual";
}

export interface KlaimMasuk {
  claim_id: string;
  teks_klaim: string;
  media_url?: string | null;
  jenis_media: JenisMedia;
  tanggal_ditemukan: string;
  jumlah_share?: number;
  jumlah_view?: number;
  laju_sebar?: number;
  pengikut_pengunggah?: number;
  sumber_masuk?: "deteksi" | "manual";
}

export interface StatusPekerjaanPipeline {
  claim_id: string;
  status_kerja: "belum_dijalankan" | "antre" | "berjalan" | "selesai" | "gagal";
  tahap_saat_ini: string;
  dimulai_pada: string | null;
  selesai_pada: string | null;
  error: string | null;
  mode_ai: boolean;
}

export interface KandidatSumber {
  url: string;
  tanggal_unggah: string | null;
  jenis_sumber: "resmi" | "media" | "pribadi";
  metode: "keyword" | "kutipan" | "frame_match";
  kemiripan: number;
  cuplikan: string | null;
  resolusi: number | null;
  ada_watermark: boolean | null;
  kecocokan_audio: number | null;
  skor: number | null;
  judul: string | null;
  uploader: string | null;
  thumbnail_url: string | null;
  rincian_skor: Record<string, number>;
}

export interface HasilPencarian {
  claim_id: string;
  kandidat: KandidatSumber[];
  mode: "live" | "demo" | "manual";
  diperbarui: string | null;
}

export interface Bukti {
  jenis: "kutipan" | "frame" | "transkrip" | "metadata";
  url: string;
  cuplikan: string | null;
  teks_viral: string | null;
  teks_sumber: string | null;
  catatan: string | null;
}

export interface DrafKlarifikasi {
  kartu: string;
  pendek: string;
  whatsapp: string;
}

export interface HasilVerifikasi {
  claim_id: string;
  status: StatusVerifikasi;
  sumber_utama: string | null;
  perubahan: string[];
  draf_klarifikasi: DrafKlarifikasi | null;
  perlu_eskalasi: boolean;
  ringkasan: string | null;
  bukti: Bukti[];
  keyakinan: number | null;
  metode: string[];
  waktu_proses_detik: number | null;
  waktu_verifikasi: string | null;
  status_persetujuan: StatusPersetujuan;
  catatan_petugas: string | null;
  disetujui_oleh: string | null;
  waktu_persetujuan: string | null;
}

export interface RiwayatAksi {
  aksi: string;
  aktor: string | null;
  waktu: string;
  detail: Record<string, unknown>;
}

export interface KlaimLengkap {
  klaim: Klaim;
  pencarian: HasilPencarian | null;
  proses_pencarian: Record<string, unknown> | null;
  verifikasi: HasilVerifikasi | null;
  riwayat: RiwayatAksi[];
}

export interface BuktiPublik {
  claim_id: string;
  teks_klaim: string;
  jenis_media: JenisMedia;
  media_url: string | null;
  tanggal_ditemukan: string;
  status: StatusVerifikasi | null;
  ringkasan: string | null;
  perubahan: string[];
  keyakinan: number | null;
  metode: string[];
  sumber_utama: string | null;
  bukti: Bukti[];
  klarifikasi: DrafKlarifikasi | null;
  disetujui: boolean;
  waktu_verifikasi: string | null;
  waktu_persetujuan: string | null;
  simulasi: boolean;
}

export interface Statistik {
  total_klaim: number;
  per_status_pipeline: Record<string, number>;
  per_status_verifikasi: Record<string, number>;
  perlu_eskalasi: number;
  menunggu_persetujuan: number;
  jumlah_bukti: number;
  rata_rata_waktu_proses_detik: number | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function minta<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, `Tidak bisa menghubungi API di ${API_BASE}. Pastikan backend jalan.`);
  }
  if (!res.ok) {
    let pesan = `Permintaan gagal (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") {
        pesan = body.detail;
      } else if (Array.isArray(body.detail) && body.detail.length > 0) {
        pesan = body.detail
          .map((d: { msg?: string }) => d.msg ?? "Input tidak valid")
          .join("; ");
      }
    } catch {
      /* biarkan pesan default */
    }
    throw new ApiError(res.status, pesan);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => minta<Record<string, unknown>>("/health"),
  statistik: () => minta<Statistik>("/statistik"),
  antrean: (params?: { status?: string; level?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.level) q.set("level", params.level);
    const s = q.toString();
    return minta<KlaimLengkap[]>(`/antrean${s ? `?${s}` : ""}`);
  },
  klaim: (id: string) => minta<KlaimLengkap>(`/klaim/${id}`),
  tambahKlaim: (body: KlaimMasuk) =>
    minta<Klaim>("/prioritas", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  pipeline: (id: string) => minta<unknown>(`/pipeline/${id}`, { method: "POST" }),
  antrePipeline: (id: string, urlManual: string[] = []) =>
    minta<StatusPekerjaanPipeline>(`/pipeline/${id}/antre`, {
      method: "POST",
      body: JSON.stringify({ url_manual: urlManual }),
    }),
  statusPipeline: (id: string) => minta<StatusPekerjaanPipeline>(`/pipeline/${id}/status`),
  cari: (id: string, urlManual: string[] = []) =>
    minta<HasilPencarian>(`/cari/${id}`, {
      method: "POST",
      body: JSON.stringify({ url_manual: urlManual }),
    }),
  verifikasi: (id: string) => minta<HasilVerifikasi>(`/verifikasi/${id}`, { method: "POST" }),
  putuskan: (id: string, body: { keputusan: "disetujui" | "ditolak"; petugas: string; catatan?: string }) =>
    minta<HasilVerifikasi>(`/verifikasi/${id}/persetujuan`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  buktiPublik: (id: string) => minta<BuktiPublik>(`/bukti/${id}`),
  seed: () => minta<unknown>("/seed", { method: "POST" }),
};