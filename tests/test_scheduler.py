"""Tests for app/services/scheduler.py — Opsi C regression suite."""
from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import MagicMock, patch

import pytest

from app.services.scheduler import (
    _ABSENCE_JOB_LAST_RUN_KEY,
    apply_automatic_absence_for_date,
    run_automatic_absence_job,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_db(
    *,
    peserta_list=None,
    existing_attendance=None,
    approved_leave=None,
    jam_pulang: time = time(16, 0),
    last_run_date: str = "",
):
    """Return a lightweight mock db session."""
    db = MagicMock()

    # get_jam_pulang reads from db via get_setting → we patch at module level instead.
    # existing_attendance / approved_leave are returned by .first()
    # peserta_list is returned by .all()

    # Build a minimal query chain that routes based on the model queried.
    def _query_side_effect(model):
        q = MagicMock()
        # Default: filter returns self, first returns None, all returns []
        q.filter.return_value = q
        q.first.return_value = None
        q.all.return_value = []

        from app.models.user import User
        from app.models.attendance import Attendance
        from app.models.leave_request import LeaveRequest
        from app.models.app_setting import AppSetting

        if model is User:
            q.all.return_value = peserta_list or []
        elif model is Attendance:
            q.first.return_value = existing_attendance
        elif model is LeaveRequest:
            q.first.return_value = approved_leave
        elif model is AppSetting:
            setting_row = MagicMock()
            setting_row.value = last_run_date
            q.first.return_value = setting_row if last_run_date else None

        return q

    db.query.side_effect = _query_side_effect
    return db


def _make_peserta(user_id: int = 1, username: str = "peserta1"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.role = "peserta"
    u.is_active = True
    return u


# ──────────────────────────────────────────────────────────────────────────────
# apply_automatic_absence_for_date — guard tests
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyAutomaticAbsenceGuards:
    """apply_automatic_absence_for_date must return 0 without side-effects for skipped cases."""

    def test_skips_future_date(self):
        """target_date in the future → return 0."""
        db = _make_db()
        future = date.today()
        # Pass now as yesterday so future > now.date()
        yesterday_noon = datetime.combine(date.today(), time(12, 0)) \
            .replace(year=date.today().year - 1)  # safely in the past
        # Simpler: use target_date = tomorrow
        tomorrow = date(date.today().year + 1, 1, 1)
        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, tomorrow, now=datetime.now())
        assert result == 0
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_skips_saturday(self):
        """Saturday (weekday=5) → return 0."""
        # Find the most recent Saturday
        today = date.today()
        days_since_saturday = (today.weekday() - 5) % 7
        saturday = today if today.weekday() == 5 else \
            today.replace(day=today.day - days_since_saturday) if days_since_saturday <= today.day - 1 \
            else date(2026, 11, 1)  # 2026-11-01 is a Sunday; use known Saturday
        # Use a known Saturday: 2026-10-31
        saturday = date(2026, 10, 31)  # Saturday
        assert saturday.weekday() == 5, f"Expected Saturday, got weekday {saturday.weekday()}"

        db = _make_db(peserta_list=[_make_peserta()])
        now = datetime(2026, 10, 31, 17, 0, 0)  # after jam_pulang
        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, saturday, now=now)
        assert result == 0
        db.add.assert_not_called()

    def test_skips_sunday(self):
        """Sunday (weekday=6) → return 0."""
        sunday = date(2026, 11, 1)  # 2026-11-01 is a Sunday
        assert sunday.weekday() == 6, f"Expected Sunday, got weekday {sunday.weekday()}"

        db = _make_db(peserta_list=[_make_peserta()])
        now = datetime(2026, 11, 1, 17, 0, 0)
        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, sunday, now=now)
        assert result == 0
        db.add.assert_not_called()

    def test_skips_before_jam_pulang(self):
        """Weekday but before jam_pulang → return 0."""
        monday = date(2026, 10, 26)  # known Monday
        assert monday.weekday() == 0

        db = _make_db(peserta_list=[_make_peserta()])
        now = datetime(2026, 10, 26, 15, 59, 0)  # 1 minute before 16:00
        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, monday, now=now)
        assert result == 0
        db.add.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# apply_automatic_absence_for_date — happy path
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyAutomaticAbsenceHappyPath:
    """apply_automatic_absence_for_date must create records on valid weekday after jam_pulang."""

    def test_creates_alpa_for_missing_student(self):
        """Weekday, after jam_pulang, student has no attendance → creates alpa."""
        monday = date(2026, 10, 26)
        assert monday.weekday() == 0  # Monday

        peserta = _make_peserta(user_id=10)
        db = _make_db(peserta_list=[peserta], existing_attendance=None, approved_leave=None)
        now = datetime(2026, 10, 26, 17, 0, 0)

        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, monday, now=now)

        assert result == 1
        db.add.assert_called_once()
        db.commit.assert_called_once()
        added_record = db.add.call_args[0][0]
        assert added_record.status == "alpa"
        assert added_record.user_id == 10

    def test_skips_student_with_existing_attendance(self):
        """Student already has an attendance record for the day → not duplicated."""
        monday = date(2026, 10, 26)
        peserta = _make_peserta(user_id=11)
        existing = MagicMock()  # any truthy value = existing record
        db = _make_db(peserta_list=[peserta], existing_attendance=existing)
        now = datetime(2026, 10, 26, 17, 0, 0)

        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, monday, now=now)

        assert result == 0
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_creates_izin_for_student_with_approved_leave(self):
        """Student has an approved leave request → creates izin (not alpa)."""
        monday = date(2026, 10, 26)
        peserta = _make_peserta(user_id=12)

        leave = MagicMock()
        leave.jenis = "izin"

        db = _make_db(peserta_list=[peserta], existing_attendance=None, approved_leave=leave)
        now = datetime(2026, 10, 26, 17, 0, 0)

        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, monday, now=now)

        assert result == 1
        added_record = db.add.call_args[0][0]
        assert added_record.status == "izin"

    def test_creates_sakit_for_student_with_approved_sakit_leave(self):
        """Student has an approved sakit leave → creates sakit record."""
        monday = date(2026, 10, 26)
        peserta = _make_peserta(user_id=13)

        leave = MagicMock()
        leave.jenis = "sakit"

        db = _make_db(peserta_list=[peserta], existing_attendance=None, approved_leave=leave)
        now = datetime(2026, 10, 26, 17, 0, 0)

        with patch("app.services.scheduler.get_jam_pulang", return_value=time(16, 0)):
            result = apply_automatic_absence_for_date(db, monday, now=now)

        assert result == 1
        added_record = db.add.call_args[0][0]
        assert added_record.status == "sakit"


# ──────────────────────────────────────────────────────────────────────────────
# run_automatic_absence_job — multi-worker lock
# ──────────────────────────────────────────────────────────────────────────────

class TestRunAutomaticAbsenceJobLock:
    """run_automatic_absence_job must use DB-backed date lock to prevent multi-worker collision."""

    def test_skips_if_already_ran_today(self):
        """If absence_job_last_run_date == today, job must exit without creating records."""
        today_str = date.today().isoformat()

        with patch("app.services.scheduler.SessionLocal") as mock_sl, \
             patch("app.services.scheduler.get_setting", return_value=today_str), \
             patch("app.services.scheduler.set_setting") as mock_set, \
             patch("app.services.scheduler.apply_automatic_absence_for_date") as mock_apply:

            mock_sl.return_value = MagicMock()
            run_automatic_absence_job()

            mock_apply.assert_not_called()
            mock_set.assert_not_called()

    def test_runs_and_claims_lock_when_not_yet_run(self):
        """If absence_job_last_run_date != today, job must claim lock and run apply_..."""
        today_str = date.today().isoformat()

        with patch("app.services.scheduler.SessionLocal") as mock_sl, \
             patch("app.services.scheduler.get_setting", return_value="2000-01-01"), \
             patch("app.services.scheduler.set_setting") as mock_set, \
             patch("app.services.scheduler.apply_automatic_absence_for_date", return_value=0) as mock_apply:

            db_mock = MagicMock()
            mock_sl.return_value = db_mock
            run_automatic_absence_job()

            mock_set.assert_called_once_with(db_mock, _ABSENCE_JOB_LAST_RUN_KEY, today_str)
            mock_apply.assert_called_once()

