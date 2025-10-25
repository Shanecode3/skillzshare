from typing import Optional, Generator
import re
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from .config import settings

def _normalize_pg_url(url: str) -> str:
    return re.sub(r"^postgresql\+psycopg2://", "postgresql://", url)

_pg_pool: Optional[ConnectionPool] = None

def init_pool(minconn: int = 1, maxconn: int = 10):
    global _pg_pool
    if _pg_pool is None:
        dsn = _normalize_pg_url(settings.database_url)
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set; check your .env")
        _pg_pool = ConnectionPool(conninfo=dsn, min_size=minconn, max_size=maxconn)
    return _pg_pool

def close_pool():
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.close()
        _pg_pool = None

# ---- Dependency: read-only cursor
def cursor_readonly() -> Generator:
    """
    Yields a read-only cursor; autocommit=True to avoid idle transactions.
    FastAPI manages the generator, keeping cursor/connection alive during the request.
    """
    if _pg_pool is None:
        raise RuntimeError("DB pool not initialized")
    with _pg_pool.connection() as conn:
        conn.autocommit = True
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur

# ---- Dependency: write cursor (transactional)
def cursor_write() -> Generator:
    """
    Yields a cursor in a transaction; commits on success, rollbacks on error.
    """
    if _pg_pool is None:
        raise RuntimeError("DB pool not initialized")
    with _pg_pool.connection() as conn:
        conn.autocommit = False
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
