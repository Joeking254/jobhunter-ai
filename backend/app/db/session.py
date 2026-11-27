from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_recycle=1800,
    pool_timeout=30,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        try:
            yield session
            if session.in_transaction():
                session.commit()
        except Exception:
            session.rollback()
            raise


def build_session_factory(database_url: str):
    """Build an isolated session factory for tests and administrative jobs."""
    test_engine = create_engine(database_url, future=True)
    return test_engine, sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
