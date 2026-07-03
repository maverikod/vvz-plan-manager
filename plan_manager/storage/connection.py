"""Database connection substrate for plan_manager storage."""

import psycopg


def connect(dsn: str) -> psycopg.Connection:
    """Open a psycopg 3 connection to the plan_manager database.

    Parameters:
        dsn: str
            A complete libpq connection string (DSN), e.g.
            "postgresql://user:password@host:port/dbname". Building this
            string from server configuration is out of scope for this
            function; it accepts the DSN exactly as given.

    Returns:
        psycopg.Connection
            An open psycopg 3 connection with autocommit=False (the
            default transactional mode: callers must call commit() or
            rollback() explicitly).
    """
    return psycopg.connect(dsn, autocommit=False)
