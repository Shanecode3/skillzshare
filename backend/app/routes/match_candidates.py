from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from ..db import cursor_readonly, cursor_write
from ..utils.audit import log_event

router = APIRouter(prefix="/match-candidates", tags=["match_candidates"])

class CandidateCreate(BaseModel):
    source_user_id: int
    target_user_id: int
    offered_skill_id: Optional[int] = None
    wanted_skill_id: Optional[int] = None
    score: Decimal = Field(gt=0)
    rationale: Optional[str] = Field(default=None, max_length=400)

class CandidateOut(BaseModel):
    id: int
    source_user_id: int
    target_user_id: int
    offered_skill_id: Optional[int]
    wanted_skill_id: Optional[int]
    score: Decimal
    rationale: Optional[str]
    created_at: datetime

def _user_exists(cur, uid: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id=%s;", (uid,))
    return bool(cur.fetchone())

def _skill_exists(cur, sid: int) -> bool:
    cur.execute("SELECT 1 FROM skills WHERE id=%s;", (sid,))
    return bool(cur.fetchone())

@router.get("/", response_model=List[CandidateOut])
def list_candidates(
    source_user_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where, params = [], []
    if source_user_id is not None:
        where.append("source_user_id=%s"); params.append(source_user_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cur.execute(
        f"""SELECT id, source_user_id, target_user_id, offered_skill_id, wanted_skill_id,
                   score, rationale, created_at
            FROM match_candidates
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s;""",
        params + [limit, offset]
    )
    return cur.fetchall()

@router.post("/", response_model=CandidateOut, status_code=201)
def create_candidate(body: CandidateCreate, cur = Depends(cursor_write)):
    if body.source_user_id == body.target_user_id:
        raise HTTPException(status_code=400, detail="users must differ")
    if not _user_exists(cur, body.source_user_id) or not _user_exists(cur, body.target_user_id):
        raise HTTPException(status_code=404, detail="user not found")
    if body.offered_skill_id is not None and not _skill_exists(cur, body.offered_skill_id):
        raise HTTPException(status_code=404, detail="offered skill not found")
    if body.wanted_skill_id is not None and not _skill_exists(cur, body.wanted_skill_id):
        raise HTTPException(status_code=404, detail="wanted skill not found")

    cur.execute(
        """
        INSERT INTO match_candidates
        (source_user_id, target_user_id, offered_skill_id, wanted_skill_id, score, rationale)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, source_user_id, target_user_id, offered_skill_id, wanted_skill_id, score, rationale, created_at;
        """,
        (body.source_user_id, body.target_user_id, body.offered_skill_id, body.wanted_skill_id, body.score, body.rationale)
    )
    row = cur.fetchone()
    log_event(cur, actor_user_id=body.source_user_id, entity="match_candidates", entity_id=row["id"], action="CREATE",
              metadata={"target_user": body.target_user_id, "score": str(body.score)})
    return row