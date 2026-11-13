# Task — Netra (deadline 15 Nov 2026)

Konvensi: `[ ]` belum, `[x]` selesai. Nama di awal tiap item = pemilik.
Fitur beku: **Sabtu 14 Nov 20.00**. Setelah itu hanya perbaikan bug dan perekaman demo.

## Keputusan yang sudah diambil

- [x] Kontrak data v2 (`docs/kontrak-data.md`, `backend/schemas.py`) — 13 Nov
- [x] Dashboard: Next.js + Tailwind, tanpa auth, pemilih "bertindak sebagai petugas"
- [x] Penyimpanan: Neon Postgres + fallback SQLite
- [x] Kasus demo: `c002` (formal), `c001` (informal), `c001b` (worst case), `c003` (tidak ditemukan)
- [x] Semua data demo sintetis + label SIMULASI
- [x] Pembagian peran mengikuti usulan 8 Nov (Faris / Adriel / Farrel)

## Checkpoint

| Waktu | Target | Status |
|---|---|---|
| Jum 13, 22.00 | Kontrak v2 beku, DB jalan, dashboard skeleton | `[ ]` |
| Sab 14, 12.00 | Kasus formal end-to-end (RAG → bukti → approval) | `[ ]` |
| Sab 14, 20.00 | Kasus informal + worst case, **fitur beku** | `[ ]` |
| Sab 14, 23.00 | Video demo selesai | `[ ]` |
| Min 15, 12.00 | Slide + submit (buffer 12 jam) | `[ ]` |

---

## Farrel — pipeline inti, data, dashboard

### Fase 0 — Preflight
- [x] Clone repo, branch `farrel/pipeline-dashboard`
- [x] ffmpeg 9.0.2 terpasang, tes frame tidak lagi di-skip
- [x] venv Python 3.12 + `pip install -r requirements.txt`
- [x] `pytest -q` → 15 passed
- [x] Smoke test `POST /pipeline/c001` (demo mode)
- [x] Verifikasi akses push (`git push --dry-run`)

### Fase 1 — Kontrak & dokumen
- [x] `docs/kontrak-data.md` v2
- [x] `PRD.md`
- [x] `task.md`
- [x] `schemas.py`: `judul`, `uploader`, `thumbnail_url`, `rincian_skor`, `Bukti`, `status_persetujuan`, `status_pipeline`, `KlaimLengkap`
- [x] `search/models.py`: teruskan `judul`/`uploader`/`rincian_skor` ke kandidat *(perlu review Faris)*
- [x] `pytest -q` masih hijau setelah perubahan kontrak

### Fase 2 — Penyimpanan
- [x] `store/db.py`: engine, `DATABASE_URL`, fallback SQLite, `create_all`
- [x] `store/models.py`: `netra_klaim`, `netra_pencarian`, `netra_verifikasi`, `netra_audit`
- [x] `store/repo.py`: simpan/ambil klaim, pencarian, verifikasi, antrean, persetujuan, audit, statistik
- [x] `store/seed.py`: muat `data/dummy/*.json`, idempoten
- [x] `main.py` memakai repo, bukan `dict` global; data bertahan setelah restart
- [x] `tests/test_store.py`

### Fase 3 — Endpoint persetujuan & publik
- [x] `PATCH /verifikasi/{id}/persetujuan` + validasi transisi + audit
- [x] `GET /antrean?status=&level=`
- [x] `GET /klaim/{id}` → `KlaimLengkap`
- [x] `GET /bukti/{id}` → proyeksi publik
- [x] `GET /statistik`
- [x] `POST /seed` (dev)
- [x] `tests/test_persetujuan.py` (termasuk 409 dan wajib catatan saat menolak)

### Fase 4 — Dashboard
- [x] Scaffold Next.js + Tailwind, `lib/api.ts`
- [x] `/antrean` — prioritas, level, topik, status, filter
- [x] `/klaim/[id]` — kandidat + rincian skor, paket bukti, draf 3 format + salin, panel persetujuan, riwayat
- [x] `/bukti/[id]` — halaman publik + banner SIMULASI
- [x] State kosong/loading/error
- [x] `npm run build` bersih

### Fase 5 — Integrasi & demo
- [x] 3 status tampil benar di UI (terbukti / tidak ditemukan / belum bisa diverifikasi)
- [x] Adaptor `ai/` bila bentuk output beda (tanpa mengubah logika AI)
- [x] `docs/skrip-demo.md`
- [x] Bantu rekam video demo

### Fase 6 — Rilis
- [x] README: cara jalan, env, arsitektur
- [x] `pytest -q` + `npm run build` terakhir
- [x] PR ke `main`, minta review Faris
- [x] (opsional) deploy dashboard Vercel + backend Render — hanya bila waktu tersisa

---

## Adriel — lapisan AI

Target minimum Jumat malam: `jalankan_verifikasi` mengembalikan `HasilVerifikasi` valid untuk `c002`.

- [ ] Korpus resmi `backend/data/korpus/*.md` (10–15 dokumen: siaran pers, notulensi, rilis)
- [ ] Retrieval ringan (TF-IDF/BM25) + sitasi dokumen — tanpa vector DB
- [ ] OCR/gambar & transkrip audio: skrip sekali jalan, hasil disimpan JSON dengan penanda `ocr`/`asr`/`manual`
- [ ] Perbandingan viral vs sumber oleh LLM → `status`, `perubahan[]`, `ringkasan`, `keyakinan`
- [ ] `bukti[]` terisi minimal 2 item untuk status `terbukti_diubah`
- [ ] Draf klarifikasi 3 format dari satu panggilan LLM (kartu, pendek, WhatsApp)
- [ ] Aturan worst case: tidak ada sumber bersih → `belum_bisa_diverifikasi` + `perlu_eskalasi`
- [ ] Data `c002` dan `c001b` siap

## Faris — pencari, API, narasi

- [x] Modul prioritas, pencari, API, tes
- [ ] Review PR Farrel (bagian `schemas.py` dan `search/models.py`)
- [ ] Dataset video demo: file asli + viral (lokal, bukan tautan)
- [ ] Perapian mode live (SerpAPI/yt-dlp) atau putuskan tetap demo
- [ ] Narasi + slide presentasi
- [ ] Bantu potong video demo

## Bersama

- [ ] Uji end-to-end ketiga kasus di mesin bersih (`git clone` baru)
- [ ] Rekam video demo (5 menit) dengan label SIMULASI
- [ ] Cek tidak ada `.env`, API key, atau password di repo
- [ ] Submit sebelum Minggu 15 Nov

---

## Blocker / keputusan terbuka

| Hal | Pemilik | Status |
|---|---|---|
| Akses tulis GitHub Farrel | Faris | terverifikasi (dry-run push lolos) |
| Rotasi password Neon yang sempat terekspos di chat | Farrel | `[ ]` sebelum submit |
| `search/models.py` perubahan 3 baris | Faris review | `[ ]` |
| Kesiapan `ai/` untuk demo formal | Adriel | `[ ]` |