from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Assessment(Base):
    __tablename__ = "penilaian"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    nilai = Column(Integer, nullable=False)
    catatan = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
