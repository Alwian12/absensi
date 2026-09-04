"""Weekly recap scheduler using APScheduler."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.models.attendance import Attendance
from app.models.leave_request import LeaveRequest
from app.models.journal import Journal
from app.models.supervisor import Supervisor
from app.models.user import User
from app.services.email import send_weekly_report
from app.services.notifications import push_notification
from app.services.settings_service import get_jam_pulang


def apply_automatic_absence_for_date(db, target_date: date, now: datetime | None = None) -> int:
    """Create one alpa/izin record for active peserta without attendance after jam pulang."""
    current_time = now or datetime.now()
    if target_date > current_time.date():
        return 0
    if current_time.time() < get_jam_pulang(db):
        return 0

    peserta_list = db.query(User).filter(User.role == "peserta", User.is_active == True).all()
    created = 0
    for peserta in peserta_list:
        existing = (
            db.query(Attendance)
            .filter(Attendance.user_id == peserta.id)
            .filter(Attendance.attendance_date >= datetime.combine(target_date, datetime.min.time()))
            .filter(Attendance.attendance_date < datetime.combine(target_date + timedelta(days=1), datetime.min.time()))
            .first()
        )
        if existing:
            continue

        approved_leave = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.user_id == peserta.id)
            .filter(LeaveRequest.status.in_(["approved", "disetujui"]))
            .filter(LeaveRequest.tanggal >= datetime.combine(target_date, datetime.min.time()))
            .filter(LeaveRequest.tanggal < datetime.combine(target_date + timedelta(days=1), datetime.min.time()))
            .first()
        )
        leave_status = approved_leave.jenis if approved_leave and approved_leave.jenis in {"izin", "sakit"} else "izin"
        db.add(
            Attendance(
                user_id=peserta.id,
                attendance_date=datetime.combine(target_date, datetime.min.time()),
                status=leave_status if approved_leave else "alpa",
            )
        )
        created += 1

    if created:
        db.commit()
    return created


def run_automatic_absence_job() -> None:
    db = SessionLocal()
    try:
        created = apply_automatic_absence_for_date(db, datetime.now().date())
        if created:
            admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
            for admin in admins:
                push_notification(db, admin.id, f"Sistem membuat {created} status absensi otomatis setelah jam pulang.", "warning")
            db.commit()
    finally:
        db.close()


def _build_weekly_html(week_start: datetime, week_end: datetime, db) -> tuple[str, str]:
    label = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"

    peserta_list = db.query(User).filter(User.role == "peserta", User.is_active == True).all()
    rows = ""
    for p in peserta_list:
        att_count = db.query(Attendance).filter(
            Attendance.user_id == p.id,
            Attendance.attendance_date >= week_start,
            Attendance.attendance_date <= week_end,
        ).count()
        journal_count = db.query(Journal).filter(
            Journal.user_id == p.id,
            Journal.tanggal >= week_start,
            Journal.tanggal <= week_end,
        ).count()
        rows += f"<tr><td>{p.username}</td><td>{att_count}</td><td>{journal_count}</td></tr>"

    html = f"""
    <h2>Rekap Mingguan PKL — {label}</h2>
    <table border='1' cellpadding='6' style='border-collapse:collapse;font-family:sans-serif'>
      <thead style='background:#eef2ff'>
        <tr><th>Peserta</th><th>Absensi</th><th>Jurnal</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <p style='color:#64748b;font-size:12px'>Dikirim otomatis oleh Sistem Monitoring PKL.</p>
    """
    return html, label


def run_weekly_recap() -> None:
    db = SessionLocal()
    try:
        now = datetime.now()
        week_end = now - timedelta(days=1)
        week_start = week_end - timedelta(days=6)

        html, label = _build_weekly_html(week_start, week_end, db)

        supervisors = db.query(Supervisor).all()
        for sv in supervisors:
            user = sv.user
            if user and user.email:
                send_weekly_report(user.email, html, label)
            if user:
                push_notification(db, user.id, f"Rekap mingguan {label} tersedia.", "info")

        admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
        for admin in admins:
            if admin.email:
                send_weekly_report(admin.email, html, label)
            push_notification(db, admin.id, f"Rekap mingguan {label} tersedia.", "info")

        db.commit()
    finally:
        db.close()


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(run_automatic_absence_job, "interval", minutes=1, id="automatic_absence", replace_existing=True)
    # Every Monday at 07:00
    _scheduler.add_job(run_weekly_recap, CronTrigger(day_of_week="mon", hour=7, minute=0))
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
