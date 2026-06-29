"""
Pydantic schemas for MOOER Support API.
All request/response models live here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# Email schemas
# ============================================================

class EmailSummary(BaseModel):
    """Lightweight email in list responses."""
    id: str
    message_id: str = ""
    sender: str = ""
    sender_email: str = ""
    subject: str = ""
    received_at: str = ""
    status: str = ""
    intent: str = ""
    sentiment: str = ""
    product_model: str = ""
    label: str = ""
    has_attachment: bool = False


class EmailDetail(EmailSummary):
    """Full email with body and AI analysis."""
    body: str = ""
    analysis_json: Optional[dict] = None
    draft_body: str = ""
    knowledge_citations: str = ""
    reasoning: str = ""
    retry_count: int = 0
    last_error: str = ""
    thread_id: str = ""
    in_reply_to: str = ""


class EmailStatusUpdate(BaseModel):
    status: Optional[str] = None
    draft_body: Optional[str] = None
    reasoning: Optional[str] = None
    label: Optional[str] = None
    last_error: Optional[str] = None
    knowledge_citations: Optional[list[dict]] = None
    increment_attempts: bool = False


class EmailAIAnalysis(BaseModel):
    intent: str = ""
    sentiment: str = ""
    product_model: str = ""


class EmailSearchParams(BaseModel):
    product_model: Optional[str] = None
    keywords: Optional[str] = None
    since_date: Optional[str] = None
    before_date: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=100, le=1000)


# ============================================================
# Support Issue schemas
# ============================================================

class SupportIssueSummary(BaseModel):
    id: int
    issue_signature: str = ""
    issue_title: str = ""
    issue_category: str = ""
    product_model: str = ""
    user_count: int = 0
    email_count: int = 0
    status: str = ""
    priority: str = ""
    rnd_status: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""


class SupportIssueDetail(SupportIssueSummary):
    rnd_notes: str = ""
    solution_summary: str = ""
    final_reply_template: str = ""


class SupportIssueCreate(BaseModel):
    issue_signature: str
    issue_title: str
    issue_category: str = ""
    product_model: str = ""
    user_count: int = 0
    email_count: int = 0
    priority: str = "medium"
    status: str = "open"


class SupportIssueUpdate(BaseModel):
    status: Optional[str] = None
    rnd_status: Optional[str] = None
    rnd_notes: Optional[str] = None
    solution_summary: Optional[str] = None
    final_reply_template: Optional[str] = None


class ScanIssueRequest(BaseModel):
    product_model: str
    issue_title: str = ""
    keywords: list[str] = []
    category: str = "Bug Report"


class IssueEmailLink(BaseModel):
    email_ids: list[str]
    confidence: float = 1.0
    matched_by: str = "api"


class IssueCandidateReview(BaseModel):
    status: str
    review_note: Optional[str] = None


# ============================================================
# Analysis schemas
# ============================================================

class QueryIssuesRequest(BaseModel):
    product_model: str
    issue_description: str
    issue_keywords: Optional[list[str]] = None
    date_range: Optional[str] = None  # "YYYY-MM-DD..YYYY-MM-DD"
    max_emails: int = Field(default=500, le=1000)
    batch_size: int = Field(default=20, le=50)


class IssueMatchRequest(BaseModel):
    email_data: dict
    product_model: str
    issue_description: str
    issue_keywords: list[str] = []


class AnalysisStatsRequest(BaseModel):
    matched_emails: list[dict]


# ============================================================
# Customer schemas
# ============================================================

class CustomerInfo(BaseModel):
    email: str
    name: str = ""
    seen_at: str = ""
    tags: str = ""
    email_count: int = 0
    total_emails: int = 0


# ============================================================
# Draft schemas
# ============================================================

class DraftSummary(BaseModel):
    uid: str
    subject: str = ""
    to: str = ""
    date: str = ""
    body_preview: str = ""


class DraftDetail(DraftSummary):
    body: str = ""
    sender: str = ""
    id: str = ""
    message_id: str = ""
    in_reply_to: str = ""
    references: str = ""


class DraftSendRequest(BaseModel):
    to_addrs: Optional[list[str]] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    original_sender: Optional[str] = None
    original_date: Optional[str] = None


# ============================================================
# Automation schemas
# ============================================================

class AutomationRunResult(BaseModel):
    success: bool
    processed: int = 0
    drafted: int = 0
    errors: int = 0
    elapsed_seconds: float = 0
    log_lines: list[str] = []


# ============================================================
# Template schemas
# ============================================================

class TemplateInfo(BaseModel):
    id: int
    name: str
    category: str = ""
    body: str = ""
    language: str = "English"
    active: bool = True


class TemplateCreate(BaseModel):
    name: str
    category: str = ""
    body: str
    language: str = "English"
    active: bool = True


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    body: Optional[str] = None
    language: Optional[str] = None
    active: Optional[bool] = None


# ============================================================
# Part Price schemas
# ============================================================

class PartPriceInfo(BaseModel):
    id: int
    product_model: str
    part_name: str
    price: float
    currency: str = "USD"
    updated_at: str = ""


class PartPriceCreate(BaseModel):
    product_model: str
    part_name: str
    price: float
    currency: str = "USD"


class PartPriceUpdate(BaseModel):
    product_model: Optional[str] = None
    part_name: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None


# ============================================================
# Reply Template schemas (for new API)
# ============================================================

class ReplyTemplateInfo(BaseModel):
    id: int
    name: str = ""
    category: str = ""
    product_model: str = ""
    issue_category: str = ""
    language: str = "en"
    body: str = ""
    status: str = "active"
    updated_at: str = ""


class ReplyTemplateCreate(BaseModel):
    name: str
    category: str = ""
    product_model: str = ""
    issue_category: str = ""
    language: str = "en"
    body: str


class ReplyTemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    product_model: Optional[str] = None
    issue_category: Optional[str] = None
    language: Optional[str] = None
    body: Optional[str] = None
    status: Optional[str] = None


# ============================================================
# Common response wrapper
# ============================================================

class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int = 0


class ErrorResponse(BaseModel):
    detail: str
    error_code: str = "internal_error"
