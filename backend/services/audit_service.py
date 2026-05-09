import json
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from models import AuditLog


def write_audit_log(
    db: Session,
    *,
    user_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    ip_address = request.client.host if request and request.client else None
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(metadata or {}),
            ip_address=ip_address,
        )
    )

