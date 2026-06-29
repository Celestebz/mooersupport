"""
REST API router for reply templates management.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_db
from ..schemas import ReplyTemplateInfo, ReplyTemplateCreate, ReplyTemplateUpdate

router = APIRouter(prefix="/templates", tags=["Reply Templates"])


@router.get("")
def list_templates(
    status: Optional[str] = Query(None),
    limit: int = Query(default=200, le=500),
    db=Depends(get_db),
):
    """List all reply templates, optionally filtered by status."""
    rows = db.list_reply_templates(status=status, limit=limit)
    return {
        "items": [
            {
                "id": r["id"],
                "name": r.get("name") or "",
                "category": r.get("category") or "",
                "product_model": r.get("product_model") or "",
                "issue_category": r.get("issue_category") or "",
                "language": r.get("language") or "en",
                "body": r.get("body") or "",
                "status": r.get("status") or "active",
                "updated_at": str(r.get("updated_at") or ""),
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("", status_code=201)
def create_template(body: ReplyTemplateCreate, db=Depends(get_db)):
    """Create a new reply template."""
    new_id = db.upsert_reply_template(
        name=body.name,
        category=body.category,
        body=body.body,
        product_model=body.product_model,
        issue_category=body.issue_category,
        language=body.language,
    )
    if new_id is None:
        raise HTTPException(status_code=500, detail="Failed to create template")
    return {"ok": True, "id": new_id}


@router.patch("/{template_id}")
def update_template(template_id: int, body: ReplyTemplateUpdate, db=Depends(get_db)):
    """Update a reply template."""
    update_kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")
    success = db.update_reply_template(template_id, **update_kwargs)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found or update failed")
    return {"ok": True}


@router.delete("/{template_id}")
def delete_template(template_id: int, db=Depends(get_db)):
    """Soft-delete a reply template (set status to inactive)."""
    success = db.delete_reply_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}
