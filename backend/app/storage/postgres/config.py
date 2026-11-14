from __future__ import annotations

import os
from collections.abc import Mapping

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker


DATABASE_URL_ENV = "DATABASE_URL"
POSTGRES_DRIVER = "postgresql+psycopg"


class PostgresConfigurationError(ValueError):
    """Raised when PostgreSQL is not configured explicitly and safely."""


def database_url_from_env(
    environ: Mapping[str, str] | None = None,
) -> URL:
    """Return an explicit PostgreSQL URL without exposing it in errors."""

    values = os.environ if environ is None else environ
    raw_url = values.get(DATABASE_URL_ENV, "").strip()
    if not raw_url:
        raise PostgresConfigurationError(
            f"{DATABASE_URL_ENV} must be set to use PostgreSQL"
        )

    try:
        url = make_url(raw_url)
    except ArgumentError:
        raise PostgresConfigurationError(
            f"{DATABASE_URL_ENV} is not a valid SQLAlchemy URL"
        ) from None

    if url.drivername != POSTGRES_DRIVER:
        raise PostgresConfigurationError(
            f"{DATABASE_URL_ENV} must use the {POSTGRES_DRIVER} driver"
        )
    if not url.database:
        raise PostgresConfigurationError(
            f"{DATABASE_URL_ENV} must name a PostgreSQL database"
        )
    return url


def engine_options(url: URL, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Build bounded pool and driver options for an already selected URL."""
    values = os.environ if environ is None else environ
    options = {"pool_pre_ping": True, "pool_timeout": float(values.get("DB_POOL_TIMEOUT", "10"))}
    if "DB_POOL_SIZE" in values:
        options["pool_size"] = int(values["DB_POOL_SIZE"])
    if "DB_MAX_OVERFLOW" in values:
        options["max_overflow"] = int(values["DB_MAX_OVERFLOW"])
    if url.drivername.startswith("postgresql"):
        options["connect_args"] = {"connect_timeout": int(values.get("DB_CONNECT_TIMEOUT", "5"))}
    return options


def create_postgres_engine(database_url: URL | None = None) -> Engine:
    """Create a lazy PostgreSQL engine; never choose a fallback backend."""

    url = database_url or database_url_from_env()
    if url.drivername != POSTGRES_DRIVER or not url.database:
        raise PostgresConfigurationError(
            f"PostgreSQL requires a {POSTGRES_DRIVER} URL with a database name"
        )
    options = engine_options(url)
    return create_engine(url, **options)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory without connecting until a session is used."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
