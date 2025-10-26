from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from ..db import cursor_readonly, cursor_write
from ..utils.audit import log_event

router = APIRouter(prefix="/availability-slots", tags=["availability_slots"])

class SlotCreate(BaseModel):
    user_id: int
    weekday: int = Field(ge=1, le=7)
    start_minute: int = Field(ge=0, le=1440)
    end_minute: int = Field(ge=1, le=1440)
    is_online: bool = True
    location: Optional[str] = Field(default=None, max_length=160)

class SlotUpdate(BaseModel):
    weekday: Optional[int] = Field(default=None, ge=1, le=7)
    start_minute: Optional[int] = Field(default=None, ge=0, le=1440)
    end_minute: Optional[int] = Field(default=None, ge=1, le=1440)
    is_online: Optional[bool] = None
    location: Optional[str] = Field(default=None, max_length=160)

class SlotOut(BaseModel):
    id: int
    user_id: int
    weekday: int
    start_minute: int
    end_minute: int
    is_online: bool
    location: Optional[str]
    created_at: datetime

def _check_user(cur, uid: int) -> bool:
    cur.execute("SELECT 1 FROM users WHERE id=%s;", (uid,))
    return bool(cur.fetchone())

@router.get("/", response_model=List[SlotOut])
def list_slots(
    user_id: Optional[int] = Query(None),
    weekday: Optional[int] = Query(None, ge=1, le=7),
    cur = Depends(cursor_readonly),
):
    where, params = [], []
    if user_id is not None:
        where.append("user_id = %s"); params.append(user_id)
    if weekday is not None:
        where.append("weekday = %s"); params.append(weekday)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    cur.execute(
        f"""SELECT id, user_id, weekday, start_minute, end_minute, is_online, location, created_at
            FROM availability_slots {where_sql}
            ORDER BY user_id, weekday, start_minute;""",
        params
    )
    return cur.fetchall()

@router.post("/", response_model=SlotOut, status_code=201)
def create_slot(body: SlotCreate, cur = Depends(cursor_write)):
    if body.end_minute <= body.start_minute:
        raise HTTPException(status_code=400, detail="end_minute must be > start_minute")
    if not _check_user(cur, body.user_id):
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute(
        """
        INSERT INTO availability_slots (user_id, weekday, start_minute, end_minute, is_online, location)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, user_id, weekday, start_minute, end_minute, is_online, location, created_at;
        """,
        (body.user_id, body.weekday, body.start_minute, body.end_minute, body.is_online, body.location)
    )
    row = cur.fetchone()
    log_event(cur, actor_user_id=row["user_id"], entity="availability_slots", entity_id=row["id"], action="CREATE")
    return row

@router.patch("/{slot_id}", response_model=SlotOut)
def update_slot(slot_id: int, body: SlotUpdate, cur = Depends(cursor_write)):
    cur.execute("SELECT * FROM availability_slots WHERE id = %s;", (slot_id,))
    ex = cur.fetchone()
    if not ex:
        raise HTTPException(status_code=404, detail="Slot not found")

    new_weekday = body.weekday if body.weekday is not None else ex["weekday"]
    new_start = body.start_minute if body.start_minute is not None else ex["start_minute"]
    new_end = body.end_minute if body.end_minute is not None else ex["end_minute"]
    new_online = body.is_online if body.is_online is not None else ex["is_online"]
    new_loc = body.location if body.location is not None else ex["location"]

    if new_end <= new_start:
        raise HTTPException(status_code=400, detail="end_minute must be > start_minute")

    cur.execute(
        """
        UPDATE availability_slots
        SET weekday=%s, start_minute=%s, end_minute=%s, is_online=%s, location=%s
        WHERE id=%s
        RETURNING id, user_id, weekday, start_minute, end_minute, is_online, location, created_at;
        """,
        (new_weekday, new_start, new_end, new_online, new_loc, slot_id)
    )
    row = cur.fetchone()
    log_event(cur, actor_user_id=row["user_id"], entity="availability_slots", entity_id=slot_id, action="UPDATE")
    return row

@router.delete("/{slot_id}", status_code=204)
def delete_slot(slot_id: int, cur = Depends(cursor_write)):
    cur.execute("SELECT user_id FROM availability_slots WHERE id=%s;", (slot_id,))
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Slot not found")
    cur.execute("DELETE FROM availability_slots WHERE id=%s;", (slot_id,))
    log_event(cur, actor_user_id=r["user_id"], entity="availability_slots", entity_id=slot_id, action="DELETE")
    return
