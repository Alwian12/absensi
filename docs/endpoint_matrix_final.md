# Endpoint Matrix Final

## Web Routes (Jinja2)
| Route | Method | Role | Keterangan |
|---|---|---|---|
| / | GET | Publik | Landing page |
| /login | GET/POST | Publik | Login web berbasis cookie |
| /register | GET/POST | Publik | Registrasi akun peserta |
| /dashboard | GET | Semua user login | Dashboard utama |
| /attendance | GET | Semua user login | Halaman absensi |
| /participants | GET/POST | admin, pembimbing | Manajemen peserta |
| /supervisors | GET/POST | admin | Manajemen pembimbing |
| /institutions | GET/POST | admin | Manajemen instansi |
| /journal | GET/POST | Semua user login | Jurnal kegiatan |
| /assessments | GET/POST | admin, pembimbing | Penilaian peserta |
| /logout | GET | Semua user login | Logout sesi |

## API Routes (FastAPI)
| Endpoint | Method | Auth | Role | Keterangan |
|---|---|---|---|---|
| /auth/login | POST | No | Publik | Login API (JWT) |
| /auth/register | POST | No | Publik | Registrasi API |
| /api/dashboard | GET | Yes | admin, pembimbing, peserta | Statistik ringkas |
| /api/journal | GET/POST | Yes | admin, pembimbing, peserta | Data jurnal |
| /api/attendance/checkin | POST | Yes | peserta | Check-in berbasis token |
| /api/attendance/history | GET | Yes | semua login | History absensi |
| /api/attendance/manual | POST | Yes | admin, pembimbing | Input manual absensi |
| /api/face/register | POST | Yes | semua login | Registrasi embedding wajah |
| /api/face/verify | POST | Yes | semua login | Verifikasi wajah check-in/out |
| /api/reports/attendance/excel | GET | Yes | admin | Export Excel absensi |
| /api/reports/attendance/pdf | GET | Yes | admin | Export PDF absensi |

## Catatan Integrasi Frontend
- Frontend JavaScript absensi ada di app/static/js/attendance.js.
- Frontend memanggil API via fetch ke endpoint /api/*.
- Kamera browser dipakai untuk capture frame saat register/verify wajah.
