from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from ..db import cursor_readonly, cursor_write
from ..security import hash_password
from datetime import datetime

router = APIRouter(prefix="/users", tags=["users"])

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    handle: str = Field(min_length=3, max_length=40)  # e.g. "shane_j"

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    handle: str
    bio: Optional[str] = None
    institute: Optional[str] = None
    semester: Optional[int] = None
    country: Optional[str] = None
    timezone_iana: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

# ---------- Routes ----------
@router.get("/", response_model=List[UserOut])
def list_users(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    sql = """
        SELECT
          id, email, full_name, handle, bio, institute, semester, country,
          timezone_iana, avatar_url, is_active, created_at, updated_at
        FROM users
        ORDER BY id
        LIMIT %s OFFSET %s;
    """
    cur.execute(sql, (limit, offset))
    return cur.fetchall()

@router.post("/", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, cur = Depends(cursor_write)):
    # Uniqueness checks (email, handle)
    cur.execute("SELECT 1 FROM users WHERE email = %s;", (payload.email,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="Email already exists")

    cur.execute("SELECT 1 FROM users WHERE handle = %s;", (payload.handle,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="Handle already exists")

    pw_hash = hash_password(payload.password)

    insert_sql = """
        INSERT INTO users (
          email, password_hash, full_name, handle
        ) VALUES (%s, %s, %s, %s)
        RETURNING
          id, email, full_name, handle, bio, institute, semester, country,
          timezone_iana, avatar_url, is_active, created_at, updated_at;
    """
    cur.execute(insert_sql, (payload.email, pw_hash, payload.full_name, payload.handle))
    return cur.fetchone()