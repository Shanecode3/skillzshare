from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from ..db import cursor_readonly, cursor_write
from ..utils.audit import log_event

router = APIRouter(prefix="/messages", tags=["messages"])

class MessageCreate(BaseModel):
    sender_id: int
    receiver_id: int
    body: str = Field(min_length=1)

class MessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    body: str
    created_at: datetime
    is_read: bool

def _user_exists(cur, uid: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id=%s;", (uid,))
    return bool(cur.fetchone())

@router.get("/", response_model=List[MessageOut])
def list_messages(
    sender_id: Optional[int] = Query(None),
    receiver_id: Optional[int] = Query(None),
    since: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where, params = [], []
    if sender_id is not None:
        where.append("sender_id=%s"); params.append(sender_id)
    if receiver_id is not None:
        where.append("receiver_id=%s"); params.append(receiver_id)
    if since is not None:
        where.append("created_at >= %s"); params.append(since)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cur.execute(
        f"""SELECT id, sender_id, receiver_id, body, created_at, is_read
            FROM messages {where_sql}
            ORDER BY created_at ASC
            LIMIT %s OFFSET %s;""",
        params + [limit, offset]
    )
    return cur.fetchall()

@router.get("/thread", response_model=List[MessageOut])
def get_thread(
    user_a: int = Query(...),
    user_b: int = Query(...),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    cur.execute(
        """
        SELECT id, sender_id, receiver_id, body, created_at, is_read
        FROM messages
        WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)
        ORDER BY created_at ASC
        LIMIT %s OFFSET %s;
        """,
        (user_a, user_b, user_b, user_a, limit, offset)
    )
    return cur.fetchall()

@router.post("/", response_model=MessageOut, status_code=201)
def send_message(body: MessageCreate, cur = Depends(cursor_write)):
    if body.sender_id == body.receiver_id:
        raise HTTPException(status_code=400, detail="sender and receiver must differ")
    if not _user_exists(cur, body.sender_id) or not _user_exists(cur, body.receiver_id):
        raise HTTPException(status_code=404, detail="sender or receiver not found")

    cur.execute(
        """
        INSERT INTO messages (sender_id, receiver_id, body)
        VALUES (%s, %s, %s)
        RETURNING id, sender_id, receiver_id, body, created_at, is_read;
        """,
        (body.sender_id, body.receiver_id, body.body)
    )
    row = cur.fetchone()
    log_event(cur, actor_user_id=body.sender_id, entity="messages", entity_id=row["id"], action="CREATE",
              metadata={"to": body.receiver_id})
    return row

@router.post("/mark-read")
def mark_read(
    user_id: int = Query(..., description="Receiver marking messages as read"),
    from_user_id: int = Query(...),
    cur = Depends(cursor_write),
):
    cur.execute(
        "UPDATE messages SET is_read = TRUE WHERE receiver_id=%s AND sender_id=%s AND is_read = FALSE;",
        (user_id, from_user_id)
    )
    updated = cur.rowcount
    if updated:
        log_event(cur, actor_user_id=user_id, entity="messages", entity_id=None, action="MARK_READ",
                  metadata={"from_user_id": from_user_id, "count": updated})
    return {"updated": updated}