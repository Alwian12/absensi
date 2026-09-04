# Final Readiness Checklist

## 1. Kesesuaian Judul dan Implementasi
- [x] Backend utama menggunakan Python (FastAPI).
- [x] Frontend utama menggunakan HTML + Bootstrap + JavaScript.
- [x] Absensi wajah tersedia dengan endpoint registrasi dan verifikasi wajah.
- [x] Modul jurnal, pembimbing, peserta, penilaian, dan dashboard tersedia.
- [x] Export laporan PDF dan Excel tersedia via endpoint API.

## 2. Kesiapan Demo Teknis
- [x] Server dapat dijalankan lokal dengan Uvicorn.
- [x] Route web dan route API dipisahkan.
- [x] Endpoint API utama sudah bernamespace /api.
- [x] Template frontend terhubung dengan file JavaScript eksternal.
- [x] Data demo dapat digenerate melalui script seed.

## 3. Keamanan Dasar
- [x] JWT tersedia pada API auth.
- [x] Hashing password diterapkan.
- [x] RBAC dasar diterapkan pada halaman manajemen dan laporan.
- [x] Route laporan dibatasi untuk role admin.
- [x] Validasi akses role otomatis (30/30 PASS) terdokumentasi.
- [x] Konfigurasi `DEBUG` dan `SQL_ECHO` sudah dipisahkan via environment.

## 4. Berkas Laporan PKL yang Sudah Siap Dibuat dari Sistem
- [x] Screenshot dashboard role admin/pembimbing/peserta.
- [x] Bukti endpoint API dari /docs.
- [x] Rekap absensi PDF dan Excel.
- [x] Skenario pengujian Black Box dan UAT.

## 5. Catatan Final Sebelum Sidang
- [x] Pastikan dependency terpasang di environment final.
- [x] Siapkan backup database (hasil seed atau data aktual).
- [ ] Uji alur registrasi wajah hingga check-out di perangkat demo.
- [x] Siapkan narasi demo 10 menit sesuai alur proses bisnis.
