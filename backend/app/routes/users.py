from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Any, Dict
from ..db import get_cursor

router = APIRouter(prefix="/users", tags=["users"])

class UserCreate(BaseModel):
    email: EmailStr
    full_name: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    created_at: Optional[str]  # ISO string from PostgreSQL

@router.get("/", response_model=List[UserOut])
def list_users(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(lambda: next(get_cursor(readonly=True)))
):
    sql = """
        SELECT id, email, full_name, created_at
        FROM users
        ORDER BY id
        LIMIT %s OFFSET %s;
    """
    cur.execute(sql, (limit, offset))
    rows = cur.fetchall()  # RealDictCursor -> list[dict]
    # pydantic will coerce dicts to UserOut
    return rows

@router.post("/", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, cur = Depends(lambda: next(get_cursor(readonly=False)))):
    # Check unique email (example; you may have unique index already)
    cur.execute("SELECT id FROM users WHERE email = %s;", (payload.email,))
    existing = cur.fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    insert_sql = """
        INSERT INTO users (email, full_name)
        VALUES (%s, %s)
        RETURNING id, email, full_name, created_at;
    """
    cur.execute(insert_sql, (payload.email, payload.full_name))
    row = cur.fetchone()
    return row