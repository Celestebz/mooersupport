"""
API client for MOOER Support REST API.
Thin wrapper around the FastAPI endpoints -- one method per endpoint.
Uses only stdlib (urllib), no extra dependencies.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Optional


class APIError(Exception):
    """Raised when the API returns a non-2xx status."""


class APIClient:
    """Synchronous HTTP client for the MOOER Support API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8100", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, json_data: dict = None, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{qs}"

        body = None
        headers = {}
        if json_data:
            body = json.dumps(json_data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise APIError(f"HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise APIError(f"Connection failed: {e.reason}") from e

    def _get(self, path: str, **params) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json_data: dict = None, **params) -> dict:
        return self._request("POST", path, json_data=json_data, params=params)

    def _patch(self, path: str, json_data: dict = None) -> dict:
        return self._request("PATCH", path, json_data=json_data)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    # ── Health ──

    def health(self) -> bool:
        """Check if API is reachable."""
        try:
            self._request("GET", "/health")
            return True
        except Exception:
            return False

    # ── Emails ──

    def list_emails(self, status: str = None, limit: int = 100, offset: int = 0) -> dict:
        return self._get("/api/v1/emails", status=status, limit=limit, offset=offset)

    def get_email(self, email_id: str) -> dict:
        return self._get(f"/api/v1/emails/{email_id}")

    def get_email_thread(self, email_id: str, limit: int = 20) -> dict:
        return self._get(f"/api/v1/emails/{email_id}/thread", limit=limit)

    def search_emails(self, **kwargs) -> dict:
        return self._get("/api/v1/emails/search", **kwargs)

    def update_email_status(self, email_id: str, **kwargs) -> dict:
        return self._patch(f"/api/v1/emails/{email_id}/status", kwargs)

    def update_email_ai_analysis(self, email_id: str, intent: str = "", sentiment: str = "", product_model: str = "") -> dict:
        return self._patch(f"/api/v1/emails/{email_id}/ai-analysis", {
            "intent": intent, "sentiment": sentiment, "product_model": product_model
        })

    # ── Issues ──

    def list_issues(self, limit: int = 200) -> dict:
        return self._get("/api/v1/issues", limit=limit)

    def get_issue(self, issue_id: int) -> dict:
        return self._get(f"/api/v1/issues/{issue_id}")

    def get_issue_emails(self, issue_id: int, limit: int = 500) -> dict:
        return self._get(f"/api/v1/issues/{issue_id}/emails", limit=limit)

    def get_issue_candidates(self, issue_id: int, status: str = None, limit: int = 500) -> dict:
        return self._get(f"/api/v1/issues/{issue_id}/candidates", status=status, limit=limit)

    def review_issue_candidate(self, issue_id: int, email_id: str, status: str, review_note: str = "") -> dict:
        return self._patch(f"/api/v1/issues/{issue_id}/candidates/{email_id}", {
            "status": status,
            "review_note": review_note,
        })

    def scan_issue(self, product_model: str, issue_title: str = "", keywords: list = None, category: str = "Bug Report") -> dict:
        return self._post("/api/v1/issues/scan", {
            "product_model": product_model,
            "issue_title": issue_title,
            "keywords": keywords or [],
            "category": category,
        })

    def update_issue(self, issue_id: int, **kwargs) -> dict:
        return self._patch(f"/api/v1/issues/{issue_id}", kwargs)

    def auto_detect_issues(self, days: int = 30, min_users: int = 2, auto_create: bool = False) -> dict:
        """Auto-detect issue clusters from recent emails."""
        return self._post(
            "/api/v1/issues/auto-detect",
            days=days,
            min_users=min_users,
            auto_create="true" if auto_create else "false",
        )

    def sync_daily_report(self, report_json_path: str = "") -> dict:
        """Sync issues from daily report JSON. If no path given, reads from default location."""
        data = {}
        if report_json_path:
            data["report_path"] = report_json_path
        return self._post("/api/v1/issues/sync-daily", data)

    # ── Logs ──

    def list_logs(self, limit: int = 100) -> dict:
        return self._get("/api/v1/logs", limit=limit)

    # ── Drafts ──

    def list_drafts(self) -> list:
        return self._get("/api/v1/drafts")

    def send_draft(self, draft_uid: str, data: dict = None) -> dict:
        return self._post(f"/api/v1/drafts/{draft_uid}/send", data or {})

    def delete_draft(self, draft_uid: str) -> dict:
        return self._delete(f"/api/v1/drafts/{draft_uid}")

    # ── Automation ──

    def trigger_automation(self) -> dict:
        return self._post("/api/v1/automation/run")

    def automation_status(self) -> dict:
        return self._get("/api/v1/automation/status")

    def schedule_status(self) -> dict:
        return self._get("/api/v1/automation/schedule")

    def schedule_toggle(self) -> dict:
        return self._post("/api/v1/automation/schedule/toggle")

    def schedule_set_interval(self, seconds: int) -> dict:
        return self._post("/api/v1/automation/schedule/interval", {"seconds": seconds})

    # ── Part Prices ──

    def list_prices(self) -> dict:
        return self._get("/api/v1/prices")

    def get_model_prices(self, product_model: str) -> dict:
        return self._get(f"/api/v1/prices/model/{product_model}")

    def create_price(self, product_model: str, part_name: str, price: float, currency: str = "USD") -> dict:
        return self._post("/api/v1/prices", {
            "product_model": product_model,
            "part_name": part_name,
            "price": price,
            "currency": currency,
        })

    def update_price(self, price_id: int, **kwargs) -> dict:
        return self._patch(f"/api/v1/prices/{price_id}", kwargs)

    def delete_price(self, price_id: int) -> dict:
        return self._delete(f"/api/v1/prices/{price_id}")

    # ── Reply Templates ──

    def list_templates(self, status: str = None, limit: int = 200) -> dict:
        return self._get("/api/v1/templates", status=status, limit=limit)

    def create_template(self, name: str, category: str, body: str,
                        product_model: str = "", issue_category: str = "",
                        language: str = "en") -> dict:
        return self._post("/api/v1/templates", {
            "name": name,
            "category": category,
            "body": body,
            "product_model": product_model,
            "issue_category": issue_category,
            "language": language,
        })

    def update_template(self, template_id: int, **kwargs) -> dict:
        return self._patch(f"/api/v1/templates/{template_id}", kwargs)

    def delete_template(self, template_id: int) -> dict:
        return self._delete(f"/api/v1/templates/{template_id}")

    # ── Knowledge Base ──

    def knowledge_summary(self) -> dict:
        return self._get("/api/v1/knowledge/summary")

    def list_knowledge_documents(self, knowledge_type: str = None, status: str = None, limit: int = 500) -> dict:
        return self._get(
            "/api/v1/knowledge/documents",
            knowledge_type=knowledge_type,
            status=status,
            limit=limit,
        )

    def sync_knowledge(self) -> dict:
        return self._post("/api/v1/knowledge/sync")
