from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Attendance(Base):
    __tablename__ = "absensi"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    attendance_date = Column(DateTime(timezone=True), server_default=func.now())
    check_in_time = Column(DateTime(timezone=True), nullable=True)
    check_out_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=False, default="hadir")
    confidence_score = Column(Float, nullable=True)
    alasan_pulang_cepat = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    distance_from_office_m = Column(Float, nullable=True)
    requires_location_review = Column(Boolean, nullable=False, default=False)
    location_review_reason = Column(String(30), nullable=True)
    location_review_status = Column(String(20), nullable=False, default="not_required")
    location_review_note = Column(String(300), nullable=True)
    location_reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    location_reviewed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
