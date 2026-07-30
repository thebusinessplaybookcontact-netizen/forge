from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# check_same_thread=False is required because FastAPI serves requests from a threadpool.
connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

if settings.is_sqlite:
    # A freshly mounted volume is an empty directory that may not exist yet; without
    # this the first connection fails with "unable to open database file".
    settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.resolved_database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


#  table  -> column -> DDL type
#
# create_all() only creates missing *tables*, so a column added to an existing model is
# invisible to a database that predates it — every query then fails with "no such
# column". Until this earns Alembic, new columns go here.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "goals": {"deleted_at": "DATETIME"},
    "tasks": {"deleted_at": "DATETIME"},
}


def _backfill_columns() -> None:
    if engine.dialect.name != "sqlite":
        # Anything else gets real migrations; don't hand-roll ALTERs for it.
        return

    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if not existing:
                continue  # table didn't exist; create_all just made it correctly
            for column, ddl in columns.items():
                if column not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    """Create tables if they don't exist, then add any columns they're missing.

    Scaffold-level only — there are no migrations yet. Once the schema stabilises,
    swap this for Alembic before there is data worth keeping.
    """
    from . import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(bind=engine)
    _backfill_columns()
