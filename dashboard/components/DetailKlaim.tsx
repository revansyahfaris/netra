"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

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
  korroborasi: "Korroborasi",
};

const LABEL_TAHAP: Record<string, string> = {
  menunggu: "antre",
  pencarian: "cari sumber & Lens",
  verifikasi: "verifikasi AI",
};

export function DetailKlaim({ id }: { id: string }) {
  const [data, setData] = useState<KlaimLengkap | null>(null);
  const [galat, setGalat] = useState<string | null>(null);
  const [proses, setProses] = useState(false);
  const [tahap, setTahap] = useState<string | null>(null);
  const [semuaKandidat, setSemuaKandidat] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aktifRef = useRef(true);

  const hentikanPoll = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const muat = useCallback(async (pertahankanGalat = false) => {
    try {
      setData(await api.klaim(id));
      if (!pertahankanGalat) {
        setGalat(null);
      }
    } catch (e) {
      setGalat(e instanceof ApiError ? e.message : "Gagal memuat klaim.");
    }
  }, [id]);

  const pantauJob = useCallback(async () => {
    if (!aktifRef.current) return;
    hentikanPoll();
    try {
      const st = await api.statusPipeline(id);
      if (!aktifRef.current) return;
      if (st.status_kerja === "antre" || st.status_kerja === "berjalan") {
        setProses(true);
        setTahap(st.tahap_saat_ini);
        timerRef.current = setTimeout(() => {
          void pantauJob();
        }, 1500);
        return;
      }
      setProses(false);
      setTahap(null);
      if (st.status_kerja === "gagal") {
        const pesan = st.error || "Pipeline gagal dijalankan.";
        await muat(true);
        if (aktifRef.current) {
          setGalat(pesan);
        }
        return;
      }
      if (st.status_kerja === "selesai") {
        await muat();
      }
    } catch {
      if (!aktifRef.current) return;
      setProses(false);
      setTahap(null);
    }
  }, [hentikanPoll, id, muat]);

  useEffect(() => {
    aktifRef.current = true;
    setProses(false);
    setTahap(null);
    void muat().then(() => {
      void api
        .statusPipeline(id)
        .then((st) => {
          if (!aktifRef.current) return;
          if (st.status_kerja === "antre" || st.status_kerja === "berjalan") {
            setProses(true);
            setTahap(st.tahap_saat_ini);
            timerRef.current = setTimeout(() => {
              void pantauJob();
            }, 1500);
          } else if (st.status_kerja === "gagal") {
            setGalat(st.error || "Pipeline gagal dijalankan.");
          }
        })
        .catch(() => {
          /* abaikan bila status tidak tersedia */
        });
    });
    return () => {
      aktifRef.current = false;
      hentikanPoll();
    };
  }, [hentikanPoll, id, muat, pantauJob]);

  async function jalankan() {
    setProses(true);
    setTahap("menunggu");
    setGalat(null);
    hentikanPoll();
    try {
      const st = await api.antrePipeline(id);
      if (!aktifRef.current) return;
      setTahap(st.tahap_saat_ini);
      timerRef.current = setTimeout(() => {
        void pantauJob();
      }, 1000);
    } catch (e) {
      setProses(false);
      setTahap(null);
      setGalat(e instanceof ApiError ? e.message : "Gagal menjadwalkan pipeline.");
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
  const kandidatTampil = semuaKandidat ? kandidat : kandidat.slice(0, 3);
  const draf = verifikasi?.draf_klarifikasi ?? null;
  const terbukti = verifikasi?.status === "terbukti_diubah";

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
            Halaman bukti publik
          </Link>
          <button
            type="button"
            onClick={() => void jalankan()}
            disabled={proses}
            className="rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {proses
              ? `Memproses (${LABEL_TAHAP[tahap ?? ""] ?? tahap ?? "antre"})…`
              : verifikasi
                ? "Verifikasi ulang"
                : "Jalankan verifikasi"}
          </button>
        </div>
      </div>

      {/* 1. Klaim */}
      <Card>
        <div className="px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            {klaim.level && (
              <span className={cn("rounded px-2 py-0.5 text-[11px] font-semibold", WARNA_LEVEL[klaim.level])}>
                Prioritas {LABEL_LEVEL[klaim.level]}
                {klaim.skor_prioritas != null ? ` · ${klaim.skor_prioritas.toFixed(2)}` : ""}
              </span>
            )}
            <Badge tone={WARNA_PIPELINE[klaim.status_pipeline]}>{LABEL_PIPELINE[klaim.status_pipeline]}</Badge>
            <span className="ml-auto font-mono text-xs text-slate-400">
              {klaim.claim_id}
              {pencarian ? ` · ${pencarian.mode}` : ""}
            </span>
          </div>
          <h1 className="mt-2 text-lg font-semibold leading-snug text-slate-900">{klaim.teks_klaim}</h1>
          <p className="mt-1.5 text-xs text-slate-500">
            {klaim.jenis_media} · ditemukan {formatTanggal(klaim.tanggal_ditemukan)} ·{" "}
            {formatAngka(klaim.jumlah_share)} share · {formatAngka(klaim.jumlah_view)} view ·{" "}
            {formatAngka(klaim.laju_sebar)}/jam
            {klaim.media_url && (
              <>
                {" · "}
                <a href={klaim.media_url} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">
                  buka media viral
                </a>
              </>
            )}
          </p>
          {klaim.alasan && (
            <details className="mt-2 text-xs text-slate-600">
              <summary className="cursor-pointer select-none text-slate-500 hover:text-slate-700">
                Kenapa prioritas ini?
              </summary>
              <p className="mt-1">{klaim.alasan}</p>
            </details>
          )}
        </div>
      </Card>

      {galat && <ErrorBox pesan={galat} onRetry={() => void muat()} />}

      {/* 2. Kesimpulan */}
      <Card>
        <div className="px-5 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Kesimpulan Netra</p>
          {verifikasi ? (
            <div className="mt-2 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={WARNA_VERIFIKASI[verifikasi.status]}>{LABEL_VERIFIKASI[verifikasi.status]}</Badge>
                {verifikasi.perlu_eskalasi && (
                  <Badge tone="bg-amber-50 text-amber-800 ring-amber-200">Eskalasi ke petugas</Badge>
                )}
                {terbukti && (
                  <span className="text-xs text-slate-500">keyakinan {persen(verifikasi.keyakinan)}</span>
                )}
                {verifikasi.waktu_proses_detik != null && (
                  <span className="text-xs text-slate-400">· {verifikasi.waktu_proses_detik}s</span>
                )}
              </div>
              {verifikasi.ringkasan && (
                <p className="max-w-4xl text-sm leading-relaxed text-slate-700">{verifikasi.ringkasan}</p>
              )}
              {verifikasi.perubahan.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-slate-500">
                    {terbukti ? "Yang diubah:" : "Dugaan (belum terbukti):"}
                  </span>
                  {verifikasi.perubahan.map((p) => (
                    <Badge
                      key={p}
                      tone={
                        terbukti
                          ? "bg-rose-50 text-rose-700 ring-rose-200"
                          : "bg-slate-50 text-slate-600 ring-slate-200"
                      }
                    >
                      {LABEL_PERUBAHAN[p] ?? p}
                    </Badge>
                  ))}
                </div>
              )}
              {verifikasi.metode.length > 0 && (
                <p className="text-xs text-slate-400">
                  Metode: {verifikasi.metode.map((m) => LABEL_METODE[m] ?? m).join(" · ")}
                </p>
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-500">
              Belum diverifikasi. Klik <span className="font-medium">Jalankan verifikasi</span> untuk mencari
              sumber asli dan menyusun paket bukti.
            </p>
          )}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-5">
        {/* 3. Sumber */}
        <Card className="lg:col-span-3">
          <CardHeader
            judul={`Kandidat sumber asli${kandidat.length ? ` (${kandidat.length})` : ""}`}
            keterangan="Urutan dari yang paling mungkin asli."
          />
          {kandidat.length === 0 ? (
            <Empty>Belum ada kandidat. Jalankan verifikasi untuk mencari sumber.</Empty>
          ) : (
            <>
              <ol className="divide-y divide-slate-100">
                {kandidatTampil.map((k, i) => (
                  <li key={k.url} className="px-5 py-3.5">
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
                        <a
                          href={k.url}
                          target="_blank"
                          rel="noreferrer"
                          className="line-clamp-2 font-medium text-slate-900 hover:text-brand-700"
                        >
                          {slugJudul(k)}
                        </a>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {LABEL_SUMBER[k.jenis_sumber]}
                          {k.uploader ? ` · ${k.uploader}` : ""}
                          {k.tanggal_unggah ? ` · ${formatTanggal(k.tanggal_unggah)}` : ""}
                          {k.ada_watermark ? " · watermark" : ""}
                        </p>
                        <div className="mt-2 max-w-xs">
                          <SkorBar nilai={k.skor} label="Skor sumber asli" compact netral />
                        </div>
                        <details className="mt-1.5 text-xs">
                          <summary className="cursor-pointer select-none text-slate-400 hover:text-slate-600">
                            Rincian
                          </summary>
                          <div className="mt-1.5 space-y-1.5">
                            <p className="break-all text-slate-400">{k.url}</p>
                            <p className="text-slate-500">
                              metode {k.metode}
                              {k.resolusi ? ` · ${k.resolusi}p` : ""}
                              {k.cuplikan ? ` · cuplikan ${k.cuplikan}` : ""}
                              {k.kecocokan_audio != null ? ` · audio ${persen(k.kecocokan_audio)}` : ""}
                            </p>
                            <div className="flex flex-wrap gap-1.5">
                              {Object.entries(k.rincian_skor).map(([komponen, nilai]) => (
                                <span
                                  key={komponen}
                                  className="rounded bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-500 ring-1 ring-inset ring-slate-200"
                                >
                                  {URUTAN_RINCIAN[komponen] ?? komponen} {nilai.toFixed(2)}
                                </span>
                              ))}
                            </div>
                          </div>
                        </details>
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              {kandidat.length > 3 && (
                <button
                  type="button"
                  onClick={() => setSemuaKandidat((v) => !v)}
                  className="w-full border-t border-slate-100 px-5 py-2.5 text-center text-xs font-medium text-brand-600 hover:bg-slate-50"
                >
                  {semuaKandidat ? "Tampilkan lebih sedikit" : `Tampilkan ${kandidat.length - 3} kandidat lain`}
                </button>
              )}
            </>
          )}
        </Card>

        {/* 4. Bukti + keputusan */}
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <CardHeader
              judul={`Bukti${verifikasi?.bukti.length ? ` (${verifikasi.bukti.length})` : ""}`}
              keterangan="Teks viral dibandingkan dengan sumber."
            />
            {!verifikasi || verifikasi.bukti.length === 0 ? (
              <Empty>Belum ada bukti terstruktur.</Empty>
            ) : (
              <ul className="space-y-2 px-5 py-4">
                {verifikasi.bukti.map((b, i) => (
                  <li key={`${b.url}-${i}`} className="rounded-lg border border-slate-200 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                        {LABEL_JENIS_BUKTI[b.jenis] ?? b.jenis}
                        {b.cuplikan ? ` · ${b.cuplikan}` : ""}
                      </span>
                      <a
                        href={b.url}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-auto max-w-[50%] truncate text-xs text-brand-600 hover:underline"
                      >
                        {new URL(b.url).hostname.replace("www.", "")}
                      </a>
                    </div>
                    {b.teks_sumber && <p className="mt-1 text-sm text-slate-700">{b.teks_sumber}</p>}
                    {(b.teks_viral || b.catatan) && (
                      <details className="mt-1 text-xs text-slate-500">
                        <summary className="cursor-pointer select-none text-slate-400 hover:text-slate-600">
                          Bandingkan
                        </summary>
                        {b.teks_viral && (
                          <p className="mt-1">
                            <span className="font-semibold text-slate-600">Viral:</span> {b.teks_viral}
                          </p>
                        )}
                        {b.catatan && <p className="mt-1">{b.catatan}</p>}
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader judul="Keputusan petugas" />
            <PanelPersetujuan claimId={klaim.claim_id} verifikasi={verifikasi} onSelesai={() => void muat()} />
          </Card>
        </div>
      </div>

      {/* 5. Draf (hanya bila ada) */}
      {draf && (
        <Card>
          <CardHeader judul="Draf klarifikasi" keterangan="Wajib disetujui petugas sebelum tayang." />
          <DrafKlarifikasi draf={draf} />
        </Card>
      )}

      {/* 6. Audit */}
      <Card>
        <details>
          <summary className="cursor-pointer select-none px-5 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50">
            Riwayat aksi ({riwayat.length}){" "}
            <span className="font-normal text-slate-400">· jejak audit, tidak bisa diubah</span>
          </summary>
          {riwayat.length === 0 ? (
            <Empty>Belum ada riwayat.</Empty>
          ) : (
            <ol className="divide-y divide-slate-100 border-t border-slate-100">
              {riwayat.map((r, i) => (
                <li key={`${r.waktu}-${i}`} className="flex items-start gap-3 px-5 py-2.5 text-sm">
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
        </details>
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