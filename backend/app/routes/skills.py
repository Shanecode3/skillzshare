# app/routes/skills.py
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import Optional, List, Union, Dict, Any
from datetime import datetime
import re

from ..db import cursor_readonly, cursor_write
from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

router = APIRouter(prefix="/skills", tags=["skills"])

# ---------- helpers ----------
_slug_re = re.compile(r"[^a-z0-9]+")
def slugify(text: str) -> str:
    text = text.strip().lower()
    text = _slug_re.sub("-", text)
    return text.strip("-")

# ---------- models ----------
JsonLike = Union[Dict[str, Any], List[Any]]

class SkillCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    category: Optional[str] = Field(default=None, max_length=80)
    synonyms_json: Optional[JsonLike] = None
    # allow custom slug; if omitted we auto-generate from name
    slug: Optional[str] = Field(default=None, max_length=120)

class SkillUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    category: Optional[str] = Field(default=None, max_length=80)
    synonyms_json: Optional[JsonLike] = None
    slug: Optional[str] = Field(default=None, max_length=120)
    is_active: Optional[bool] = None

class SkillOut(BaseModel):
    id: int
    name: str
    slug: str
    category: Optional[str] = None
    synonyms_json: Optional[JsonLike] = None
    is_active: bool
    created_at: datetime

# ---------- endpoints ----------

@router.get("/", response_model=List[SkillOut])
def list_skills(
    q: Optional[str] = Query(default=None, description="Search in name/slug/category"),
    only_active: bool = Query(default=True),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where = []
    params: List[Any] = []
    if q:
        where.append("(name ILIKE %s OR slug ILIKE %s OR category ILIKE %s)")
        like = f"%{q}%"
        params += [like, like, like]
    if only_active:
        where.append("is_active = true")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT id, name, slug, category, synonyms_json, is_active, created_at
        FROM skills
        {where_sql}
        ORDER BY name
        LIMIT %s OFFSET %s;
    """
    params += [limit, offset]
    cur.execute(sql, params)
    return cur.fetchall()

def _get_skill_by_id_or_slug(id_or_slug: str, cur) -> Optional[dict]:
    if id_or_slug.isdigit():
        cur.execute("""
            SELECT id, name, slug, category, synonyms_json, is_active, created_at
            FROM skills WHERE id = %s;
        """, (int(id_or_slug),))
    else:
        cur.execute("""
            SELECT id, name, slug, category, synonyms_json, is_active, created_at
            FROM skills WHERE slug = %s;
        """, (id_or_slug,))
    return cur.fetchone()

@router.get("/{id_or_slug}", response_model=SkillOut)
def get_skill(
    id_or_slug: str = Path(..., description="Numeric id or slug"),
    cur = Depends(cursor_readonly),
):
    row = _get_skill_by_id_or_slug(id_or_slug, cur)
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    return row

@router.post("/", response_model=SkillOut, status_code=201)
def create_skill(payload: SkillCreate, cur = Depends(cursor_write)):
    # slug
    slug = payload.slug.strip().lower() if payload.slug else slugify(payload.name)
    # enforce uniqueness hints before insert (nice error messages)
    cur.execute("SELECT 1 FROM skills WHERE slug = %s;", (slug,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="Slug already exists")

    try:
        cur.execute(
            """
            INSERT INTO skills (name, slug, category, synonyms_json)
            VALUES (%s, %s, %s, %s)
            RETURNING id, name, slug, category, synonyms_json, is_active, created_at;
            """,
            (payload.name, slug, payload.category, Json(payload.synonyms_json) if payload.synonyms_json is not None else None),
        )
    except UniqueViolation:
        # covers the rare race where slug becomes taken between our check and insert
        raise HTTPException(status_code=409, detail="Slug already exists")

    return cur.fetchone()

@router.patch("/{id_or_slug}", response_model=SkillOut)
def update_skill(
    id_or_slug: str,
    payload: SkillUpdate,
    cur = Depends(cursor_write),
):
    # Find current
    existing = _get_skill_by_id_or_slug(id_or_slug, cur)
    if not existing:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Prepare updates
    new_name = payload.name if payload.name is not None else existing["name"]
    new_slug = (
        payload.slug.strip().lower()
        if payload.slug is not None
        else existing["slug"]
    )
    new_category = payload.category if payload.category is not None else existing["category"]
    new_syn = payload.synonyms_json if payload.synonyms_json is not None else existing["synonyms_json"]
    new_active = payload.is_active if payload.is_active is not None else existing["is_active"]

    # If user updated name but didn't provide slug, we keep the same slug by default.
    # (Change to: new_slug = slugify(new_name) if payload.name and payload.slug is None else new_slug)
    try:
        cur.execute(
            """
            UPDATE skills
            SET name = %s,
                slug = %s,
                category = %s,
                synonyms_json = %s,
                is_active = %s
            WHERE id = %s
            RETURNING id, name, slug, category, synonyms_json, is_active, created_at;
            """,
            (
                new_name,
                new_slug,
                new_category,
                Json(new_syn) if new_syn is not None else None,
                new_active,
                existing["id"],
            ),
        )
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="Slug already exists")

    return cur.fetchone()

@router.delete("/{id_or_slug}", status_code=204)
def delete_skill(
    id_or_slug: str,
    purge: bool = Query(False, description="Hard delete instead of soft delete"),
    cur = Depends(cursor_write),
):
    row = _get_skill_by_id_or_slug(id_or_slug, cur)
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")

    if purge:
        cur.execute("DELETE FROM skills WHERE id = %s;", (row["id"],))
    else:
        cur.execute("UPDATE skills SET is_active = false WHERE id = %s;", (row["id"],))
    return
