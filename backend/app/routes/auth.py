from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from typing import Optional
from ..db import cursor_readonly
from ..security import verify_password
from ..auth_tokens import create_access_token, decode_token

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MeOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    handle: str
    is_active: bool

def _get_user_by_email(cur, email: str) -> Optional[dict]:
    cur.execute(
        """
        SELECT id, email, password_hash, full_name, handle, is_active
        FROM users WHERE email = %s;
        """,
        (email,)
    )
    return cur.fetchone()

@router.post("/login", response_model=TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends(), cur = Depends(cursor_readonly)):
    # form_data.username will carry the email (standard OAuth2 field name)
    user = _get_user_by_email(cur, form_data.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="User is inactive")

    if not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token({"sub": str(user["id"])})
    return TokenOut(access_token=token)

def get_current_user(token: str = Depends(oauth2_scheme), cur = Depends(cursor_readonly)) -> dict:
    try:
        payload = decode_token(token)
        uid = int(payload.get("sub", "0"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    cur.execute(
        """SELECT id, email, full_name, handle, is_active
           FROM users WHERE id = %s;""",
        (uid,)
    )
    user = cur.fetchone()
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid user")
    return user

@router.get("/me", response_model=MeOut)
def me(current = Depends(get_current_user)):
    return current