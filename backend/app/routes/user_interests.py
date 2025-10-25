# app/routes/user_interests.py
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any
from datetime import datetime
from ..db import cursor_readonly, cursor_write
from psycopg.errors import UniqueViolation, ForeignKeyViolation

router = APIRouter(prefix="/user-interests", tags=["user_interests"])

# Allowed enums as per schema
DesiredLevel = Literal["beginner", "intermediate", "advanced"]
ALLOWED_DESIRED = {"beginner", "intermediate", "advanced"}

# ---------- MODELS ----------
class UserInterestCreate(BaseModel):
    user_id: int
    skill_id: int
    desired_level: DesiredLevel = "beginner"
    priority: int = Field(default=3, ge=1, le=5)
    note: Optional[str] = Field(default=None, max_length=200)


class UserInterestUpdate(BaseModel):
    desired_level: Optional[DesiredLevel] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    note: Optional[str] = Field(default=None, max_length=200)


class UserInterestOut(BaseModel):
    user_id: int
    skill_id: int
    desired_level: DesiredLevel
    priority: int
    note: Optional[str] = None
    created_at: datetime
    # denormalized
    user_handle: Optional[str] = None
    user_full_name: Optional[str] = None
    skill_name: Optional[str] = None
    skill_slug: Optional[str] = None


# ---------- HELPERS ----------
def _exists_user(cur, user_id: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id = %s;", (user_id,))
    return bool(cur.fetchone())

def _exists_skill(cur, skill_id: int) -> bool:
    cur.execute("SELECT 1 FROM skills WHERE id = %s;", (skill_id,))
    return bool(cur.fetchone())

# ---------- ENDPOINTS ----------

@router.get("/", response_model=List[UserInterestOut])
def list_user_interests(
    user_id: Optional[int] = Query(None, description="Filter by user"),
    skill_id: Optional[int] = Query(None, description="Filter by skill"),
    desired_level: Optional[DesiredLevel] = Query(None),
    q: Optional[str] = Query(None, description="Search skill name/slug"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where = []
    params: list[Any] = []
    if user_id is not None:
        where.append("ui.user_id = %s")
        params.append(user_id)
    if skill_id is not None:
        where.append("ui.skill_id = %s")
        params.append(skill_id)
    if desired_level is not None:
        where.append("ui.desired_level = %s")
        params.append(desired_level)
    if q:
        where.append("(s.name ILIKE %s OR s.slug ILIKE %s)")
        like = f"%{q}%"
        params += [like, like]

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT
          ui.user_id, ui.skill_id, ui.desired_level, ui.priority,
          ui.note, ui.created_at,
          u.handle AS user_handle, u.full_name AS user_full_name,
          s.name AS skill_name, s.slug AS skill_slug
        FROM user_interests ui
        JOIN users  u ON u.id = ui.user_id
        JOIN skills s ON s.id = ui.skill_id
        {where_sql}
        ORDER BY ui.created_at DESC
        LIMIT %s OFFSET %s;
    """
    params += [limit, offset]
    cur.execute(sql, params)
    return cur.fetchall()


@router.get("/{user_id}/{skill_id}", response_model=UserInterestOut)
def get_user_interest(
    user_id: int,
    skill_id: int,
    cur = Depends(cursor_readonly),
):
    cur.execute(
        """
        SELECT
          ui.user_id, ui.skill_id, ui.desired_level, ui.priority,
          ui.note, ui.created_at,
          u.handle AS user_handle, u.full_name AS user_full_name,
          s.name AS skill_name, s.slug AS skill_slug
        FROM user_interests ui
        JOIN users  u ON u.id = ui.user_id
        JOIN skills s ON s.id = ui.skill_id
        WHERE ui.user_id = %s AND ui.skill_id = %s;
        """,
        (user_id, skill_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User interest not found")
    return row


@router.post("/", response_model=UserInterestOut, status_code=201)
def add_user_interest(payload: UserInterestCreate, cur = Depends(cursor_write)):
    if not _exists_user(cur, payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not _exists_skill(cur, payload.skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    if payload.desired_level not in ALLOWED_DESIRED:
        raise HTTPException(status_code=422, detail="Invalid desired_level")

    try:
        cur.execute(
            """
            INSERT INTO user_interests (user_id, skill_id, desired_level, priority, note)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING user_id, skill_id, desired_level, priority, note, created_at;
            """,
            (
                payload.user_id,
                payload.skill_id,
                payload.desired_level,
                payload.priority,
                payload.note,
            ),
        )
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="Interest already exists")
    except ForeignKeyViolation:
        raise HTTPException(status_code=400, detail="Invalid user_id or skill_id")

    core = cur.fetchone()

    # Enrich response
    cur.execute("SELECT handle, full_name FROM users WHERE id = %s;", (core["user_id"],))
    u = cur.fetchone()
    cur.execute("SELECT name, slug FROM skills WHERE id = %s;", (core["skill_id"],))
    s = cur.fetchone()
    core["user_handle"] = u["handle"] if u else None
    core["user_full_name"] = u["full_name"] if u else None
    core["skill_name"] = s["name"] if s else None
    core["skill_slug"] = s["slug"] if s else None
    return core


@router.patch("/{user_id}/{skill_id}", response_model=UserInterestOut)
def update_user_interest(
    user_id: int,
    skill_id: int,
    payload: UserInterestUpdate,
    cur = Depends(cursor_write),
):
    cur.execute(
        "SELECT desired_level, priority, note FROM user_interests WHERE user_id = %s AND skill_id = %s;",
        (user_id, skill_id),
    )
    existing = cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="User interest not found")

    new_level = payload.desired_level or existing["desired_level"]
    if new_level not in ALLOWED_DESIRED:
        raise HTTPException(status_code=422, detail="Invalid desired_level")
    new_priority = payload.priority if payload.priority is not None else existing["priority"]
    new_note = payload.note if payload.note is not None else existing["note"]

    cur.execute(
        """
        UPDATE user_interests
        SET desired_level = %s, priority = %s, note = %s
        WHERE user_id = %s AND skill_id = %s
        RETURNING user_id, skill_id, desired_level, priority, note, created_at;
        """,
        (new_level, new_priority, new_note, user_id, skill_id),
    )
    core = cur.fetchone()

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
def delete_user_interest(
    user_id: int,
    skill_id: int,
    cur = Depends(cursor_write),
):
    cur.execute("DELETE FROM user_interests WHERE user_id = %s AND skill_id = %s;", (user_id, skill_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="User interest not found")
    return