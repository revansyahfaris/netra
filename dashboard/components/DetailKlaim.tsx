"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Card,
  CardHeader,
  Empty,
  ErrorBox,
  SkorBar,
  Skeleton,
} from "@/components/ui";
import { DrafKlarifikasi } from "@/components/DrafKlarifikasi";
import { PanelPersetujuan } from "@/components/PanelPersetujuan";
import { api, ApiError, type KlaimLengkap } from "@/lib/api";
import {
  cn,
  formatAngka,
  formatTanggal,
  formatTanggalWaktu,
  LABEL_JENIS_BUKTI,
  LABEL_LEVEL,
  LABEL_METODE,
  LABEL_PERUBAHAN,
  LABEL_PIPELINE,
  LABEL_SUMBER,
  LABEL_VERIFIKASI,
  persen,
  slugJudul,
  WARNA_LEVEL,
  WARNA_PIPELINE,
  WARNA_VERIFIKASI,
} from "@/lib/format";

const LABEL_AKSI: Record<string, string> = {
  klaim_dibuat: "Klaim masuk antrean",
  klaim_diperbarui: "Klaim diperbarui",
  pencarian: "Pencarian sumber dijalankan",
  verifikasi: "Verifikasi dijalankan",
  persetujuan_disetujui: "Klarifikasi disetujui",
  persetujuan_ditolak: "Klarifikasi ditolak",
  seed: "Data demo dimuat",
  api: "Diproses API",
};

const URUTAN_RINCIAN: Record<string, string> = {
  kemiripan: "Kemiripan",
  tanggal: "Tanggal",
  jenis_sumber: "Jenis sumber",
  resolusi: "Resolusi",
  bersih: "Bebas watermark",
  audio: "Audio",
};

export function DetailKlaim({ id }: { id: string }) {
  const [data, setData] = useState<KlaimLengkap | null>(null);
  const [galat, setGalat] = useState<string | null>(null);
  const [proses, setProses] = useState(false);

  const muat = useCallback(async () => {
    try {
      setData(await api.klaim(id));
      setGalat(null);
    } catch (e) {
      setGalat(e instanceof ApiError ? e.message : "Gagal memuat klaim.");
    }
  }, [id]);

  useEffect(() => {
    void muat();
  }, [muat]);

  async function jalankan() {
    setProses(true);
    setGalat(null);
    try {
      await api.pipeline(id);
      await muat();
    } catch (e) {
      setGalat(e instanceof ApiError ? e.message : "Gagal menjalankan pipeline.");
    } finally {
      setProses(false);
    }
  }

  if (galat && !data) {
    return <ErrorBox pesan={galat} onRetry={() => void muat()} />;
  }

  if (!data) {
    return (
      <Card>
        <Skeleton baris={8} />
      </Card>
    );
  }

  const { klaim, pencarian, verifikasi, riwayat } = data;
  const kandidat = pencarian?.kandidat ?? [];
  const draf = verifikasi?.draf_klarifikasi ?? null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <Link href="/antrean" className="text-slate-500 hover:text-slate-800">
          ← Antrean
        </Link>
        <div className="flex items-center gap-3">
          <Link
            href={`/bukti/${klaim.claim_id}`}
            className="text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            Lihat halaman bukti publik
          </Link>
          <button
            type="button"
            onClick={() => void jalankan()}
            disabled={proses}
            className="rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {proses ? "Memproses…" : verifikasi ? "Cari & verifikasi ulang" : "Jalankan pencarian & verifikasi"}
          </button>
        </div>
      </div>

      <Card className="overflow-hidden">
        <div className="border-b border-slate-100 bg-slate-50 px-5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-slate-500">{klaim.claim_id}</span>
            {klaim.level && (
              <span className={cn("rounded px-2 py-0.5 text-[11px] font-semibold", WARNA_LEVEL[klaim.level])}>
                Prioritas {LABEL_LEVEL[klaim.level]}
                {klaim.skor_prioritas != null ? ` · ${klaim.skor_prioritas.toFixed(2)}` : ""}
              </span>
            )}
            <Badge tone={WARNA_PIPELINE[klaim.status_pipeline]}>{LABEL_PIPELINE[klaim.status_pipeline]}</Badge>
            {verifikasi && (
              <Badge tone={WARNA_VERIFIKASI[verifikasi.status]}>{LABEL_VERIFIKASI[verifikasi.status]}</Badge>
            )}
            {verifikasi?.perlu_eskalasi && (
              <Badge tone="bg-amber-50 text-amber-800 ring-amber-200">Eskalasi petugas</Badge>
            )}
            <span className="ml-auto text-xs text-slate-400">
              {pencarian ? `mode ${pencarian.mode}` : "belum dicari"}
            </span>
          </div>
        </div>
        <div className="px-5 py-4">
          <h1 className="text-lg font-semibold leading-snug text-slate-900">{klaim.teks_klaim}</h1>
          <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Info label="Jenis media" nilai={klaim.jenis_media} />
            <Info label="Ditemukan" nilai={formatTanggal(klaim.tanggal_ditemukan)} />
            <Info label="Sebaran" nilai={`${formatAngka(klaim.jumlah_share)} share · ${formatAngka(klaim.jumlah_view)} view`} />
            <Info label="Laju sebar" nilai={`${formatAngka(klaim.laju_sebar)} / jam`} />
          </div>
          {klaim.alasan && (
            <p className="mt-3 rounded-lg bg-brand-50 px-3 py-2 text-xs text-brand-900 ring-1 ring-inset ring-brand-100">
              <span className="font-semibold">Alasan prioritas:</span> {klaim.alasan}
            </p>
          )}
          {klaim.media_url && (
            <p className="mt-3 break-all text-xs text-slate-500">
              Media viral:{" "}
              <a href={klaim.media_url} target="_blank" rel="noreferrer" className="text-brand-600 underline">
                {klaim.media_url}
              </a>
            </p>
          )}
        </div>
      </Card>

      {galat && <ErrorBox pesan={galat} onRetry={() => void muat()} />}

      <div className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader
            judul={`Kandidat sumber${kandidat.length ? ` (${kandidat.length})` : ""}`}
            keterangan="Diurutkan dari yang paling mungkin asli: tanggal paling awal, resolusi, kebersihan, kecocokan audio."
          />
          {kandidat.length === 0 ? (
            <Empty>
              Belum ada kandidat. Jalankan pencarian, atau kirim URL kandidat secara manual lewat API
              <span className="font-mono"> /cari/{klaim.claim_id}</span>.
            </Empty>
          ) : (
            <ol className="divide-y divide-slate-100">
              {kandidat.map((k, i) => (
                <li key={k.url} className="px-5 py-4">
                  <div className="flex gap-3">
                    <span
                      className={cn(
                        "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                        i === 0 ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600",
                      )}
                    >
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <a
                          href={k.url}
                          target="_blank"
                          rel="noreferrer"
                          className="truncate font-medium text-slate-900 hover:text-brand-700"
                        >
                          {slugJudul(k)}
                        </a>
                        <Badge tone="bg-slate-100 text-slate-600 ring-slate-200">
                          {LABEL_SUMBER[k.jenis_sumber]}
                        </Badge>
                        <Badge tone="bg-slate-50 text-slate-500 ring-slate-200">{k.metode}</Badge>
                        {k.ada_watermark && (
                          <Badge tone="bg-amber-50 text-amber-800 ring-amber-200">watermark</Badge>
                        )}
                      </div>
                      <p className="mt-0.5 break-all text-xs text-slate-400">{k.url}</p>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                        <span>unggah {formatTanggal(k.tanggal_unggah)}</span>
                        {k.uploader && <span>oleh {k.uploader}</span>}
                        {k.resolusi && <span>{k.resolusi}p</span>}
                        {k.cuplikan && (
                          <span className="font-mono text-slate-700">cuplikan {k.cuplikan}</span>
                        )}
                        {k.kecocokan_audio != null && <span>audio {persen(k.kecocokan_audio)}</span>}
                      </div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-[200px_1fr] sm:items-center">
                        <SkorBar nilai={k.skor} label="Skor sumber asli" compact />
                        <div className="flex flex-wrap gap-1.5">
                          {Object.entries(k.rincian_skor).map(([komponen, nilai]) => (
                            <span
                              key={komponen}
                              className="rounded bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-500 ring-1 ring-inset ring-slate-200"
                              title={URUTAN_RINCIAN[komponen] ?? komponen}
                            >
                              {URUTAN_RINCIAN[komponen] ?? komponen} {nilai.toFixed(2)}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader judul="Paket bukti" keterangan="Yang dilihat petugas sebelum memutuskan." />
          <div className="space-y-4 px-5 py-4">
            {verifikasi ? (
              <>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <Info label="Keyakinan" nilai={persen(verifikasi.keyakinan)} />
                  <Info
                    label="Waktu proses"
                    nilai={verifikasi.waktu_proses_detik != null ? `${verifikasi.waktu_proses_detik}s` : "—"}
                  />
                </div>
                {verifikasi.metode.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {verifikasi.metode.map((m) => (
                      <Badge key={m} tone="bg-indigo-50 text-indigo-700 ring-indigo-200">
                        {LABEL_METODE[m] ?? m}
                      </Badge>
                    ))}
                  </div>
                )}
                {verifikasi.ringkasan && (
                  <p className="text-sm leading-relaxed text-slate-700">{verifikasi.ringkasan}</p>
                )}
                {verifikasi.perubahan.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Apa yang diubah
                    </p>
                    <ul className="space-y-1 text-sm text-slate-700">
                      {verifikasi.perubahan.map((p) => (
                        <li key={p} className="flex gap-2">
                          <span className="text-rose-500">▸</span>
                          {LABEL_PERUBAHAN[p] ?? p}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Bukti
                  </p>
                  {verifikasi.bukti.length === 0 ? (
                    <p className="text-sm text-slate-500">Belum ada bukti terstruktur.</p>
                  ) : (
                    <ul className="space-y-2">
                      {verifikasi.bukti.map((b, i) => (
                        <li key={`${b.url}-${i}`} className="rounded-lg border border-slate-200 px-3 py-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone="bg-slate-100 text-slate-700 ring-slate-200">
                              {LABEL_JENIS_BUKTI[b.jenis] ?? b.jenis}
                            </Badge>
                            {b.cuplikan && <span className="font-mono text-xs text-slate-600">{b.cuplikan}</span>}
                            <a
                              href={b.url}
                              target="_blank"
                              rel="noreferrer"
                              className="ml-auto max-w-[45%] truncate text-xs text-brand-600 hover:underline"
                            >
                              {new URL(b.url).hostname.replace("www.", "")}
                            </a>
                          </div>
                          {b.teks_viral && (
                            <p className="mt-1 text-xs text-slate-500">
                              <span className="font-semibold text-slate-600">Viral:</span> {b.teks_viral}
                            </p>
                          )}
                          {b.teks_sumber && (
                            <p className="mt-0.5 text-xs text-slate-500">
                              <span className="font-semibold text-slate-600">Sumber:</span> {b.teks_sumber}
                            </p>
                          )}
                          {b.catatan && <p className="mt-1 text-xs text-slate-600">{b.catatan}</p>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </>
            ) : (
              <Empty>Belum diverifikasi. Paket bukti akan muncul setelah pencarian dijalankan.</Empty>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader judul="Draf klarifikasi" keterangan="Klaim → fakta → apa yang diubah → bukti." />
          {draf ? (
            <DrafKlarifikasi draf={draf} />
          ) : verifikasi && verifikasi.status !== "terbukti_diubah" ? (
            <Empty>
              Tidak ada draf klarifikasi. Status <span className="font-semibold">{LABEL_VERIFIKASI[verifikasi.status]}</span>{" "}
              tidak menghasilkan klarifikasi otomatis — klaim dieskalasi ke petugas untuk diperiksa manual.
            </Empty>
          ) : (
            <Empty>Belum ada draf. Verifikasi dulu untuk menyusun klarifikasi.</Empty>
          )}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader judul="Persetujuan petugas" />
          <PanelPersetujuan claimId={klaim.claim_id} verifikasi={verifikasi} onSelesai={() => void muat()} />
        </Card>
      </div>

      <Card>
        <CardHeader judul="Riwayat aksi" keterangan="Jejak audit, tidak bisa diubah dari dashboard." />
        {riwayat.length === 0 ? (
          <Empty>Belum ada riwayat.</Empty>
        ) : (
          <ol className="divide-y divide-slate-100">
            {riwayat.map((r, i) => (
              <li key={`${r.waktu}-${i}`} className="flex items-start gap-3 px-5 py-3 text-sm">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />
                <div className="min-w-0">
                  <p className="text-slate-800">{LABEL_AKSI[r.aksi] ?? r.aksi}</p>
                  <p className="text-xs text-slate-400">
                    {formatTanggalWaktu(r.waktu)}
                    {r.aktor ? ` · ${r.aktor}` : ""}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

function Info({ label, nilai }: { label: string; nilai: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-0.5 text-sm text-slate-800">{nilai}</p>
    </div>
  );
}