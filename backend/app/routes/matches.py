from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from ..db import cursor_readonly, cursor_write
from ..utils.audit import log_event

router = APIRouter(prefix="/matches", tags=["matches"])

class MatchCreate(BaseModel):
    user_a_id: int
    user_b_id: int
    score: Decimal = Field(gt=0)   # NUMERIC(5,2) in DB
    reason: Optional[str] = Field(default=None, max_length=300)
    created_by: Optional[str] = "system"  # matches schema default

class MatchOut(BaseModel):
    id: int
    user_a_id: int
    user_b_id: int
    score: Decimal
    reason: Optional[str]
    created_by: Optional[str]
    created_at: datetime

def _user_exists(cur, uid: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id=%s;", (uid,))
    return bool(cur.fetchone())

@router.get("/", response_model=List[MatchOut])
def list_matches(
    user_id: Optional[int] = Query(None),
    min_score: Optional[Decimal] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where, params = [], []
    if user_id is not None:
        where.append("(user_a_id=%s OR user_b_id=%s)"); params += [user_id, user_id]
    if min_score is not None:
        where.append("score >= %s"); params.append(min_score)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cur.execute(
        f"""SELECT id, user_a_id, user_b_id, score, reason, created_by, created_at
            FROM matches {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s;""",
        params + [limit, offset]
    )
    return cur.fetchall()

@router.post("/", response_model=MatchOut, status_code=201)
def create_match(body: MatchCreate, cur = Depends(cursor_write)):
    if body.user_a_id == body.user_b_id:
        raise HTTPException(status_code=400, detail="users must differ")
    if not _user_exists(cur, body.user_a_id) or not _user_exists(cur, body.user_b_id):
        raise HTTPException(status_code=404, detail="user not found")

    
    cur.execute(
        """
        INSERT INTO matches (user_a_id, user_b_id, score, reason, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, user_a_id, user_b_id, score, reason, created_by, created_at;
        """,
        (body.user_a_id, body.user_b_id, body.score, body.reason, body.created_by)
    )
    row = cur.fetchone()
    log_event(cur, actor_user_id=None, entity="matches", entity_id=row["id"], action="CREATE",
              metadata={"user_a": body.user_a_id, "user_b": body.user_b_id, "score": str(body.score)})
    return row
