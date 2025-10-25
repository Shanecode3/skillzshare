# app/routes/user_skills.py
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from ..db import cursor_readonly, cursor_write
from psycopg.errors import UniqueViolation, ForeignKeyViolation

router = APIRouter(prefix="/user-skills", tags=["user_skills"])

# ---- allowed enum values (mirror DB enum skill_level) ----
SkillLevel = Literal["beginner", "intermediate", "advanced", "expert"]
ALLOWED_LEVELS = {"beginner", "intermediate", "advanced", "expert"}


# ---------- Models ----------
class UserSkillCreate(BaseModel):
    user_id: int
    skill_id: int
    level: SkillLevel = "intermediate"
    years_exp: Optional[float] = Field(default=0.0, ge=0, le=50)
    note: Optional[str] = Field(default=None, max_length=200)


class UserSkillUpdate(BaseModel):
    level: Optional[SkillLevel] = None
    years_exp: Optional[float] = Field(default=None, ge=0, le=50)
    note: Optional[str] = Field(default=None, max_length=200)


class UserSkillOut(BaseModel):
    user_id: int
    skill_id: int
    level: SkillLevel
    years_exp: Optional[float] = None
    note: Optional[str] = None
    created_at: datetime
    # helpful denormalized fields for UI
    user_handle: Optional[str] = None
    user_full_name: Optional[str] = None
    skill_name: Optional[str] = None
    skill_slug: Optional[str] = None


# ---------- Helpers ----------
def _round_1_dec(x: Optional[float]) -> Optional[str]:
    """
    Convert Python float to a string with 1 decimal place (e.g., '3.5')
    so Postgres NUMERIC(3,1) accepts it precisely (avoids float rounding noise).
    """
    if x is None:
        return None
    d = Decimal(str(x)).quantize(Decimal("0.0"), rounding=ROUND_HALF_UP)
    return str(d)


def _exists_user(cur, user_id: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id = %s;", (user_id,))
    return bool(cur.fetchone())


def _exists_skill(cur, skill_id: int) -> bool:
    cur.execute("SELECT 1 FROM skills WHERE id = %s;", (skill_id,))
    return bool(cur.fetchone())


# ---------- Endpoints ----------

@router.get("/", response_model=List[UserSkillOut])
def list_user_skills(
    user_id: Optional[int] = Query(None, description="Filter by user"),
    skill_id: Optional[int] = Query(None, description="Filter by skill"),
    level: Optional[SkillLevel] = Query(None),
    q: Optional[str] = Query(None, description="Search skill name/slug"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where = []
    params: list[Any] = []

    if user_id is not None:
        where.append("us.user_id = %s")
        params.append(user_id)
    if skill_id is not None:
        where.append("us.skill_id = %s")
        params.append(skill_id)
    if level is not None:
        where.append("us.level = %s")
        params.append(level)
    if q:
        where.append("(s.name ILIKE %s OR s.slug ILIKE %s)")
        like = f"%{q}%"
        params += [like, like]

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT
          us.user_id, us.skill_id, us.level, us.years_exp, us.note, us.created_at,
          u.handle AS user_handle, u.full_name AS user_full_name,
          s.name AS skill_name, s.slug AS skill_slug
        FROM user_skills us
        JOIN users  u ON u.id = us.user_id
        JOIN skills s ON s.id = us.skill_id
        {where_sql}
        ORDER BY u.id, s.name
        LIMIT %s OFFSET %s;
    """
    params += [limit, offset]
    cur.execute(sql, params)
    return cur.fetchall()


@router.get("/{user_id}/{skill_id}", response_model=UserSkillOut)
def get_user_skill(
    user_id: int = Path(...),
    skill_id: int = Path(...),
    cur = Depends(cursor_readonly),
):
    cur.execute(
        """
        SELECT
          us.user_id, us.skill_id, us.level, us.years_exp, us.note, us.created_at,
          u.handle AS user_handle, u.full_name AS user_full_name,
          s.name AS skill_name, s.slug AS skill_slug
        FROM user_skills us
        JOIN users  u ON u.id = us.user_id
        JOIN skills s ON s.id = us.skill_id
        WHERE us.user_id = %s AND us.skill_id = %s;
        """,
        (user_id, skill_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User skill not found")
    return row


@router.post("/", response_model=UserSkillOut, status_code=201)
def add_user_skill(payload: UserSkillCreate, cur = Depends(cursor_write)):
    # Fast checks for foreign keys → nicer messages than raw FK error
    if not _exists_user(cur, payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not _exists_skill(cur, payload.skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    if payload.level not in ALLOWED_LEVELS:
        raise HTTPException(status_code=422, detail="Invalid level")

    years_exp_str = _round_1_dec(payload.years_exp)

    try:
        cur.execute(
            """
            INSERT INTO user_skills (user_id, skill_id, level, years_exp, note)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING
              user_id, skill_id, level, years_exp, note, created_at;
            """,
            (payload.user_id, payload.skill_id, payload.level, years_exp_str, payload.note),
        )
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="User already has this skill")
    except ForeignKeyViolation:
        raise HTTPException(status_code=400, detail="Invalid user_id or skill_id")

    core = cur.fetchone()

    # Enrich with user & skill info for response
    cur.execute("SELECT handle, full_name FROM users WHERE id = %s;", (core["user_id"],))
    u = cur.fetchone()
    cur.execute("SELECT name, slug FROM skills WHERE id = %s;", (core["skill_id"],))
    s = cur.fetchone()

    core["user_handle"] = u["handle"] if u else None
    core["user_full_name"] = u["full_name"] if u else None
    core["skill_name"] = s["name"] if s else None
    core["skill_slug"] = s["slug"] if s else None
    return core


@router.patch("/{user_id}/{skill_id}", response_model=UserSkillOut)
def update_user_skill(
    user_id: int,
    skill_id: int,
    payload: UserSkillUpdate,
    cur = Depends(cursor_write),
):
    # Ensure row exists
    cur.execute(
        "SELECT level, years_exp, note FROM user_skills WHERE user_id = %s AND skill_id = %s;",
        (user_id, skill_id),
    )
    existing = cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="User skill not found")

    new_level = payload.level if payload.level is not None else existing["level"]
    if new_level not in ALLOWED_LEVELS:
        raise HTTPException(status_code=422, detail="Invalid level")

    new_years = _round_1_dec(payload.years_exp if payload.years_exp is not None else existing["years_exp"])
    new_note = payload.note if payload.note is not None else existing["note"]

    cur.execute(
        """
        UPDATE user_skills
        SET level = %s,
            years_exp = %s,
            note = %s
        WHERE user_id = %s AND skill_id = %s
        RETURNING user_id, skill_id, level, years_exp, note, created_at;
        """,
        (new_level, new_years, new_note, user_id, skill_id),
    )
    core = cur.fetchone()

    # Enrich
    cur.execute("SELECT handle, full_name FROM users WHERE id = %s;", (user_id,))
    u = cur.fetchone()
    cur.execute("SELECT name, slug FROM skills WHERE id = %s;", (skill_id,))
    s = cur.fetchone()
    core["user_handle"] = u["handle"] if u else None
    core["user_full_name"] = u["full_name"] if u else None
    core["skill_name"] = s["name"] if s else None
    core["skill_slug"] = s["slug"] if s else None
    return core


@router.delete("/{user_id}/{skill_id}", status_code=204)
def delete_user_skill(
    user_id: int,
    skill_id: int,
    cur = Depends(cursor_write),
):
    cur.execute("DELETE FROM user_skills WHERE user_id = %s AND skill_id = %s;", (user_id, skill_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="User skill not found")
    return