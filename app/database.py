from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        echo=settings.sql_echo,
    )
else:
    engine = create_engine(
        settings.database_url,
        echo=settings.sql_echo,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,   # reconnect if stale connection
        pool_recycle=3600,    # recycle connections every 1 hour
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
 