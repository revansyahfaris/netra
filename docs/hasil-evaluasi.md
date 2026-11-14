# Hasil evaluasi Netra

Mode: **demo (tanpa API berbayar)** · 8 kasus · dibuat dengan `python scripts/evaluasi.py`

- Status verifikasi sesuai label tim: **7/7**
- Salah menuduh konten asli sebagai manipulasi (false positive): **0**

| Kasus | Klaim | Prioritas | Status Netra | Label tim | Keyakinan | Bukti | Waktu |
|---|---|---|---|---|---|---|---|
| r001 | Video aparat TNI mendobrak pintu dan mengambil komputer di Kantor B... | 0.94 (tinggi) | Terbukti diubah ✓ | Terbukti diubah | 87% | 1 | 0.0s |
| r002 | Maklumat Kapuspen TNI Mayjen Sisriadi: mahasiswa bisa minta pendamp... | 0.88 (tinggi) | Terbukti diubah ✓ | Terbukti diubah | 82% | 1 | 0.0s |
| c002 | Kasad disebut menyatakan 'TNI siap ambil alih pemerintahan sipil' | 0.86 (tinggi) | Terbukti diubah ✓ | Terbukti diubah | 75% | 2 | 0.0s |
| c001 | Video prajurit TNI AD membubarkan warga di Papua, disebut terjadi m... | 0.85 (tinggi) | Terbukti diubah ✓ | Terbukti diubah | 87% | 2 | 0.0s |
| r003 | Video tank TNI dikerahkan ke Kepulauan Riau untuk persiapan perang | 0.75 (tinggi) | Terbukti diubah ✓ | Terbukti diubah | 84% | 1 | 0.0s |
| c001b | Video pengamanan disebut baru terjadi pekan ini, beredar tanpa meny... | 0.59 (sedang) | Dieskalasi ke petugas ✓ | Dieskalasi ke petugas | – | 3 | 0.0s |
| c003 | Pendaftaran Bintara TNI AD 2027 dipungut biaya Rp15 juta | 0.46 (sedang) | Terbukti diubah | – | 87% | 1 | 0.0s |
| c004 | Disebut ada pengumuman resmi TNI AD tentang pembagian sembako di ma... | 0.40 (sedang) | Sumber tidak ditemukan ✓ | Sumber tidak ditemukan | – | 0 | 0.0s |

Catatan: mode demo memakai kandidat sumber yang sudah disiapkan di `data/`, jadi angka ini menguji logika peringkat, verifikasi, dan eskalasi, bukan kualitas mesin pencari.
