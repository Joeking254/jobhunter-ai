from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def import_models() -> None:
    """Import model modules so Alembic sees all mapped tables."""
    from app import models  # noqa: F401
