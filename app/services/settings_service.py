"""Read and write app settings from database."""
from datetime import time


def get_setting(db, key: str, default: str = "") -> str:
    from app.models.app_setting import AppSetting
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def set_setting(db, key: str, value: str) -> None:
    from app.models.app_setting import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
        return
    db.add(AppSetting(key=key, value=value))


def get_jam_masuk(db) -> time:
    raw = get_setting(db, "jam_masuk", "08:15")
    try:
        h, m = raw.split(":")
        return time(int(h), int(m))
    except Exception:
        return time(8, 15)


def get_jam_pulang(db) -> time:
    raw = get_setting(db, "jam_pulang", "16:00")
    try:
        h, m = raw.split(":")
        return time(int(h), int(m))
    except Exception:
        return time(16, 0)


def get_attendance_success_auto_hide_seconds(db) -> int:
    raw = get_setting(db, "attendance_success_auto_hide_seconds", "9")
    try:
        value = int(raw)
    except Exception:
        return 9
    return max(3, min(20, value))


def get_attendance_transition_style(db) -> str:
    raw = get_setting(db, "attendance_transition_style", "normal").strip().lower()
    if raw in {"fast", "normal", "slow"}:
        return raw
    return "normal"


def get_office_latitude(db) -> float | None:
    raw = get_setting(db, "office_latitude", "").strip()
    if not raw:
        return None
    try:
        lat = float(raw)
    except Exception:
        return None
    if lat < -90 or lat > 90:
        return None
    return lat


def get_office_longitude(db) -> float | None:
    raw = get_setting(db, "office_longitude", "").strip()
    if not raw:
        return None
    try:
        lng = float(raw)
    except Exception:
        return None
    if lng < -180 or lng > 180:
        return None
    return lng


def get_office_radius_m(db) -> int:
    raw = get_setting(db, "office_radius_m", "200")
    try:
        radius = int(raw)
    except Exception:
        return 200
    return max(20, min(5000, radius))


def get_office_grace_m(db) -> int:
    raw = get_setting(db, "office_grace_m", "15")
    try:
        grace = int(raw)
    except Exception:
        return 15
    return max(0, min(500, grace))


def get_office_max_accuracy_m(db) -> int:
    raw = get_setting(db, "office_max_accuracy_m", "80")
    try:
        accuracy = int(raw)
    except Exception:
        return 80
    return max(10, min(500, accuracy))


def get_office_geofence(db) -> tuple[float, float, int] | None:
    lat = get_office_latitude(db)
    lng = get_office_longitude(db)
    if lat is None or lng is None:
        return None
    return lat, lng, get_office_radius_m(db)
