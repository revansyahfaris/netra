# Skrip demo (5 menit)

Prasyarat: backend jalan (`uvicorn main:app`), dashboard jalan (`npm run dev`), data demo baru
(`POST /seed` atau tombol "Reset data demo" di `/antrean`). Layar bersih, zoom 110%, notifikasi mati.

| Waktu | Layar | Yang dikatakan |
|---|---|---|
| 0:00 | `/antrean` | "Ini antrean klaim dari sistem deteksi yang sudah ada. Netra tidak mendeteksi hoaks — Netra mencari sumber aslinya." |
| 0:20 | `/antrean` | Tunjukkan skor prioritas dan alasan: "Skor dari sensitivitas topik, laju sebar, jangkauan, kebaruan. Petugas bisa melihat alasannya." |
| 0:40 | buka `c001` | "Kasus informal: video yang disebut kejadian minggu ini." |
| 0:55 | klik **Jalankan pencarian & verifikasi** | "Sistem membuat variasi query, mencari kandidat, lalu mencocokkan frame dan audio." |
| 1:30 | kandidat | "Tiga kandidat, terurut. Yang tertua YouTube 2019, skor 0.92 — resolusi lebih tinggi, tanpa watermark, audio cocok. Yang viral justru unggahan 2026, watermark, resolusi rendah." |
| 2:00 | rincian skor | "Setiap komponen skor terlihat: kemiripan, tanggal, jenis sumber, resolusi, kebersihan, audio. Bukan kotak hitam." |
| 2:20 | paket bukti | "Cuplikan 00:42 di video asli menjadi potongan viral. Ini bukti yang dilihat petugas." |
| 2:40 | draf klarifikasi | "Draf disusun klaim → fakta → apa yang diubah → bukti, dalam tiga format: kartu, versi pendek, WhatsApp." |
| 3:00 | panel persetujuan | Isi nama petugas, klik **Setujui klarifikasi**. "Tidak ada yang tayang otomatis." |
| 3:20 | `/bukti/c001` | "Halaman bukti publik. Hanya data yang layak publik — catatan internal petugas tidak ikut." |
| 3:40 | buka `c002`, jalankan | "Kasus formal: kutipan yang tidak ada di korpus resmi. Jalur RAG." |
| 4:10 | buka `c001b`, jalankan | "Worst case: kandidat tertua pun akun pribadi dan berwatermark. Sistem tidak memaksakan klarifikasi — status 'belum bisa diverifikasi' dan dieskalasi ke petugas." |
| 4:40 | `/klaim/c001` riwayat | "Semua keputusan tercatat di audit trail." |
| 4:50 | penutup | "Tiga tingkat keluaran: terbukti diubah, tidak ditemukan sumber, belum bisa diverifikasi. Manusia tetap di ujung keputusan." |

## Catatan saat merekam

- Rekam 1080p, kursor diperlambat, jangan buru-buru di bagian skor.
- Matikan tab lain dan notifikasi; sembunyikan bookmark bar.
- Kalau API lambat karena mode live, sebut "mode demo" — data contoh sudah disiapkan.
- Semua data adalah simulasi. Jangan menyebut nama pejabat nyata.
- Siapkan tab cadangan: `/bukti/c001` yang sudah disetujui, kalau ada langkah gagal saat rekaman.