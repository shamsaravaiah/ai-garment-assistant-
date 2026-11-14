from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def get_catalog_session() -> Session | None:
    """Optional Postgres session for product hydrate. None if not configured."""
    settings = get_settings()
    if not settings.catalog_db_enabled:
        return None
    catalog_engine = create_engine(settings.database_url, pool_pre_ping=True)
    return sessionmaker(bind=catalog_engine, autoflush=False, autocommit=False)()
