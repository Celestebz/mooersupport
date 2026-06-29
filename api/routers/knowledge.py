"""
REST API router for structured knowledge base management.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_db
from knowledge_base import KnowledgeBaseSync

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@router.get("/summary")
def knowledge_summary(db=Depends(get_db)):
    """Return grouped knowledge document/chunk counts."""
    return db.get_knowledge_summary()


@router.get("/documents")
def list_knowledge_documents(
    knowledge_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(default=500, le=1000),
    db=Depends(get_db),
):
    """List indexed knowledge documents."""
    rows = db.list_knowledge_documents(
        knowledge_type=knowledge_type,
        status=status,
        limit=limit,
    )
    return {"items": rows, "total": len(rows)}


@router.post("/sync")
def sync_knowledge(db=Depends(get_db)):
    """Synchronize existing project files and DB rows into the structured KB index."""
    syncer = KnowledgeBaseSync(db_path=db.db_path)
    return syncer.sync_all()
