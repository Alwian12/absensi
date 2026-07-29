from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Journal(Base):
    __tablename__ = "jurnal"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tanggal = Column(DateTime(timezone=True), server_default=func.now())
    kegiatan = Column(String(500), nullable=False)
    output = Column(String(500), nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    komentar = Column(String(500), nullable=True)

    user = relationship("User")
