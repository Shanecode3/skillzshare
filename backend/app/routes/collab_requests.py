# app/routes/collab_requests.py
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Any
from datetime import datetime
from ..db import cursor_readonly, cursor_write
from psycopg.errors import ForeignKeyViolation

router = APIRouter(prefix="/collab-requests", tags=["collab_requests"])

# ----- enums mirrored from DB type req_status -----
ReqStatus = Literal["PENDING", "ACCEPTED", "DECLINED", "CANCELLED", "COMPLETED"]

# Allowed transitions (server-side guardrails)
ALLOWED_TRANSITIONS = {
    "PENDING":   {"ACCEPTED", "DECLINED", "CANCELLED"},  # requester can cancel; receiver can accept/decline
    "ACCEPTED":  {"CANCELLED", "COMPLETED"},             # either party can cancel; complete after session
    "DECLINED":  set(),                                  # terminal
    "CANCELLED": set(),                                  # terminal
    "COMPLETED": set(),                                  # terminal
}

# ---------- models ----------
class CollabCreate(BaseModel):
    requester_id: int
    receiver_id: int
    offered_skill_id: Optional[int] = None
    wanted_skill_id: Optional[int] = None
    message: Optional[str] = Field(default=None, max_length=500)
    scheduled_at: Optional[datetime] = None  # optional scheduling time

class CollabOut(BaseModel):
    id: int
    requester_id: int
    receiver_id: int
    offered_skill_id: Optional[int] = None
    wanted_skill_id: Optional[int] = None
    status: ReqStatus
    message: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # denormalized convenience
    requester_handle: Optional[str] = None
    receiver_handle: Optional[str] = None

class CollabStatusUpdate(BaseModel):
    actor_user_id: int  # who performs the action (requester or receiver)
    new_status: ReqStatus

class CollabReschedule(BaseModel):
    actor_user_id: int
    scheduled_at: datetime

# ---------- helpers ----------
def _user_exists(cur, uid: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id = %s;", (uid,))
    return bool(cur.fetchone())

def _skill_exists(cur, sid: int) -> bool:
    cur.execute("SELECT 1 FROM skills WHERE id = %s;", (sid,))
    return bool(cur.fetchone())

def _fetch(cur, req_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT
          c.id, c.requester_id, c.receiver_id,
          c.offered_skill_id, c.wanted_skill_id,
          c.status, c.message, c.scheduled_at,
          c.created_at, c.updated_at,
          ru.handle AS requester_handle,
          rv.handle AS receiver_handle
        FROM collab_requests c
        JOIN users ru ON ru.id = c.requester_id
        JOIN users rv ON rv.id = c.receiver_id
        WHERE c.id = %s;
        """,
        (req_id,),
    )
    return cur.fetchone()

def _can_transition(old: str, new: str) -> bool:
    return new in ALLOWED_TRANSITIONS.get(old, set())

def _is_party(req: dict, actor_id: int) -> bool:
    return actor_id in (req["requester_id"], req["receiver_id"])

# ---------- endpoints ----------

@router.get("/", response_model=List[CollabOut])
def list_collabs(
    user_id: Optional[int] = Query(None, description="Return requests where user is requester or receiver"),
    status: Optional[ReqStatus] = Query(None),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cur = Depends(cursor_readonly),
):
    where = []
    params: list[Any] = []

    if user_id is not None:
        where.append("(c.requester_id = %s OR c.receiver_id = %s)")
        params += [user_id, user_id]
    if status is not None:
        where.append("c.status = %s")
        params.append(status)
    if since is not None:
        where.append("c.created_at >= %s")
        params.append(since)
    if until is not None:
        where.append("c.created_at < %s")
        params.append(until)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT
          c.id, c.requester_id, c.receiver_id,
          c.offered_skill_id, c.wanted_skill_id,
          c.status, c.message, c.scheduled_at,
          c.created_at, c.updated_at,
          ru.handle AS requester_handle,
          rv.handle AS receiver_handle
        FROM collab_requests c
        JOIN users ru ON ru.id = c.requester_id
        JOIN users rv ON rv.id = c.receiver_id
        {where_sql}
        ORDER BY c.created_at DESC
        LIMIT %s OFFSET %s;
    """
    params += [limit, offset]
    cur.execute(sql, params)
    return cur.fetchall()

@router.get("/{request_id}", response_model=CollabOut)
def get_collab(
    request_id: int = Path(...),
    cur = Depends(cursor_readonly),
):
    row = _fetch(cur, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Collab request not found")
    return row

@router.post("/", response_model=CollabOut, status_code=201)
def create_collab(payload: CollabCreate, cur = Depends(cursor_write)):
    # basic validations
    if payload.requester_id == payload.receiver_id:
        raise HTTPException(status_code=400, detail="Requester and receiver must be different")

    if not _user_exists(cur, payload.requester_id):
        raise HTTPException(status_code=404, detail="Requester not found")
    if not _user_exists(cur, payload.receiver_id):
        raise HTTPException(status_code=404, detail="Receiver not found")

    if payload.offered_skill_id is not None and not _skill_exists(cur, payload.offered_skill_id):
        raise HTTPException(status_code=404, detail="Offered skill not found")
    if payload.wanted_skill_id is not None and not _skill_exists(cur, payload.wanted_skill_id):
        raise HTTPException(status_code=404, detail="Wanted skill not found")

    try:
        cur.execute(
            """
            INSERT INTO collab_requests
              (requester_id, receiver_id, offered_skill_id, wanted_skill_id, message, scheduled_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                payload.requester_id,
                payload.receiver_id,
                payload.offered_skill_id,
                payload.wanted_skill_id,
                payload.message,
                payload.scheduled_at,
            ),
        )
    except ForeignKeyViolation:
        raise HTTPException(status_code=400, detail="Invalid foreign key")

    new_id = cur.fetchone()["id"]
    row = _fetch(cur, new_id)
    return row

@router.post("/{request_id}/status", response_model=CollabOut)
def set_status(
    request_id: int,
    body: CollabStatusUpdate,
    cur = Depends(cursor_write),
):
    # load
    req = _fetch(cur, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Collab request not found")

    # only participants can change status
    if not _is_party(req, body.actor_user_id):
        raise HTTPException(status_code=403, detail="Only participants can change status")

    # role-based rules
    old = req["status"]
    new = body.new_status

    if not _can_transition(old, new):
        raise HTTPException(status_code=409, detail=f"Illegal transition {old} -> {new}")

    # Additional simple guardrails:
    # - ACCEPT / DECLINE can only be done by receiver
    if new in {"ACCEPTED", "DECLINED"} and body.actor_user_id != req["receiver_id"]:
        raise HTTPException(status_code=403, detail="Only receiver can accept or decline")

    # - CANCEL can be done by either party while not terminal
    # - COMPLETE can be done by either, but only from ACCEPTED
    if new == "COMPLETED" and old != "ACCEPTED":
        raise HTTPException(status_code=409, detail="Can complete only from ACCEPTED")

    cur.execute(
        """
        UPDATE collab_requests
        SET status = %s, updated_at = now()
        WHERE id = %s
        RETURNING id;
        """,
        (new, request_id),
    )
    return _fetch(cur, request_id)

@router.post("/{request_id}/reschedule", response_model=CollabOut)
def reschedule(
    request_id: int,
    body: CollabReschedule,
    cur = Depends(cursor_write),
):
    req = _fetch(cur, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Collab request not found")

    if not _is_party(req, body.actor_user_id):
        raise HTTPException(status_code=403, detail="Only participants can reschedule")

    if req["status"] not in ("PENDING", "ACCEPTED"):
        raise HTTPException(status_code=409, detail="Can reschedule only when PENDING or ACCEPTED")

    cur.execute(
        """
        UPDATE collab_requests
        SET scheduled_at = %s, updated_at = now()
        WHERE id = %s
        RETURNING id;
        """,
        (body.scheduled_at, request_id),
    )
    return _fetch(cur, request_id)

@router.delete("/{request_id}", status_code=204)
def delete_collab(
    request_id: int,
    actor_user_id: int = Query(..., description="User performing delete"),
    cur = Depends(cursor_write),
):
    req = _fetch(cur, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Collab request not found")

    if not _is_party(req, actor_user_id):
        raise HTTPException(status_code=403, detail="Only participants can delete")

    # Hard delete is okay here (we keep audit trail separate if needed)
    cur.execute("DELETE FROM collab_requests WHERE id = %s;", (request_id,))
    return