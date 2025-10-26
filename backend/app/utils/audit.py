from typing import Optional, Any, Dict
from psycopg.types.json import Json

def log_event(cur, *, actor_user_id: Optional[int], entity: str, entity_id: Optional[int],
              action: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    cur.execute(
        """
        INSERT INTO audit_log (actor_user_id, entity, entity_id, action, metadata)
        VALUES (%s, %s, %s, %s, %s);
        """,
        (actor_user_id, entity, entity_id, action, Json(metadata) if metadata is not None else None)
    )
