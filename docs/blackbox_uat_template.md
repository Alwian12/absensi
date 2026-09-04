# Template Pengujian Black Box dan UAT

## A. Black Box Test Cases

| ID | Modul | Skenario | Input | Hasil Diharapkan | Hasil Aktual | Status |
|---|---|---|---|---|---|---|
| BB-01 | Login | Login valid | email + password benar | Masuk ke dashboard |  |  |
| BB-02 | Login | Login invalid | password salah | Pesan error login |  |  |
| BB-03 | Absensi Wajah | Register wajah | Frame wajah valid | Registrasi berhasil |  |  |
| BB-04 | Absensi Wajah | Check-in wajah | Frame sesuai user | Absensi berhasil + confidence |  |  |
| BB-05 | Absensi Wajah | Check-out tanpa check-in | action=checkout | Ditolak dengan pesan validasi |  |  |
| BB-06 | Jurnal | Tambah jurnal | data kegiatan lengkap | Data tersimpan |  |  |
| BB-07 | Penilaian | Input nilai | nilai 0-100 | Nilai tersimpan |  |  |
| BB-08 | Laporan | Export Excel | klik endpoint excel | File .xlsx terunduh |  |  |
| BB-09 | Laporan | Export PDF | klik endpoint pdf | File .pdf terunduh |  |  |

## B. UAT (User Acceptance Test)

### B1. Administrator
- Dashboard mudah dipahami.
- Data peserta/pembimbing/instansi mudah dikelola.
- Laporan PDF/Excel sesuai kebutuhan.

### B2. Pembimbing
- Dapat memantau absensi peserta.
- Dapat mengakses jurnal dan memberikan penilaian.

### B3. Peserta PKL
- Dapat melakukan absensi wajah dengan mudah.
- Dapat mengisi jurnal harian tanpa kesulitan.

## C. Kesimpulan UAT
- Diterima tanpa revisi / Diterima dengan revisi / Ditolak.
- Catatan perbaikan:
  1.
  2.
  3.

## D. Hasil Uji Akses Role (Validasi Otomatis)

Tanggal uji: 2026-07-30  
Environment: MySQL lokal (`absensi`) + session cookie login web

Ringkasan:
- Total skenario diuji: 30
- Lulus (PASS): 30
- Gagal (FAIL): 0

Rincian hasil penting:
- Login admin/pembimbing/peserta: PASS
- Akses `/dashboard` untuk semua role: PASS
- Akses `/participants`: admin + pembimbing PASS, peserta redirect ke `/dashboard` PASS
- Akses `/supervisors`: admin PASS, pembimbing + peserta redirect ke `/dashboard` PASS
- Akses `/institutions`: admin PASS, pembimbing + peserta redirect ke `/dashboard` PASS
- Akses `/attendance`, `/journal`, `/assessments` sesuai rule role: PASS
- API `POST /api/attendance/manual`: admin/pembimbing authorized path PASS, peserta `403 Forbidden` PASS
- API `GET /api/attendance/history`: seluruh role dapat akses data sesuai scope PASS
