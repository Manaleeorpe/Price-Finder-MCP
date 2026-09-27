import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine


DATABASE_URL_ENV = "DATABASE_URL"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_paths():
    paths = [PROJECT_ROOT / ".env", Path.cwd() / ".env"]
    paths.extend(parent / ".env" for parent in Path.cwd().parents)

    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield resolved


def load_env_file() -> None:
    for env_path in _env_paths():
        if not env_path.exists():
            continue

        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def get_database_url() -> str:
    load_env_file()
    database_url = os.getenv(DATABASE_URL_ENV)
    if not database_url:
        checked_paths = ", ".join(str(path) for path in _env_paths())
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is not set. Checked .env paths: {checked_paths}"
        )
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def is_database_configured() -> bool:
    load_env_file()
    return bool(os.getenv(DATABASE_URL_ENV))


def get_engine():
    return create_engine(get_database_url(), pool_pre_ping=True)


def create_db_and_tables() -> None:
    engine = get_engine()
    try:
        SQLModel.metadata.create_all(engine)
        migrate_price_alerts_table(engine)
    finally:
        engine.dispose()


def migrate_price_alerts_table(engine) -> None:
    """Add columns that create_all will not add to an existing table."""
    inspector = inspect(engine)
    if "price_alerts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("price_alerts")}
    column_types = {
        column["name"]: str(column["type"]).lower()
        for column in inspector.get_columns("price_alerts")
    }
    migrations = []
    if "latest_price" not in columns:
        migrations.append("ALTER TABLE price_alerts ADD COLUMN latest_price DOUBLE PRECISION")
    if "last_updated_at" not in columns:
        migrations.append("ALTER TABLE price_alerts ADD COLUMN last_updated_at DATE")
    if "starting_price" in columns and "double" not in column_types["starting_price"]:
        migrations.append(
            "ALTER TABLE price_alerts "
            "ALTER COLUMN starting_price TYPE DOUBLE PRECISION "
            "USING starting_price::double precision"
        )
    if "lowest_notified_price" in columns and "double" not in column_types["lowest_notified_price"]:
        migrations.append(
            "ALTER TABLE price_alerts "
            "ALTER COLUMN lowest_notified_price TYPE DOUBLE PRECISION "
            "USING lowest_notified_price::double precision"
        )

    if not migrations:
        return

    with engine.begin() as connection:
        for statement in migrations:
            connection.execute(text(statement))


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    engine = get_engine()
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def get_session() -> Generator[Session, None, None]:
    with session_scope() as session:
        yield session
