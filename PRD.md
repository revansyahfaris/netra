# PRD — Netra

Sistem pendukung Dinas Penerangan TNI AD untuk memverifikasi dan mengklarifikasi konten viral
yang dimanipulasi. Netra **tidak** mendeteksi hoaks (memakai sistem deteksi yang sudah ada);
Netra melacak sumber asli, membuktikan apa yang diubah, lalu menyiapkan klarifikasi yang
disetujui petugas sebelum tayang.

Versi: 0.3 (13 Nov 2026) · Status: prototipe untuk demo 15 Nov 2026

---

## 1. Masalah

Konten viral yang dipelintir (video lama dinarasikan sebagai kejadian baru, kutipan pejabat yang
tidak pernah diucapkan) menyebar lebih cepat daripada kemampuan tim menerangkan. Verifikasi manual
memakan waktu karena harus mencari sumber asli di banyak platform, lalu menyusun klarifikasi dari nol.
Akibatnya klarifikasi terlambat, atau tidak terbit sama sekali.

## 2. Pengguna

| Pengguna | Kebutuhan |
|---|---|
| Petugas Dispenad (pengguna utama) | Antrean terprioritas, paket bukti yang bisa diperiksa, draf klarifikasi siap edit, tombol setujui/tolak |
| Pimpinan | Ringkasan cepat: berapa klaim, mana yang terbukti diubah, mana yang dieskalasi |
| Publik | Halaman bukti yang bisa dibagikan: klaim, fakta, sumber asli, tautan |

## 3. Tujuan & metrik prototipe

| Tujuan | Metrik |
|---|---|
| Waktu verifikasi turun | Dari jam kerja manual menjadi < 2 menit per klaim di demo |
| Keputusan berbasis bukti | Setiap status `terbukti_diubah` punya ≥ 2 bukti tertaut |
| Tidak ada klarifikasi tanpa manusia | 100% klarifikasi melewati `status_persetujuan` |
| Kejujuran status | Kasus tanpa sumber bersih keluar `belum_bisa_diverifikasi`, bukan dipaksakan |

## 4. Ruang lingkup

**Termasuk:** prioritas klaim, pencarian sumber asli, pencocokan frame/audio untuk video,
RAG ke korpus resmi untuk klaim kutipan, perbandingan oleh LLM, penyusunan draf klarifikasi
3 format, antrean & persetujuan petugas, halaman bukti publik.

**Tidak termasuk:** deteksi hoaks, auto-publish klarifikasi, manajemen akun/multi-tenant,
aplikasi mobile, integrasi langsung ke API platform media sosial.

## 5. Pipeline

```
Deteksi (sistem yang ada)
   │
   ▼
Prioritas  skor = 0.4·sensitivitas + 0.3·laju_sebar + 0.2·jangkauan + 0.1·kebaruan
   │
   ▼
Verifikasi  pencarian sumber (keyword/kutipan/frame match) → RAG/OCR/transkrip → perbandingan LLM
   │
   ▼
Klarifikasi  klaim → fakta → apa yang diubah → bukti  (kartu, versi pendek, pesan WhatsApp)
   │
   ▼
Persetujuan manusia  setujui / tolak + catatan → halaman bukti publik
```

### Tiga tingkat keluaran

| Status | Arti | Tindakan |
|---|---|---|
| `terbukti_diubah` | Sumber asli ditemukan dan perbedaannya konkret | Susun draf klarifikasi → menunggu persetujuan |
| `tidak_ditemukan` | Tidak ada sumber pendukung sama sekali | Eskalasi ke petugas, tanpa draf klarifikasi |
| `belum_bisa_diverifikasi` | Kandidat ada tetapi tidak ada yang bersih/otentik | Eskalasi, tampilkan kandidat + alasan keraguan |

Worst case yang disepakati: bila sumber tertua pun terindikasi dimanipulasi, sistem **tidak**
memaksakan klarifikasi. Status `belum_bisa_diverifikasi` + eskalasi.

## 6. Fungsi utama

### 6.1 Prioritas
Klasifikasi topik (pimpinan, operasi, SARA, keselamatan, umum) + sinyal penyebaran → skor 0–1
dan level tinggi/sedang/rendah, dengan alasan yang bisa dibaca petugas.

### 6.2 Pencarian sumber asli
Variasi query dibantu LLM (kutipan persis + kata kunci tanpa narasi waktu), pencarian web,
YouTube, reverse image; untuk video: unduh kandidat, cocokkan frame (perceptual hash) dan pola
audio, tampilkan detik asal potongan.

Peringkat kandidat: kemiripan 30%, tanggal unggah paling awal 25%, jenis sumber 15%,
resolusi 10%, bebas watermark 10%, kecocokan audio 10%. Komponen tanpa data dilewati dan
bobotnya dibagi ulang — petugas bisa melihat rincian tiap komponen.

### 6.3 Verifikasi AI
RAG ke korpus resmi (siaran pers, notulensi, rilis video), OCR untuk teks pada gambar/video,
transkrip audio, lalu perbandingan terarah: apa yang dipotong, tanggal yang digeser, kutipan
yang tidak ada di sumber asli.

### 6.4 Klarifikasi
Draf dalam tiga format dari satu hasil analisis: kartu visual, versi pendek, pesan WhatsApp.
Selalu berstruktur klaim → fakta → apa yang diubah → bukti.

### 6.5 Persetujuan manusia
Petugas membuka paket bukti, membaca draf, lalu menyetujui atau menolak dengan catatan.
Sistem tidak pernah menayangkan klarifikasi tanpa keputusan petugas. Semua keputusan tercatat
di audit trail.

## 7. Halaman dashboard

```
/antrean           tabel klaim: skor prioritas, level, topik, status, jumlah share
                   filter status & level, pencarian, urut skor
/klaim/{id}        ringkasan klaim · kandidat + rincian skor · paket bukti ·
                   draf klarifikasi (3 tab, tombol salin) · panel persetujuan · riwayat aksi
/bukti/{id}        halaman publik: status, klaim, fakta, sumber asli, bukti, waktu verifikasi
                   tanpa catatan internal · banner SIMULASI untuk data demo
/statistik         ringkasan angka (bisa jadi bagian /antrean)
```

Wireframe `/klaim/{id}`:

```
┌──────────────────────────────────────────────────────────┐
│ [PRIORITAS TINGGI 0.78]  c001 · video · 11 Nov 2026      │
│ "Video prajurit ... disebut terjadi minggu ini"          │
├───────────────────────────────┬──────────────────────────┤
│ Kandidat sumber (3)           │ Paket bukti              │
│ 1. YouTube 2019  skor 0.92 ▓▓ │ ▸ frame 00:42 vs 00:00   │
│    judul · uploader · rincian │ ▸ audio cocok 0.88      │
│ 2. Facebook 2022 skor 0.69    │ ▸ metadata tanggal       │
│ 3. TikTok 2026   skor 0.50    │                          │
├───────────────────────────────┴──────────────────────────┤
│ Draf klarifikasi  [Kartu] [Pendek] [WhatsApp]   [Salin]  │
├──────────────────────────────────────────────────────────┤
│ Petugas [........]  Catatan [................]            │
│ [ Setujui & siapkan publikasi ]   [ Tolak ]              │
└──────────────────────────────────────────────────────────┘
```

## 8. Kasus demo

| # | Jenis | Klaim | Jalur | Status |
|---|---|---|---|---|
| 1 | Formal | `c002` — kutipan "TNI siap ambil alih pemerintahan sipil" | RAG korpus resmi → kutipan tidak ada | `terbukti_diubah` |
| 2 | Informal | `c001` — video 2019 dinarasikan "minggu ini" | frame match + audio → potongan 00:42 | `terbukti_diubah` |
| 3 | Worst case | `c001b` — kandidat tertua ternyata reupload | tidak ada sumber bersih | `belum_bisa_diverifikasi` + eskalasi |
| 4 | Eskalasi | `c003` — biaya Bintara | tidak ada sumber pendukung | `tidak_ditemukan` + eskalasi |

Semua data **sintetis** dan diberi label SIMULASI. Tidak memakai nama pejabat nyata dengan
kutipan palsu.

Skrip demo (5 menit):
1. Buka `/antrean`, tunjukkan urutan prioritas dan alasan skor.
2. Buka `c001`, jalankan pencarian → kandidat terurut, tunjukkan rincian skor dan detik potongan.
3. Jalankan verifikasi → status + bukti + draf klarifikasi.
4. Setujui sebagai petugas → status berubah, audit tercatat.
5. Buka `/bukti/c001` → halaman publik yang bisa dibagikan.
6. Ulangi singkat `c002` (RAG) dan `c001b` (worst case, eskalasi).

## 9. Arsitektur

```
dashboard/ (Next.js + Tailwind)
      │ HTTP
backend/ (FastAPI)
  ├── priority/   skor & klasifikasi
  ├── search/     query, web search, frame match, peringkat
  ├── ai/         RAG, OCR/ASR, perbandingan, draf klarifikasi
  ├── store/      Postgres (Neon) / SQLite, audit, seed
  └── schemas.py  kontrak data v2
```

Tanpa API key, sistem tetap jalan dalam mode demo (data contoh). Dashboard tidak punya auth —
ada pemilih "bertindak sebagai petugas" untuk prototipe; keputusan tercatat atas nama itu.

## 10. Keamanan & etika

- `.env` tidak pernah di-commit; `DATABASE_URL` dan API key hanya lokal.
- Halaman bukti publik tidak menampilkan catatan internal petugas.
- Data demo diberi banner SIMULASI.
- Klarifikasi tidak pernah terbit otomatis; selalu ada persetujuan manusia.

## 11. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Modul AI belum siap | Demo formal gagal | Stub kontrak-valid + korpus kecil; target Jumat malam |
| ffmpeg/yt-dlp gagal saat demo | Kasus video gagal | Video demo lokal, mode demo, rekam lebih awal |
| API key habis/diblokir | Mode live mati | Fallback data dummy otomatis |
| Waktu | Fitur setengah jadi | Fitur beku Sabtu 20.00 |

## 12. Rencana kerja

Lihat `task.md`.