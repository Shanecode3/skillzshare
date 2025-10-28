from fastapi import APIRouter, Depends, HTTPException, Query, Path
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
    handle: str = Field(min_length=3, max_length=40)

class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    handle: Optional[str] = Field(default=None, min_length=3, max_length=40)
    institute: Optional[str] = Field(default=None, max_length=120)
    timezone_iana: Optional[str] = Field(default=None, max_length=50)

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    handle: str
    institute: Optional[str] = None
    timezone_iana: Optional[str] = None
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
          id, email, full_name, handle, institute, 
          timezone_iana, is_active, created_at, updated_at
        FROM users
        WHERE is_active = true
        ORDER BY id
        LIMIT %s OFFSET %s;
    """
    cur.execute(sql, (limit, offset))
    return cur.fetchall()

@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int = Path(...),
    cur = Depends(cursor_readonly),
):
    cur.execute("""
        SELECT
          id, email, full_name, handle, institute,
          timezone_iana, is_active, created_at, updated_at
        FROM users
        WHERE id = %s;
    """, (user_id,))
    user = cur.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

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
          id, email, full_name, handle, institute,
          timezone_iana, is_active, created_at, updated_at;
    """
    cur.execute(insert_sql, (payload.email, pw_hash, payload.full_name, payload.handle))
    return cur.fetchone()

@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int = Path(..., description="User ID to update"),
    payload: UserUpdate = ...,
    cur = Depends(cursor_write),
):
    # Check user exists
    cur.execute("SELECT * FROM users WHERE id = %s;", (user_id,))
    existing = cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"User with id {user_id} not found")

    # Build update fields dynamically
    updates = []
    params = []
    
    if payload.full_name is not None:
        updates.append("full_name = %s")
        params.append(payload.full_name)
    
    if payload.handle is not None:
        # Check handle uniqueness
        cur.execute("SELECT 1 FROM users WHERE handle = %s AND id != %s;", (payload.handle, user_id))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Handle already exists")
        updates.append("handle = %s")
        params.append(payload.handle)
    
    
    if payload.institute is not None:
        updates.append("institute = %s")
        params.append(payload.institute)
    
    
    if payload.timezone_iana is not None:
        updates.append("timezone_iana = %s")
        params.append(payload.timezone_iana)
    
    
    if not updates:
        # No changes, return existing
        return existing
    
    # Add updated_at timestamp
    updates.append("updated_at = now()")
    
    # Add user_id as last parameter
    params.append(user_id)
    
    # Build and execute update query
    update_sql = f"""
        UPDATE users
        SET {', '.join(updates)}
        WHERE id = %s
        RETURNING
          id, email, full_name, handle, institute,
          timezone_iana, is_active, created_at, updated_at;
    """
    
    try:
        cur.execute(update_sql, params)
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="User not found after update")
        return result
    except Exception as e:
        print(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating user: {str(e)}")