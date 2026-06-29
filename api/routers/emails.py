"""
REST API router for emails and email search.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_db, get_analyzer
from ..schemas import (
    EmailSummary, EmailDetail, EmailStatusUpdate,
    EmailAIAnalysis, EmailSearchParams, PaginatedResponse,
)

router = APIRouter(prefix="/emails", tags=["Emails"])


def _extract_email_addr(sender: str) -> str:
    m = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender or "")
    return m.group(0) if m else sender


def _row_to_summary(row: dict) -> EmailSummary:
    return EmailSummary(
        id=str(row.get("id", "")),
        message_id=row.get("message_id") or "",
        sender=row.get("sender") or "",
        sender_email=_extract_email_addr(row.get("sender") or ""),
        subject=row.get("subject") or "",
        received_at=str(row.get("received_at") or ""),
        status=row.get("status") or "",
        intent=row.get("ai_intent") or row.get("intent") or "",
        sentiment=row.get("ai_sentiment") or row.get("sentiment") or "",
        product_model=row.get("product_model") or "",
        label=row.get("label") or "",
        has_attachment=bool(row.get("has_attachment")),
    )


def _row_to_flat_dict(row: dict) -> dict:
    """Return a flat dict with all fields — compatible with dashboard field names."""
    return {
        "id": str(row.get("id", "")),
        "message_id": row.get("message_id") or "",
        "sender": row.get("sender") or "",
        "sender_email": _extract_email_addr(row.get("sender") or ""),
        "subject": row.get("subject") or "",
        "received_at": str(row.get("received_at") or ""),
        "status": row.get("status") or "",
        "intent": row.get("ai_intent") or row.get("intent") or "",
        "ai_intent": row.get("ai_intent") or row.get("intent") or "",
        "sentiment": row.get("ai_sentiment") or row.get("sentiment") or "",
        "ai_sentiment": row.get("ai_sentiment") or row.get("sentiment") or "",
        "product_model": row.get("product_model") or "",
        "label": row.get("label") or "",
        "ai_reasoning": row.get("ai_reasoning") or row.get("reasoning") or "",
        "body": row.get("body") or "",
        "draft_body": row.get("draft_body") or "",
        "attachments": row.get("attachments") or "",
        "has_attachment": bool(row.get("has_attachment")),
        "language": row.get("language") or "",
        "thread_id": row.get("thread_id") or "",
        "thread_key": row.get("thread_key") or "",
        "normalized_subject": row.get("normalized_subject") or "",
        "in_reply_to": row.get("in_reply_to") or "",
        "references": row.get("references") or "",
        "retry_count": row.get("retry_count") or 0,
        "last_error": row.get("last_error") or "",
        "knowledge_citations": row.get("knowledge_citations") or "",
    }


@router.get("", response_model=dict)
def list_emails(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
):
    """List emails, optionally filtered by status. Returns flat dicts for dashboard compatibility."""
    rows = db.get_emails(status=status, limit=limit + offset)
    items = [_row_to_flat_dict(r) for r in rows[offset:offset + limit]]
    return {"items": items, "total": len(rows), "limit": limit, "offset": offset}


@router.get("/search", response_model=PaginatedResponse)
def search_emails(
    product_model: Optional[str] = Query(None),
    keywords: Optional[str] = Query(None),
    since_date: Optional[str] = Query(None),
    before_date: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
    analyzer=Depends(get_analyzer),
):
    """Search emails by product, keywords, date range, or status."""
    rows = analyzer.search_emails_db(
        product_model=product_model,
        keywords=keywords,
        since_date=since_date,
        before_date=before_date,
        limit=limit + offset,
    )
    if status:
        rows = [r for r in rows if r.get("status") == status]
    items = [_row_to_summary(r) for r in rows[offset:offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


@router.get("/{email_id}", response_model=EmailDetail)
def get_email(email_id: str, db=Depends(get_db)):
    """Get a single email by ID with full detail."""
    row = db.get_email_by_id(email_id)
    if not row:
        raise HTTPException(status_code=404, detail="Email not found")
    return EmailDetail(
        id=str(row.get("id", "")),
        message_id=row.get("message_id") or "",
        sender=row.get("sender") or "",
        sender_email=_extract_email_addr(row.get("sender") or ""),
        subject=row.get("subject") or "",
        received_at=str(row.get("received_at") or ""),
        status=row.get("status") or "",
        intent=row.get("intent") or "",
        sentiment=row.get("sentiment") or "",
        product_model=row.get("product_model") or "",
        label=row.get("label") or "",
        has_attachment=bool(row.get("has_attachment")),
        body=row.get("body") or "",
        analysis_json=row.get("analysis_json"),
        draft_body=row.get("draft_body") or "",
        knowledge_citations=row.get("knowledge_citations") or "",
        reasoning=row.get("reasoning") or "",
        retry_count=row.get("retry_count") or 0,
        last_error=row.get("last_error") or "",
        thread_id=row.get("thread_id") or "",
        in_reply_to=row.get("in_reply_to") or "",
    )


@router.get("/{email_id}/thread", response_model=dict)
def get_email_thread(email_id: str, limit: int = Query(default=20, le=50), db=Depends(get_db)):
    """Get lightweight conversation context for a draft/email."""
    thread = db.get_email_thread_context(email_id, limit=limit)
    if not thread:
        raise HTTPException(status_code=404, detail="Email thread not found")
    return thread


@router.patch("/{email_id}/status")
def update_email_status(email_id: str, body: EmailStatusUpdate, db=Depends(get_db)):
    """Update email status, draft, reasoning, label, or retry count."""
    success = db.update_email_status(
        email_id,
        status=body.status,
        draft_body=body.draft_body,
        reasoning=body.reasoning,
        label=body.label,
        last_error=body.last_error,
        knowledge_citations=body.knowledge_citations,
        increment_attempts=body.increment_attempts,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Email not found or update failed")
    return {"ok": True}


@router.patch("/{email_id}/ai-analysis")
def update_email_ai_analysis(email_id: str, body: EmailAIAnalysis, db=Depends(get_db)):
    """Update AI analysis fields (intent, sentiment, product_model)."""
    success = db.update_email_ai_analysis(email_id, {
        "intent": body.intent,
        "sentiment": body.sentiment,
        "product_model": body.product_model,
    })
    if not success:
        raise HTTPException(status_code=404, detail="Email not found or update failed")
    return {"ok": True}
