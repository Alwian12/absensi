from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.authentication.jwt_handler import verify_token
from app.database import get_db
from app.models.journal import Journal
from app.models.user import User
from app.security.session import require_user

router = APIRouter(prefix="/api/journal", tags=["journal"])


def get_request_user(request: Request, db: Session, authorization: str | None = Header(default=None)) -> User:
    return require_user(request, db, authorization)


@router.post("")
def create_journal(
    request: Request,
    user_id: int,
    kegiatan: str,
    output: str | None = None,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    requester = get_request_user(request, db, authorization)
    target_user_id = user_id

    if requester.role not in {"admin", "pembimbing"}:
        target_user_id = requester.id

    user = db.query(User).filter(User.id == target_user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    journal = Journal(user_id=target_user_id, kegiatan=kegiatan, output=output or "")
    db.add(journal)
    db.commit()
    db.refresh(journal)
    return {"message": "Journal created", "journal_id": journal.id}


@router.get("")
def list_journal(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    requester = get_request_user(request, db, authorization)

    query = db.query(Journal)
    if requester.role not in {"admin", "pembimbing"}:
        query = query.filter(Journal.user_id == requester.id)

    rows = query.order_by(Journal.id.desc()).all()
    return [{"id": row.id, "user_id": row.user_id, "kegiatan": row.kegiatan, "status": row.status} for row in rows]
