from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from ..db import cursor_readonly, cursor_write
from ..utils.audit import log_event

router = APIRouter(prefix="/reviews", tags=["reviews"])

class ReviewCreate(BaseModel):
    reviewer_id: int
    reviewee_id: int
    collab_request_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=400)

class ReviewOut(BaseModel):
    id: int
    reviewer_id: int
    reviewee_id: int
    collab_request_id: Optional[int]
    rating: int
    comment: Optional[str]
    created_at: datetime

def _user_exists(cur, uid: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id=%s;", (uid,))
    return bool(cur.fetchone())

def _collab_exists(cur, cid: int) -> bool:
    cur.execute("SELECT 1 FROM collab_requests WHERE id=%s;", (cid,))
    return bool(cur.fetchone())

@router.get("/", response_model=List[ReviewOut])
def list_reviews(
    reviewee_id: Optional[int] = Query(None),
    reviewer_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where, params = [], []
    if reviewee_id is not None:
        where.append("reviewee_id=%s"); params.append(reviewee_id)
    if reviewer_id is not None:
        where.append("reviewer_id=%s"); params.append(reviewer_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cur.execute(
        f"""SELECT id, reviewer_id, reviewee_id, collab_request_id, rating, comment, created_at
            FROM reviews {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s;""",
        params + [limit, offset]
    )
    return cur.fetchall()

@router.post("/", response_model=ReviewOut, status_code=201)
def create_review(body: ReviewCreate, cur = Depends(cursor_write)):
    if body.reviewer_id == body.reviewee_id:
        raise HTTPException(status_code=400, detail="reviewer and reviewee must differ")
    if not _user_exists(cur, body.reviewer_id) or not _user_exists(cur, body.reviewee_id):
        raise HTTPException(status_code=404, detail="reviewer or reviewee not found")
    if body.collab_request_id is not None and not _collab_exists(cur, body.collab_request_id):
        raise HTTPException(status_code=404, detail="collab request not found")

    cur.execute(
        """
        INSERT INTO reviews (reviewer_id, reviewee_id, collab_request_id, rating, comment)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, reviewer_id, reviewee_id, collab_request_id, rating, comment, created_at;
        """,
        (body.reviewer_id, body.reviewee_id, body.collab_request_id, body.rating, body.comment)
    )
    row = cur.fetchone()
    log_event(cur, actor_user_id=body.reviewer_id, entity="reviews", entity_id=row["id"], action="CREATE",
              metadata={"reviewee": body.reviewee_id, "rating": body.rating})
    return row