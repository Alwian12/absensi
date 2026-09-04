# Spesifikasi REST API (Backend Python - Frontend JavaScript)

Frontend JavaScript mengakses endpoint backend Python FastAPI melalui namespace `/api/*`.

## Auth API
- POST /auth/login
- POST /auth/register

## Face Recognition API
- POST /api/face/register
- POST /api/face/verify

## Attendance API
- POST /api/attendance/checkin
- GET /api/attendance/history
- POST /api/attendance/manual

## Dashboard API
- GET /api/dashboard

## Journal API
- GET /api/journal
- POST /api/journal

## Reports API
- GET /api/reports/attendance/excel
- GET /api/reports/attendance/pdf

## Catatan RBAC
- Route manajemen web (`/participants`, `/supervisors`, `/institutions`) dibatasi untuk role `admin` atau `pembimbing` sesuai modul.
- Endpoint laporan `/api/reports/*` hanya untuk role `admin`.
- Endpoint API dapat memakai cookie sesi web atau bearer token JWT.

## Web Routes (Jinja2 + JavaScript)
- GET /login
- GET /dashboard
- GET /attendance
- GET /participants
- GET /supervisors
- GET /institutions
- GET /journal
- GET /assessments
