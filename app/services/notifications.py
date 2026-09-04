from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User


def push_notification(db: Session, user_id: int, message: str, type: str = "info") -> None:
    db.add(Notification(user_id=user_id, message=message, type=type))


def push_to_role(db: Session, role: str, message: str, type: str = "info") -> None:
    users = db.query(User).filter(User.role == role, User.is_active == True).all()
    for user in users:
        db.add(Notification(user_id=user.id, message=message, type=type))
