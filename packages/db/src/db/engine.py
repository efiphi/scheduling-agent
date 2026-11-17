"""Connecting to the database as one of the service roles (ADR-005, invariant 7).

Each service passes its own role and password; there is no shared superuser connection.
`URL.create` escapes the password and hides it when the URL is printed (T22).
"""

from sqlalchemy import URL, Engine, create_engine

DATABASE = "scheduling_agent"


def database_url(role: str, password: str, host: str = "127.0.0.1", port: int = 5432) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=role,
        password=password,
        host=host,
        port=port,
        database=DATABASE,
    )


def make_engine(role: str, password: str, host: str = "127.0.0.1", port: int = 5432) -> Engine:
    # pool_pre_ping replaces connections Postgres closed while idle (restart, timeout).
    return create_engine(database_url(role, password, host, port), pool_pre_ping=True)
