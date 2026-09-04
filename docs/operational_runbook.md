# Operational Runbook (Production Readiness)

## 1. Environment Profile

Gunakan profile produksi berikut sebagai baseline:
- Copy `.env.production.example` ke `.env` pada server target.
- Pastikan nilai berikut sesuai lingkungan produksi:
  - `DATABASE_URL`
  - `JWT_SECRET_KEY`
  - `COOKIE_SECURE=true` (wajib jika HTTPS)

## 2. Startup Service

Perintah jalankan aplikasi:

```powershell
c:/laragon/www/absensi/.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

## 3. Backup Database

Backup manual:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup_mysql.ps1 -Database absensi -User root -OutputDir backups
```

Output backup akan berada di folder `backups/` dengan format nama:
- `absensi-YYYYMMDD-HHMMSS.sql`

## 4. Restore Database

Restore dari file backup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\restore_mysql.ps1 -File .\backups\absensi-YYYYMMDD-HHMMSS.sql -User root
```

## 5. Security Baseline

- Public register API hanya dapat membuat role `peserta`.
- API jurnal membutuhkan autentikasi (Bearer token atau session cookie).
- Session cookie mengikuti setting environment:
  - `COOKIE_SECURE`
  - `COOKIE_SAMESITE`
- Nonaktifkan SQL verbose log di produksi (`SQL_ECHO=false`).
- Embedding wajah disimpan dalam format terenkripsi (bukan plain JSON).
- Audit log verifikasi wajah tersimpan di tabel `face_verification_logs`.
- Proteksi brute-force verifikasi wajah aktif:
  - `FACE_MAX_FAILED_ATTEMPTS`
  - `FACE_LOCK_MINUTES`

## 6. Final Smoke Test

Lakukan cek login dan halaman inti untuk role:
- Admin
- Pembimbing
- Peserta

Halaman minimum:
- `/dashboard`
- `/attendance`
- `/journal`
- `/assessments`

## 7. Known Pending Item

- Uji kamera nyata registrasi wajah sampai check-out tetap perlu dilakukan di perangkat demo/laptop target karena bergantung hardware kamera dan pencahayaan.
