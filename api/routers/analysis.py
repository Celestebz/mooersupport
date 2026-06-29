"""
REST API router for analysis and reporting.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_analyzer
from ..schemas import QueryIssuesRequest, IssueMatchRequest, AnalysisStatsRequest

router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.post("/query-issues")
def query_issues(body: QueryIssuesRequest, analyzer=Depends(get_analyzer)):
    """
    Run a full issue query: search DB + IMAP, then AI-match candidates.
    Returns matched emails and stats.
    """
    result = analyzer.query_issues(
        product_model=body.product_model,
        issue_description=body.issue_description,
        issue_keywords=body.issue_keywords,
        date_range=body.date_range,
        max_emails=body.max_emails,
        batch_size=body.batch_size,
    )
    return result


@router.post("/issue-match")
def ai_analyze_issue_match(body: IssueMatchRequest, analyzer=Depends(get_analyzer)):
    """
    Single-email AI matching: returns whether this email matches the described issue.
    """
    result = analyzer.ai_analyze_issue_match(
        email_data=body.email_data,
        product_model=body.product_model,
        issue_description=body.issue_description,
        issue_keywords=body.issue_keywords,
    )
    return result


@router.post("/stats")
def generate_analysis_stats(body: AnalysisStatsRequest, analyzer=Depends(get_analyzer)):
    """Generate aggregated stats from a list of matched emails."""
    stats = analyzer.generate_stats(body.matched_emails)
    return stats
