from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.journal import Journal

router = APIRouter(prefix="/journal", tags=["journal"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("")
def create_journal(user_id: int, kegiatan: str, output: str | None = None, db: Session = Depends(get_db)) -> dict[str, object]:
    journal = Journal(user_id=user_id, kegiatan=kegiatan, output=output or "")
    db.add(journal)
    db.commit()
    db.refresh(journal)
    return {"message": "Journal created", "journal_id": journal.id}


@router.get("")
def list_journal(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.query(Journal).all()
    return [{"id": row.id, "user_id": row.user_id, "kegiatan": row.kegiatan, "status": row.status} for row in rows]
