from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Institution(Base):
    __tablename__ = "instansi"

    id = Column(Integer, primary_key=True, index=True)
    nama_instansi = Column(String(150), nullable=False)
    alamat = Column(String(250), nullable=True)
    kontak = Column(String(100), nullable=True)
    office_latitude = Column(Float, nullable=True)
    office_longitude = Column(Float, nullable=True)
    office_radius_m = Column(Integer, nullable=True)
    office_grace_m = Column(Integer, nullable=True)
    office_max_accuracy_m = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
