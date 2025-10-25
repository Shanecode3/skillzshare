# app/security.py
from passlib.context import CryptContext

# PBKDF2-SHA256: pure-Python, no bcrypt length limit or native backend issues
_pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(plain_password: str) -> str:
    return _pwd_ctx.hash(plain_password)

def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_ctx.verify(plain_password, password_hash)