from __future__ import annotations

from datetime import datetime, timedelta

from app.authentication.jwt_handler import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Assessment, Attendance, Institution, Journal, Participant, Supervisor, User


def _get_or_create_user(db, username: str, email: str, role: str, password: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user

    user = User(
        username=username,
        email=email,
        role=role,
        is_active=True,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.flush()
    return user


def seed_demo_data() -> None:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = _get_or_create_user(db, "admin.diskominfo", "admin@diskominfo.local", "admin", "Admin123!")
        supervisor_user = _get_or_create_user(
            db, "pembimbing.pkl", "pembimbing@diskominfo.local", "pembimbing", "Pembimbing123!"
        )
        participant_1 = _get_or_create_user(db, "peserta.satu", "peserta1@kampus.ac.id", "peserta", "Peserta123!")
        participant_2 = _get_or_create_user(db, "peserta.dua", "peserta2@kampus.ac.id", "peserta", "Peserta123!")

        instansi = db.query(Institution).filter(Institution.nama_instansi == "Diskominfo Kabupaten Batu Bara").first()
        if not instansi:
            instansi = Institution(
                nama_instansi="Diskominfo Kabupaten Batu Bara",
                alamat="Limapuluh, Kabupaten Batu Bara",
                kontak="(0622) 000000",
            )
            db.add(instansi)
            db.flush()

        supervisor = db.query(Supervisor).filter(Supervisor.user_id == supervisor_user.id).first()
        if not supervisor:
            supervisor = Supervisor(user_id=supervisor_user.id, nama_lengkap="Budi Santoso, S.Kom", bidang="Infrastruktur TI")
            db.add(supervisor)

        p1 = db.query(Participant).filter(Participant.user_id == participant_1.id).first()
        if not p1:
            p1 = Participant(
                user_id=participant_1.id,
                nama_lengkap="Andi Pratama",
                jurusan="Sistem Informasi",
                instansi=instansi.nama_instansi,
            )
            db.add(p1)

        p2 = db.query(Participant).filter(Participant.user_id == participant_2.id).first()
        if not p2:
            p2 = Participant(
                user_id=participant_2.id,
                nama_lengkap="Siti Rahma",
                jurusan="Teknik Informatika",
                instansi=instansi.nama_instansi,
            )
            db.add(p2)

        db.flush()

        today = datetime.now()
        for idx, user in enumerate([participant_1, participant_2], start=1):
            existing = db.query(Attendance).filter(Attendance.user_id == user.id).first()
            if existing:
                continue
            check_in = today - timedelta(hours=9, minutes=idx * 5)
            check_out = today - timedelta(hours=2, minutes=idx * 3)
            db.add(
                Attendance(
                    user_id=user.id,
                    check_in_time=check_in,
                    check_out_time=check_out,
                    status="hadir" if idx == 1 else "terlambat",
                    confidence_score=0.9 - (idx * 0.04),
                )
            )

        for idx, user in enumerate([participant_1, participant_2], start=1):
            existing_journal = db.query(Journal).filter(Journal.user_id == user.id).first()
            if existing_journal:
                continue
            db.add(
                Journal(
                    user_id=user.id,
                    kegiatan=f"Implementasi modul API ke-{idx}",
                    output="Endpoint berjalan dan tervalidasi",
                    status="approved" if idx == 1 else "pending",
                    komentar="Lanjutkan dengan dokumentasi pengujian.",
                )
            )

        existing_assessment = db.query(Assessment).filter(Assessment.user_id == participant_1.id).first()
        if not existing_assessment:
            db.add(
                Assessment(
                    user_id=participant_1.id,
                    nilai=88,
                    catatan="Aktif, disiplin, dan cepat beradaptasi.",
                )
            )

        db.commit()
        print("Seed demo data berhasil dibuat.")
        print("Akun admin: admin@diskominfo.local / Admin123!")
        print("Akun pembimbing: pembimbing@diskominfo.local / Pembimbing123!")
        print("Akun peserta: peserta1@kampus.ac.id / Peserta123!")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
