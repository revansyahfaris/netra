# Kontrak Data Netra — v2

Berlaku sejak 13 November 2026. Semua modul (`priority`, `search`, `ai`, `store`, `dashboard`)
mengacu ke file ini dan ke `backend/schemas.py`. Perubahan berikutnya harus disepakati bertiga
dan dicatat di bagian "Riwayat".

## Alur data

```
Klaim ──prioritas──> Klaim (skor, level, label_topik)
      ──pencari───> HasilPencarian { kandidat[] }
      ──AI────────> HasilVerifikasi { status, bukti[], draf_klarifikasi }
      ──petugas───> status_persetujuan + catatan_petugas
```

## 1. Klaim

| Field | Tipe | Sumber | Catatan |
|---|---|---|---|
| `claim_id` | str | sistem deteksi / manual | unik |
| `teks_klaim` | str | input | narasi yang beredar |
| `media_url` | HttpUrl? | input | opsional untuk klaim teks |
| `jenis_media` | `video`/`gambar`/`teks` | input | menentukan jalur pencarian |
| `tanggal_ditemukan` | datetime | input | dipakai skor kebaruan |
| `jumlah_share`, `jumlah_view`, `laju_sebar`, `pengikut_pengunggah` | angka | sistem deteksi | sinyal prioritas |
| `skor_prioritas`, `level`, `label_topik`, `alasan` | diisi `priority` | | level: tinggi ≥0.65, sedang ≥0.4 |
| `status_pipeline` | enum | `store` | lihat state machine |
| `sumber_masuk` | `deteksi`/`manual` | input | manual = diunggah petugas |

## 2. KandidatSumber

| Field | Tipe | Catatan |
|---|---|---|
| `url` | HttpUrl | wajib |
| `tanggal_unggah` | datetime? | makin awal makin kuat |
| `jenis_sumber` | `resmi`/`media`/`pribadi` | bobot 0.15 |
| `metode` | `keyword`/`kutipan`/`frame_match` | asal temuan |
| `kemiripan` | 0–1 | di bawah 0.3 dibuang |
| `cuplikan` | str? | teks kutipan atau timestamp `01:12` |
| `resolusi` | int? | tinggi piksel |
| `ada_watermark` | bool? | |
| `kecocokan_audio` | 0–1? | khusus video |
| `skor` | 0–1? | hasil peringkat |
| `judul`, `uploader`, `thumbnail_url` | str? | **baru** — untuk kartu dashboard |
| `rincian_skor` | dict | **baru** — komponen skor, untuk transparansi di UI |

## 3. HasilVerifikasi

| Field | Tipe | Catatan |
|---|---|---|
| `status` | `terbukti_diubah`/`tidak_ditemukan`/`belum_bisa_diverifikasi` | tiga tingkat keluaran |
| `sumber_utama` | HttpUrl? | kandidat teratas |
| `perubahan` | list enum | `dipotong`, `tanggal_berbeda`, `kutipan_tidak_ada`, `konteks_berbeda`, `lainnya` |
| `ringkasan` | str? | **baru** — 1–3 kalimat untuk petugas |
| `bukti` | list `Bukti` | **baru** — lihat di bawah |
| `keyakinan` | 0–1? | **baru** |
| `metode` | list enum | **baru** — `rag`, `frame_match`, `ocr`, `asr`, `manual` |
| `waktu_proses_detik` | float? | **baru** |
| `draf_klarifikasi` | `{kartu, pendek, whatsapp}`? | wajib ada hanya bila `terbukti_diubah` |
| `perlu_eskalasi` | bool | true untuk dua status selain `terbukti_diubah` |
| `status_persetujuan` | `menunggu`/`disetujui`/`ditolak` | **baru**, default `menunggu` |
| `catatan_petugas`, `disetujui_oleh`, `waktu_persetujuan` | | **baru**, diisi endpoint persetujuan |

### Bukti

| Field | Tipe | Catatan |
|---|---|---|
| `jenis` | `kutipan`/`frame`/`transkrip`/`metadata` | |
| `url` | HttpUrl | sumber bukti |
| `cuplikan` | str? | teks atau timestamp |
| `teks_viral` / `teks_sumber` | str? | sisi yang dibandingkan |
| `catatan` | str? | penjelasan singkat |

## 4. State machine `status_pipeline`

```
baru ──cari──> dicari ──verifikasi──> diverifikasi
                                          │
                            status == terbukti_diubah
                                          ▼
                                menunggu_persetujuan
                                   │            │
                            disetujui        ditolak
                                   │            │
                              dipublikasi   (kembali ke antrean)

status != terbukti_diubah → tetap diverifikasi + perlu_eskalasi=true
(tidak masuk alur persetujuan, naik ke petugas sebagai eskalasi)
```

Aturan:
- `PATCH /verifikasi/{id}/persetujuan` hanya boleh saat `status_persetujuan == "menunggu"` **dan**
  `status == "terbukti_diubah"`. Selain itu → `409`.
- Menolak **wajib** menyertakan `catatan`.
- Setiap perubahan status menulis satu baris audit (`aktor`, `aksi`, `waktu`, `detail`).

## 5. Endpoint

| Endpoint | Fungsi | Status |
|---|---|---|
| `POST /prioritas` | skor prioritas klaim | ada |
| `GET /antrean?status=&level=` | antrean terurut | diperluas |
| `GET /klaim/{id}` | `KlaimLengkap` (klaim + pencarian + verifikasi + riwayat) | diperluas |
| `POST /cari/{id}` | cari kandidat | ada |
| `GET /cari/{id}/proses` | log proses | ada |
| `POST /verifikasi/{id}` | jalankan lapisan AI | ada |
| `POST /pipeline/{id}` | cari + verifikasi (sinkron) | ada |
| `POST /pipeline/{id}/antre` | jadwalkan pipeline di latar belakang (`202`) | **baru** |
| `GET /pipeline/{id}/status` | status pekerjaan pipeline latar belakang | **baru** |
| `GET /media-sementara/{token}` | layani keyframe sementara bertanda tangan HMAC (Google Lens) | **baru** |
| `PATCH /verifikasi/{id}/persetujuan` | setujui/tolak | **baru** |
| `GET /bukti/{id}` | proyeksi publik untuk halaman bukti | **baru** |
| `GET /statistik` | angka ringkas untuk dashboard/slide | **baru** |
| `POST /seed` | reset + isi data demo (dev) | **baru** |
| `GET /health` | status & mode | ada |

## 6. Penyimpanan

- Postgres (Neon) lewat `DATABASE_URL`; fallback `sqlite:///backend/data/netra.db` bila kosong.
- Tabel inti: `netra_klaim`, `netra_pencarian`, `netra_verifikasi`, `netra_klaim_bukti`, `netra_audit`.
- Tabel korpus RAG (`pgvector` di Postgres): `netra_korpus_dokumen` (`doc_id` deterministik dari hash URL ternormalisasi, `cakupan` `resmi`/`temuan`, `kadaluwarsa_pada` TTL 90 hari untuk `temuan`) dan `netra_korpus_chunk`.
- Kolom index: `claim_id`, `status_pipeline`, `status_persetujuan`, `skor_prioritas`, `tanggal_ditemukan`, `doc_id`, `cakupan`.
- Snapshot JSON disimpan utuh supaya kontrak bisa berubah tanpa migrasi besar; tautan bukti ke dokumen/chunk RAG ikut tercatat relasional di `netra_klaim_bukti`.

## Riwayat

| Tanggal | Versi | Perubahan | Oleh |
|---|---|---|---|
| 11 Nov 2026 | v1 | kontrak awal | Faris |
| 13 Nov 2026 | v2 | `judul`/`uploader`/`rincian_skor`, `Bukti`, `ringkasan`, persetujuan, `status_pipeline` | Farrel |
| 14 Nov 2026 | v3 | Integrasi penuh AI Tahap 1–5, JIT Tier-2 `temuan`, `netra_klaim_bukti`, `/media-sementara/{token}`, `/pipeline/{id}/antre` & `/status` | Adriel |