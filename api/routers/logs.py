"""
REST API router for system logs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_db
from ..schemas import PaginatedResponse

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("", response_model=PaginatedResponse)
def get_logs(
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
):
    """Retrieve system event logs."""
    rows = db.get_logs(limit=limit + offset)
    items = [dict(row) for row in rows[offset:offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)
