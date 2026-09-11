import os

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

os.makedirs(os.path.dirname(settings.database_path), exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.database_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def _add_missing_columns() -> None:
    """Tiny stand-in for a real migration tool: adds any newly-declared,
    nullable columns to already-existing SQLite tables. Never drops/alters
    existing columns, so it's safe to run on every startup."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(engine.dialect)
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')


def init_db() -> None:
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
