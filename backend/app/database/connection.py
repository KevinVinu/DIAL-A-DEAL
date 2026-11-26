from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings
from app.utils.logger import logger

# SQLite connection check
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_columns():
    """Lightweight forward-only migration: add any model columns missing from existing tables."""
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in present:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}'))
                logger.info(f"[DB] Migrated: added column {table.name}.{col.name} ({coltype})")


def init_db():
    from app.database import models  # noqa
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
