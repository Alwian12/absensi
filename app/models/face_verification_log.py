from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class FaceVerificationLog(Base):
    __tablename__ = "face_verification_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(20), nullable=False, default="checkin")
    matched = Column(Boolean, nullable=False, default=False)
    attempt_blocked = Column(Boolean, nullable=False, default=False)
    similarity = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    engine = Column(String(100), nullable=True)
    message = Column(String(255), nullable=True)
    source_ip = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
