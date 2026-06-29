"""
REST API router for support issues management.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_db
from ..schemas import (
    SupportIssueSummary, SupportIssueDetail, SupportIssueCreate,
    SupportIssueUpdate, ScanIssueRequest, IssueEmailLink,
    IssueCandidateReview, PaginatedResponse,
)

router = APIRouter(prefix="/issues", tags=["Issues"])


def _row_to_summary(row: dict) -> SupportIssueSummary:
    return SupportIssueSummary(
        id=row.get("id", 0),
        issue_signature=row.get("issue_signature") or "",
        issue_title=row.get("issue_title") or "",
        issue_category=row.get("issue_category") or "",
        product_model=row.get("product_model") or "",
        user_count=row.get("user_count") or 0,
        email_count=row.get("email_count") or 0,
        status=row.get("status") or "",
        priority=row.get("priority") or "",
        rnd_status=row.get("rnd_status") or "",
        first_seen_at=str(row.get("first_seen_at") or ""),
        last_seen_at=str(row.get("last_seen_at") or ""),
    )


@router.get("", response_model=PaginatedResponse)
def list_issues(
    status: Optional[str] = Query(None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
):
    """List support issues, optionally filtered by status."""
    rows = db.get_support_issues(status=status, limit=limit + offset)
    items = [_row_to_summary(r) for r in rows[offset:offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


@router.get("/{issue_id:int}", response_model=SupportIssueDetail)
def get_issue(issue_id: int, db=Depends(get_db)):
    """Get a single support issue by ID."""
    issues = db.get_support_issues(limit=1000)
    for row in issues:
        if row.get("id") == issue_id:
            return SupportIssueDetail(
                id=row.get("id", 0),
                issue_signature=row.get("issue_signature") or "",
                issue_title=row.get("issue_title") or "",
                issue_category=row.get("issue_category") or "",
                product_model=row.get("product_model") or "",
                user_count=row.get("user_count") or 0,
                email_count=row.get("email_count") or 0,
                status=row.get("status") or "",
                priority=row.get("priority") or "",
                rnd_status=row.get("rnd_status") or "",
                first_seen_at=str(row.get("first_seen_at") or ""),
                last_seen_at=str(row.get("last_seen_at") or ""),
                rnd_notes=row.get("rnd_notes") or "",
                solution_summary=row.get("solution_summary") or "",
                final_reply_template=row.get("final_reply_template") or "",
            )
    raise HTTPException(status_code=404, detail="Issue not found")


@router.get("/{issue_id:int}/emails", response_model=dict)
def get_issue_emails(
    issue_id: int,
    limit: int = Query(default=500, le=1000),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
):
    """Get all emails linked to a support issue. Returns full email dicts (compatible with dashboard)."""
    rows = db.get_issue_emails(issue_id, limit=limit + offset)
    items = []
    for r in rows[offset:offset + limit]:
        items.append({
            "id": str(r.get("id", "")),
            "message_id": r.get("message_id") or "",
            "sender": r.get("sender") or "",
            "sender_email": _extract_email(r.get("sender") or ""),
            "subject": r.get("subject") or "",
            "received_at": str(r.get("received_at") or ""),
            "status": r.get("status") or "",
            "ai_intent": r.get("ai_intent") or "",
            "ai_sentiment": r.get("ai_sentiment") or "",
            "product_model": r.get("product_model") or "",
            "label": r.get("label") or "",
            "body": r.get("body") or "",
            "draft_body": r.get("draft_body") or "",
            "ai_reasoning": r.get("ai_reasoning") or "",
            "attachments": r.get("attachments") or "",
            "has_attachment": bool(r.get("has_attachment")),
            "language": r.get("language") or "",
            "thread_id": r.get("thread_id") or "",
            "retry_count": r.get("retry_count") or 0,
        })
    return {"items": items, "total": len(rows), "limit": limit, "offset": offset}


def _email_row_to_dict(r: dict) -> dict:
    return {
        "id": str(r.get("id", "")),
        "message_id": r.get("message_id") or "",
        "sender": r.get("sender") or "",
        "sender_email": _extract_email(r.get("sender") or ""),
        "subject": r.get("subject") or "",
        "received_at": str(r.get("received_at") or ""),
        "status": r.get("status") or "",
        "ai_intent": r.get("ai_intent") or "",
        "ai_sentiment": r.get("ai_sentiment") or "",
        "product_model": r.get("product_model") or "",
        "label": r.get("label") or "",
        "body": r.get("body") or "",
        "draft_body": r.get("draft_body") or "",
        "ai_reasoning": r.get("ai_reasoning") or "",
        "attachments": r.get("attachments") or "",
        "candidate_status": r.get("candidate_status") or "",
        "confidence": r.get("confidence") or 0,
        "matched_by": r.get("matched_by") or "",
        "matched_keywords": r.get("matched_keywords") or "",
        "evidence_snippet": r.get("evidence_snippet") or "",
        "review_note": r.get("review_note") or "",
        "reviewed_at": str(r.get("reviewed_at") or ""),
    }


@router.get("/{issue_id:int}/candidates", response_model=dict)
def get_issue_candidates(
    issue_id: int,
    status: Optional[str] = Query(None),
    limit: int = Query(default=500, le=1000),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
):
    """Get candidate emails waiting for issue review."""
    rows = db.get_issue_candidates(issue_id, status=status, limit=limit + offset)
    items = [_email_row_to_dict(r) for r in rows[offset:offset + limit]]
    return {"items": items, "total": len(rows), "limit": limit, "offset": offset}


@router.patch("/{issue_id:int}/candidates/{email_id}")
def review_issue_candidate(
    issue_id: int,
    email_id: str,
    body: IssueCandidateReview,
    db=Depends(get_db),
):
    """Review one candidate email: pending, confirmed, weak_related, excluded, unsure."""
    ok = db.review_issue_candidate(
        issue_id,
        email_id,
        candidate_status=body.status,
        review_note=body.review_note,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Candidate not found or update failed")
    return {"ok": True}


@router.post("", response_model=SupportIssueSummary, status_code=201)
def create_issue(body: SupportIssueCreate, db=Depends(get_db)):
    """Create a new support issue."""
    success = db.upsert_support_issue({
        "issue_signature": body.issue_signature,
        "issue_title": body.issue_title,
        "issue_category": body.issue_category,
        "product_model": body.product_model,
        "user_count": body.user_count,
        "email_count": body.email_count,
        "priority": body.priority,
        "status": body.status,
    })
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create issue")
    # Retrieve the created issue
    issues = db.get_support_issues(limit=1000)
    for row in issues:
        if row.get("issue_signature") == body.issue_signature:
            return _row_to_summary(row)
    raise HTTPException(status_code=500, detail="Issue created but not found on read-back")


@router.patch("/{issue_id:int}")
def update_issue(issue_id: int, body: SupportIssueUpdate, db=Depends(get_db)):
    """Update a support issue's tracking fields."""
    update_kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update_kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")
    success = db.update_support_issue(issue_id, **update_kwargs)
    if not success:
        raise HTTPException(status_code=404, detail="Issue not found or update failed")
    return {"ok": True}


@router.post("/{issue_id:int}/link-emails")
def link_emails_to_issue(issue_id: int, body: IssueEmailLink, db=Depends(get_db)):
    """Link multiple emails to a support issue."""
    emails = [{"id": eid} for eid in body.email_ids]
    linked = db.link_emails_to_issue(
        issue_id, emails,
        confidence=body.confidence,
        matched_by=body.matched_by,
    )
    return {"ok": True, "linked_count": linked}


@router.post("/scan")
def scan_for_issue(body: ScanIssueRequest, db=Depends(get_db)):
    """
    Generic issue scanner.
    Searches emails by product + keywords and stores matches as review candidates.
    Confirmed candidates are linked to the formal issue later.
    """
    from issue_facts import score_issue_match

    keywords = body.keywords if body.keywords else [body.issue_title]
    if not keywords:
        raise HTTPException(status_code=400, detail="Need at least one keyword or issue_title")

    # Search DB for candidate emails
    rows = db.get_emails(limit=5000)
    matched = []
    rejected = []
    for row in rows:
        match = score_issue_match(
            row,
            target_model=body.product_model,
            issue_title=body.issue_title,
            keywords=keywords,
            category=body.category,
        )
        if match["matched"]:
            row = dict(row)
            row["_issue_facts"] = match.get("facts", {})
            row["_matched_keywords"] = match.get("matched_keywords", [])
            row["_match_confidence"] = match.get("confidence", 0.5)
            matched.append(row)
        elif match.get("reject_reason"):
            rejected.append({
                "id": row.get("id"),
                "subject": row.get("subject"),
                "reason": match.get("reject_reason"),
            })

    if not matched:
        return {"ok": True, "matched_emails": 0, "issue_id": None, "message": "No matching emails found"}

    # Create or update issue
    signature_source = body.category if body.category and body.category != "Bug Report" else body.issue_title
    sig = f"{body.product_model}_{signature_source}".replace("/", "_").replace(" ", "_").replace(":", "_").lower()
    db.upsert_support_issue({
        "issue_signature": sig,
        "issue_title": f"{body.product_model} - {body.issue_title}",
        "issue_category": body.category,
        "product_model": body.product_model,
        "user_count": 0,
        "email_count": 0,
        "priority": "High",
        "status": "new_detected",
    })

    # Find the issue ID
    issues = db.get_support_issues(limit=1000)
    issue_id = None
    for iss in issues:
        if iss.get("issue_signature") == sig:
            issue_id = iss["id"]
            break

    candidate_count = 0
    if issue_id:
        candidate_count = db.upsert_issue_candidates(
            issue_id,
            matched,
            confidence=0.75,
            matched_by="fact_scan",
            matched_keywords=keywords,
        )

    unique_users = len({_extract_email(row.get("sender", "")) for row in matched if _extract_email(row.get("sender", ""))})

    return {
        "ok": True,
        "matched_count": len(matched),
        "matched_emails": len(matched),
        "candidate_count": candidate_count,
        "unique_user_count": unique_users,
        "rejected_count": len(rejected),
        "rejected_samples": rejected[:10],
        "issue_id": issue_id,
        "issue_signature": sig,
    }


@router.get("/auto-detect")
@router.post("/auto-detect")
def auto_detect_issues(
    days: int = Query(default=30, ge=1, le=365),
    min_users: int = Query(default=2, ge=1, le=100),
    auto_create: bool = Query(default=False),
    db=Depends(get_db),
):
    """
    Auto-detect issue clusters from recent emails.

    Groups emails by (product_model, intent) and identifies clusters
    with enough unique users to warrant creating an Issue bucket.

    If auto_create=True, detected issues are automatically upserted
    and matching emails are stored as review candidates.
    """
    result = db.auto_detect_issues(days=days, min_users=min_users)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["summary"])

    candidates = result.get("candidates", [])

    if auto_create and candidates:
        created = []
        for c in candidates:
            issue_id = db.upsert_support_issue({
                "issue_signature": c["issue_signature"],
                "issue_title": c["issue_title"],
                "issue_category": c["issue_category"],
                "product_model": c["product_model"],
                "priority": c["priority"],
                "status": "new_detected",
            })
            rows_by_id = {str(r.get("id")): r for r in db.get_emails(limit=5000)}
            matched = []
            email_facts = c.get("email_facts") or {}
            for eid in c.get("email_ids", []):
                if eid in rows_by_id:
                    row = dict(rows_by_id[eid])
                    if str(eid) in email_facts:
                        row["_issue_facts"] = email_facts[str(eid)]
                    matched.append(row)
            candidate_count = 0
            if issue_id and matched:
                candidate_count = db.upsert_issue_candidates(
                    issue_id,
                    matched,
                    confidence=0.85,
                    matched_by="auto_detect",
                    matched_keywords=[c.get("issue_category", "")],
                )
            created.append({
                "issue_signature": c["issue_signature"],
                "issue_id": issue_id,
                "candidate_emails": candidate_count,
            })
        result["created"] = created

    return result


def _extract_email(sender: str) -> str:
    import re
    m = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender or "")
    return m.group(0).lower() if m else ""
