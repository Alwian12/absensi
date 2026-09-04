"""Activity log helper — records user actions for the timeline page."""
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog


def log_activity(db: Session, user_id: int, action: str, detail: str | None = None, ip: str | None = None) -> None:
    db.add(ActivityLog(user_id=user_id, action=action, detail=detail, ip=ip))
