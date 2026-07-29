# Pengembangan Aplikasi Monitoring PKL Berbasis Web

## Judul Proyek
Pengembangan Aplikasi Monitoring PKL Berbasis Web dengan Fitur Absensi Verifikasi Wajah, Jurnal Kegiatan, dan Manajemen Data Pembimbing di Dinas Komunikasi dan Informatika Kabupaten Batu Bara.

## 1. Analisis Kebutuhan Sistem

### 1.1 Latar Belakang
Aplikasi monitoring PKL diperlukan untuk menggantikan proses manual yang sering kali memakan waktu, rentan kesalahan, dan sulit dipantau secara real-time. Sistem ini dirancang untuk membantu peserta PKL, pembimbing, dan administrator dalam mengelola kegiatan PKL secara digital, aman, dan terstruktur.

### 1.2 Tujuan Sistem
- Memudahkan absensi peserta PKL secara digital.
- Meningkatkan akurasi verifikasi kehadiran melalui wajah.
- Menyediakan ruang jurnal kegiatan yang terintegrasi.
- Mempermudah pembimbing melakukan monitoring, penilaian, dan pemberian komentar.
- Menyediakan dashboard statistik untuk administrator.

### 1.3 Ruang Lingkup
- Pengelolaan akun pengguna.
- Pengelolaan data peserta, pembimbing, instansi, dan periode.
- Absensi masuk dan pulang berbasis verifikasi wajah.
- Pengisian jurnal kegiatan dan dokumentasi.
- Monitoring penilaian dan progres peserta.
- Export laporan PDF dan Excel.

### 1.4 Kebutuhan Fungsional
- Administrator dapat login, mengelola data, memantau absensi, jurnal, penilaian, dan export laporan.
- Peserta PKL dapat login, mendaftar wajah, melakukan absensi, mengisi jurnal, mengunggah dokumentasi, dan melihat komentar pembimbing.
- Pembimbing dapat melihat peserta, memantau absensi, menyetujui jurnal, memberi komentar, dan menilai peserta.

### 1.5 Kebutuhan Non-Fungsional
- Keamanan: JWT, hashing password, RBAC, logging.
- Kinerja: respons API cepat untuk operasi harian.
- Reliabilitas: data harus tersimpan dengan aman dan konsisten.
- Kemudahan pemeliharaan: arsitektur modular dan terstruktur.

---

## 2. Flowchart Proses Utama

### 2.1 Flowchart Login dan Autentikasi
```mermaid
flowchart TD
    A[Pengguna membuka halaman login] --> B[Input username/email dan password]
    B --> C[Validasi input]
    C --> D[Check akun di database]
    D --> E{Akun valid?}
    E -- Ya --> F[Generate JWT]
    F --> G[Redirect ke dashboard sesuai role]
    E -- Tidak --> H[Tampilkan error login]
    H --> B
```

### 2.2 Flowchart Absensi Verifikasi Wajah
```mermaid
flowchart TD
    A[Peserta membuka halaman absensi] --> B[Aktifkan kamera]
    B --> C[Deteksi wajah dari frame]
    C --> D[Ekstrak embedding wajah]
    D --> E[Bandingkan dengan wajah terdaftar]
    E --> F{Kecocokan memenuhi threshold?}
    F -- Ya --> G[Simpan absensi masuk/pulang]
    G --> H[Perbarui status kehadiran dan confidence score]
    F -- Tidak --> I[Tampilkan pesan verifikasi gagal]
    I --> B
```

### 2.3 Flowchart Pengisian Jurnal
```mermaid
flowchart TD
    A[Peserta membuka form jurnal] --> B[Isi kegiatan, output, dan dokumentasi]
    B --> C[Validasi input]
    C --> D[Simpan jurnal ke database]
    D --> E[Status draft atau menunggu persetujuan]
    E --> F[Pembimbing meninjau dan memberi komentar]
    F --> G[Status disetujui ditolak]
```

---

## 3. Use Case Diagram
```mermaid
flowchart LR
    Admin[Administrator] --> UC1[Login]
    Admin --> UC2[Kelola peserta]
    Admin --> UC3[Kelola pembimbing]
    Admin --> UC4[Kelola instansi]
    Admin --> UC5[Kelola periode]
    Admin --> UC6[Monitoring absensi]
    Admin --> UC7[Monitoring jurnal]
    Admin --> UC8[Export laporan]

    Peserta[Peserta PKL] --> UC9[Login]
    Peserta --> UC10[Registrasi wajah]
    Peserta --> UC11[Absensi]
    Peserta --> UC12[Isi jurnal]
    Peserta --> UC13[Upload dokumentasi]

    Pembimbing[Pembimbing] --> UC14[Login]
    Pembimbing --> UC15[Monitoring peserta]
    Pembimbing --> UC16[Persetujuan jurnal]
    Pembimbing --> UC17[Memberi komentar]
    Pembimbing --> UC18[Penilaian]
```

---

## 4. Activity Diagram
```mermaid
flowchart TD
    A[Mulai] --> B[Login]
    B --> C{Role?}
    C -- Admin --> D[Dashboard admin]
    C -- Peserta --> E[Dashboard peserta]
    C -- Pembimbing --> F[Dashboard pembimbing]
    D --> G[Kelola data dan lihat statistik]
    E --> H[Absensi, jurnal, lihat progres]
    F --> I[Monitoring, penilaian, komentar]
    G --> J[Selesai]
    H --> J
    I --> J
```

---

## 5. Sequence Diagram
```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant API as FastAPI
    participant DB as MySQL
    participant AI as Face Service

    U->>FE: Buka halaman absensi
    FE->>API: POST /attendance/checkin
    API->>AI: Proses frame wajah
    AI-->>API: Embedding + confidence
    API->>DB: Simpan absensi dan metadata
    DB-->>API: Konfirmasi penyimpanan
    API-->>FE: Response sukses/gagal
    FE-->>U: Tampilkan hasil absensi
```

---

## 6. ERD (Entity Relationship Diagram)
```mermaid
erDiagram
    users ||--o{ absensi : has
    users ||--o{ jurnal : writes
    users ||--o{ log_aktivitas : triggers
    users ||--o{ notifikasi : receives
    users ||--o{ penilaian : receives
    peserta ||--|| users : maps
    pembimbing ||--|| users : maps
    instansi ||--o{ peserta : hosts
    periode ||--o{ peserta : includes
    periode ||--o{ absensi : covers
    peserta ||--o{ absensi : has
    peserta ||--o{ jurnal : creates
    pembimbing ||--o{ penilaian : gives
    pembimbing ||--o{ jurnal : reviews

    users {
        int id PK
        string username
        string email
        string password_hash
        string role
        boolean is_active
        datetime created_at
    }

    peserta {
        int id PK
        int user_id FK
        int instansi_id FK
        int periode_id FK
        string nama_lengkap
        string nim_nisn
        string jurusan
        string no_hp
        datetime created_at
    }

    pembimbing {
        int id PK
        int user_id FK
        string nama_lengkap
        string nip
        string bidang
        string no_hp
    }

    instansi {
        int id PK
        string nama_instansi
        string alamat
        string kontak
    }

    periode {
        int id PK
        string nama_periode
        date tanggal_mulai
        date tanggal_selesai
        string status
    }

    absensi {
        int id PK
        int user_id FK
        int peserta_id FK
        int periode_id FK
        datetime check_in_time
        datetime check_out_time
        string status
        float confidence_score
        string location_info
        string device_info
    }

    jurnal {
        int id PK
        int peserta_id FK
        int pembimbing_id FK
        date tanggal
        string kegiatan
        string output
        string dokumentasi_path
        string status
        string komentar
    }

    penilaian {
        int id PK
        int peserta_id FK
        int pembimbing_id FK
        int nilai_akhir
        string catatan
        date tanggal_penilaian
    }

    notifikasi {
        int id PK
        int user_id FK
        string judul
        string isi
        boolean is_read
        datetime created_at
    }

    log_aktivitas {
        int id PK
        int user_id FK
        string aksi
        string detail
        datetime created_at
    }
```

---

## 7. Class Diagram
```mermaid
classDiagram
    class User {
        +int id
        +string username
        +string email
        +string password_hash
        +string role
        +bool is_active
        +login()
        +logout()
    }

    class Participant {
        +int id
        +int user_id
        +string nama_lengkap
        +string jurusan
        +registerFace()
        +submitJournal()
    }

    class Supervisor {
        +int id
        +int user_id
        +string nama_lengkap
        +string bidang
        +reviewJournal()
        +submitAssessment()
    }

    class Attendance {
        +int id
        +int user_id
        +datetime check_in_time
        +datetime check_out_time
        +string status
        +float confidence_score
        +createAttendance()
        +updateAttendance()
    }

    class Journal {
        +int id
        +int participant_id
        +string kegiatan
        +string status
        +string komentar
        +createJournal()
        +updateJournal()
    }

    class FaceRecognitionService {
        +registerEmbedding()
        +verifyEmbedding()
    }

    User <|-- Participant
    User <|-- Supervisor
    Participant --> Attendance
    Participant --> Journal
    Supervisor --> Journal
    FaceRecognitionService --> Attendance
```

---

## 8. Struktur Database Beserta Relasi

### 8.1 Tabel Utama
| Tabel | Fungsi | Keterangan |
|---|---|---|
| users | Akun login | Menyimpan identitas akun dan role |
| peserta | Data peserta PKL | Berelasi ke users dan instansi/periode |
| pembimbing | Data pembimbing | Berelasi ke users |
| instansi | Data instansi tempat PKL | Menandai lokasi serta organisasi |
| periode | Periode pelaksanaan PKL | Menentukan rentang waktu PKL |
| absensi | Data kehadiran | Menyimpan status masuk dan pulang |
| jurnal | Catatan kegiatan harian | Disetujui atau ditolak pembimbing |
| penilaian | Penilaian akhir atau berkala | Diberikan oleh pembimbing |
| notifikasi | Pemberitahuan sistem | Dapat ditampilkan ke pengguna |
| log_aktivitas | Riwayat aktivitas | Menyimpan log penting pengguna |

### 8.2 Relasi Inti
- users 1-to-1 peserta
- users 1-to-1 pembimbing
- instansi 1-to-many peserta
- periode 1-to-many peserta
- users 1-to-many absensi
- peserta 1-to-many absensi
- peserta 1-to-many jurnal
- pembimbing 1-to-many jurnal
- peserta 1-to-many penilaian
- pembimbing 1-to-many penilaian

### 8.3 Constraint yang Direkomendasikan
- `NOT NULL` pada field kunci penting.
- `UNIQUE` pada username/email.
- `CHECK` untuk status absensi (`hadir`, `terlambat`, `izin`, `alpha`).
- `FOREIGN KEY` untuk menjaga integritas relasi.

---

## 9. Struktur Folder Proyek
```text
absensi/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── routers/
│   ├── services/
│   ├── repositories/
│   ├── middleware/
│   ├── authentication/
│   ├── ai/
│   ├── utils/
│   ├── static/
│   ├── templates/
│   └── uploads/
├── migrations/
├── tests/
├── requirements.txt
├── .env.example
├── README.md
└── docs/
```

---

## 10. Desain REST API

### 10.1 Autentikasi
| Method | Endpoint | Deskripsi |
|---|---|---|
| POST | /login | Login pengguna |
| POST | /logout | Logout sesi |
| POST | /register | Registrasi akun baru |

### 10.2 Face Recognition
| Method | Endpoint | Deskripsi |
|---|---|---|
| POST | /face/register | Daftarkan embedding wajah |
| POST | /face/verify | Verifikasi wajah saat absensi |

### 10.3 Attendance
| Method | Endpoint | Deskripsi |
|---|---|---|
| POST | /attendance/checkin | Absensi masuk |
| POST | /attendance/checkout | Absensi pulang |
| GET | /attendance/history | Riwayat absensi |

### 10.4 Journal
| Method | Endpoint | Deskripsi |
|---|---|---|
| POST | /journal | Tambah jurnal |
| PUT | /journal/{id} | Edit jurnal |
| DELETE | /journal/{id} | Hapus jurnal |
| GET | /journal | Daftar jurnal |

### 10.5 Management
| Method | Endpoint | Deskripsi |
|---|---|---|
| GET | /users | Daftar pengguna |
| GET | /participants | Daftar peserta |
| GET | /supervisors | Daftar pembimbing |
| GET | /dashboard | Statistik dashboard |
| GET | /reports | Rekap laporan |

---

## 11. Desain Antarmuka (UI/UX)

### 11.1 Prinsip Desain
- Modern, bersih, dan formal.
- Sesuai untuk aplikasi pemerintahan.
- Navigasi sederhana dengan warna tema biru dan putih.
- Responsif untuk desktop dan tablet.

### 11.2 Halaman Utama
- Halaman login.
- Dashboard berdasarkan role.
- Halaman daftar peserta.
- Halaman absensi wajah.
- Halaman jurnal harian.
- Halaman penilaian.
- Halaman laporan PDF/Excel.

### 11.3 UX Recommendation
- Pengguna dapat melihat status absensi dengan cepat.
- Tombol aksi harus jelas dan konsisten.
- Pemberitahuan sukses/gagal ditampilkan melalui toast atau alert.
- Form disusun singkat dan mudah dipahami.

---

## 12. Arsitektur Sistem
```mermaid
flowchart TB
    U[Client Browser] --> FE[Frontend Jinja2 + Bootstrap + JS]
    FE --> API[FastAPI REST API]
    API --> AUTH[JWT Auth + RBAC]
    API --> ORM[SQLAlchemy ORM]
    ORM --> DB[(MySQL)]
    API --> AI[Face Recognition Service]
    AI --> CV[OpenCV + InsightFace + NumPy]
    API --> FILE[Upload & Report Service]
    FILE --> STORAGE[uploads / generated reports]
```

### 12.1 Komponen Utama
- Frontend: HTML, CSS, Bootstrap, JavaScript, Jinja2.
- Backend: FastAPI, SQLAlchemy, Pydantic, JWT.
- AI: OpenCV, InsightFace, NumPy.
- Database: MySQL.
- Laporan: ReportLab, Pandas, OpenPyXL.

---

## 13. Penjelasan Backend Python
Backend dikembangkan menggunakan FastAPI karena performansi tinggi, dokumentasi otomatis, dan dukungan dependency injection yang baik. Struktur aplikasi dibagi menjadi modul yang jelas:
- `routers` untuk endpoint API.
- `services` untuk logika bisnis.
- `repositories` untuk akses data.
- `schemas` untuk validasi request/response.
- `models` untuk representasi tabel database.
- `authentication` untuk JWT dan RBAC.
- `ai` untuk transaksi verifikasi wajah.

### 13.1 Kelebihan FastAPI
- Dokumentasi otomatis via Swagger UI.
- Validasi data berbasis Pydantic.
- Skalabel untuk aplikasi pemerintahan.
- Cocok untuk integrasi AI dan layanan laporan.

---

## 14. Alur Kerja AI Verifikasi Wajah
1. Kamera aktif saat halaman absensi dibuka.
2. OpenCV mengambil frame video.
3. Wajah dideteksi dari frame.
4. InsightFace menghasilkan embedding wajah.
5. Embedding dibandingkan dengan embedding wajah yang tersimpan.
6. Jika similarity melebihi threshold, absensi berhasil.
7. Sistem menyimpan metadata absensi, confidence score, status, dan waktu.
8. Foto wajah mentah tidak disimpan secara permanen, hanya metadata verifikasi.

### 14.1 Rekomendasi Threshold
- Threshold awal: 0.70 - 0.80 tergantung data latih dan kualitas kamera.
- Jika terlalu tinggi, false negative akan meningkat.
- Jika terlalu rendah, false positive akan meningkat.

---

## 15. Alur Autentikasi JWT
```mermaid
sequenceDiagram
    participant C as Client
    participant A as FastAPI Auth
    participant DB as MySQL

    C->>A: POST /login dengan email/password
    A->>DB: Cek akun dan password hash
    DB-->>A: Data akun valid
    A-->>C: Return access_token + refresh_token
    C->>A: Request dengan Authorization: Bearer token
    A-->>C: Izinkan/ Tolak berdasarkan role dan token
```

### 15.1 Flow JWT
- Login berhasil menghasilkan access token.
- Token berisi claim user_id, role, exp.
- Middleware memeriksa token sebelum mengakses route.
- Role-based access control membatasi fitur sesuai peran.

---

## 16. Rencana Implementasi Selama 2 Bulan

### Minggu 1-2: Persiapan dan Analisis
- Menentukan kebutuhan sistem.
- Membuat desain database.
- Menyiapkan lingkungan Python, FastAPI, MySQL.
- Membuat struktur folder proyek.

### Minggu 3-4: Modul Dasar
- Implementasi auth, role, CRUD user.
- Implementasi modul peserta, pembimbing, instansi, periode.
- Membuat dashboard dasar.

### Minggu 5-6: Absensi dan AI
- Integrasi OpenCV dan InsightFace.
- Membuat endpoint absensi.
- Menyimpan metadata verification hasil.

### Minggu 7: Jurnal, Penilaian, dan Notifikasi
- Pengisian jurnal.
- Persetujuan jurnal oleh pembimbing.
- Penilaian dan komentar.

### Minggu 8: Laporan dan Pengujian
- Export PDF dan Excel.
- Pengujian black box dan UAT.
- Perbaikan bug dan dokumentasi akhir.

---

## 17. Daftar Pengujian Sistem

### 17.1 Black Box Testing
- Login berhasil dan gagal.
- Absensi wajah berhasil dan gagal.
- Pengisian jurnal berhasil dan ditolak.
- Admin dapat mengelola data peserta dan pembimbing.
- Export laporan PDF/Excel berjalan.

### 17.2 User Acceptance Testing (UAT)
- Administrator menilai kemudahan dashboard.
- Pembimbing menilai kelengkapan monitoring.
- Peserta menilai kemudahan absensi dan jurnal.
- Sistem dinilai sesuai kebutuhan instansi.

---

## 18. Saran Pengembangan Sistem di Masa Depan
- Integrasi dengan sistem absensi fingerprint atau RFID.
- Penerapan deteksi lokasi GPS yang lebih presisi.
- Penggunaan model AI yang lebih akurat untuk variasi pencahayaan.
- Notifikasi real-time via email atau WhatsApp.
- Penyediaan mobile app untuk pengguna.
- Integrasi dengan sistem kepegawaian atau SAPD instansi.

---

## 19. Kesimpulan
Sistem monitoring PKL berbasis web ini dirancang agar realistis, modern, dan mampu dikembangkan oleh satu mahasiswa PKL dalam kurun waktu sekitar dua bulan. Dengan pendekatan modular, backend Python FastAPI, database MySQL, dan AI verifikasi wajah berbasis InsightFace, aplikasi ini cukup layak dijadikan solusi digital untuk mendukung kegiatan PKL di lingkungan pemerintahan.
