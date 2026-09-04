from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAuditLog


def log_admin_action(
    db: Session,
    admin_user_id: int,
    action: str,
    target_user_id: int | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    db.add(AdminAuditLog(
        admin_user_id=admin_user_id,
        action=action,
        target_user_id=target_user_id,
        detail=detail,
        ip=ip,
    ))
