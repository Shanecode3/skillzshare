from typing import Generator, Optional
import re
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from .config import settings


def _normalize_pg_url(url: str) -> str:
    # psycopg2 expects "postgresql://..." or "postgres://"
    return re.sub(r"^postgresql\+psycopg2://", "postgresql://", url)

_pg_pool: Optional[pool.SimpleConnectionPool] = None

def init_pool(minconn: int = 1, maxconn: int = 10):
    global _pg_pool
    if _pg_pool is None:
        dsn = _normalize_pg_url(settings.database_url)
        _pg_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            dsn=dsn,
            cursor_factory=RealDictCursor,
            
        )
    return _pg_pool

def close_pool():
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.closeall()
        _pg_pool = None

def get_conn():
    if _pg_pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pg_pool.getconn()

def put_conn(conn):
    if _pg_pool is not None and conn is not None:
        _pg_pool.putconn(conn)

def get_cursor(readonly: bool = True) -> Generator:
    """
    Dependency-style generator yielding a cursor.
    - For readonly, uses autocommit to avoid lingering transactions.
    - For write operations, caller must commit/rollback explicitly.
    """
    conn = get_conn()
    try:
        if readonly:
            conn.autocommit = True
        else:
            conn.autocommit = False
        with conn.cursor() as cur:
            yield cur
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        put_conn(conn)
