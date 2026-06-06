from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .paths import DB_PATH


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401 — register mappers
    Base.metadata.create_all(engine)
    _ensure_columns()


# (table, column_name, sqlite_column_def) — additive only; never drops or retypes.
# SQLAlchemy create_all() makes tables but won't add columns to existing ones.
_REQUIRED_COLUMNS: list[tuple[str, str, str]] = [
    ("dag", "is_paused", "BOOLEAN NOT NULL DEFAULT 0"),
    ("dag", "next_run_at", "DATETIME"),
    ("dag", "spec_json", "TEXT"),
    ("dag", "params_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("dag_run", "params_json", "TEXT NOT NULL DEFAULT '{}'"),
]


def _ensure_columns() -> None:
    with engine.begin() as conn:
        for table, column, ddl in _REQUIRED_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
