"""Weekly recap & automatic-absence scheduler using APScheduler."""
from __future__ import annotations

import logging
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
from app.services.settings_service import get_jam_pulang, get_setting, set_setting

logger = logging.getLogger(__name__)


def apply_automatic_absence_for_date(db, target_date: date, now: datetime | None = None) -> int:
    """Create one alpa/izin record for active peserta without attendance after jam pulang.

    Returns the number of records created, or 0 when the job is skipped.

    Skip conditions:
    - ``target_date`` is in the future (relative to ``now``).
    - Current time is before ``jam_pulang`` (end-of-workday setting).
    - ``target_date`` falls on a weekend (Saturday=5, Sunday=6).
    """
    current_time = now or datetime.now()

    # Guard 1: don't process future dates
    if target_date > current_time.date():
        return 0

    # Guard 2: skip weekends — no work days, no absences
    if target_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        logger.debug("apply_automatic_absence_for_date: skipping weekend %s", target_date)
        return 0

    # Guard 3: wait until after jam pulang
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


# Key stored in AppSetting to track the last date the absence job ran.
_ABSENCE_JOB_LAST_RUN_KEY = "absence_job_last_run_date"


def run_automatic_absence_job() -> None:
    """Scheduled entry-point for the automatic absence job.

    Multi-worker safety: reads/writes ``absence_job_last_run_date`` in the
    database as a simple distributed lock.  If another worker already ran the
    job today, this worker exits immediately without duplicating records.
    """
    db = SessionLocal()
    try:
        today_str = date.today().isoformat()  # "YYYY-MM-DD"

        # --- distributed lock: skip if another worker already ran today ---
        last_run = get_setting(db, _ABSENCE_JOB_LAST_RUN_KEY, "")
        if last_run == today_str:
            logger.debug("run_automatic_absence_job: already ran today (%s), skipping.", today_str)
            return

        # Claim the slot before doing heavy work to reduce race window
        set_setting(db, _ABSENCE_JOB_LAST_RUN_KEY, today_str)
        db.commit()
        # -------------------------------------------------------------------

        created = apply_automatic_absence_for_date(db, datetime.now().date())
        if created:
            admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
            for admin in admins:
                push_notification(db, admin.id, f"Sistem membuat {created} status absensi otomatis setelah jam pulang.", "warning")
            db.commit()
            logger.info("run_automatic_absence_job: created %d absence record(s).", created)
    except Exception:
        logger.exception("run_automatic_absence_job: unexpected error")
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
    """Start the background scheduler.

    Automatic absence job:
        Runs daily at **16:30** via CronTrigger (after the default jam_pulang
        of 16:00).  The job itself re-checks the current time against the
        *actual* jam_pulang setting from the database, so changing the setting
        in the admin panel takes effect the next day without restarting the
        server.

    Multi-worker safety:
        Each uvicorn worker starts its own BackgroundScheduler.  The job uses
        a database-backed date flag (``absence_job_last_run_date`` in
        AppSetting) so only the first worker to claim the slot does real work.

    Weekly recap job:
        Runs every Monday at 07:00.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler()

    # Daily cron at 16:30 — safe margin after default jam_pulang (16:00).
    # The job body still checks jam_pulang dynamically, so it is correct even
    # when the admin changes the setting to a later time.
    _scheduler.add_job(
        run_automatic_absence_job,
        CronTrigger(hour=16, minute=30),
        id="automatic_absence",
        replace_existing=True,
    )

    # Every Monday at 07:00
    _scheduler.add_job(run_weekly_recap, CronTrigger(day_of_week="mon", hour=7, minute=0))
    _scheduler.start()
    logger.info("Scheduler started: automatic_absence=daily@16:30, weekly_recap=monday@07:00")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
