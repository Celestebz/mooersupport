"""
REST API router for email automation triggers, scheduler control, and status.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends

from ..dependencies import get_db
from ..schemas import AutomationRunResult
from ..scheduler import scheduler_state, run_automation_sync

router = APIRouter(prefix="/automation", tags=["Automation"])

_PROJECT_DIR = Path(__file__).resolve().parent.parent


@router.post("/run", response_model=AutomationRunResult)
def run_automation_once():
    """
    Trigger a single manual automation run.
    Runs synchronously and returns the result.
    """
    import re

    start = time.time()
    result = run_automation_sync()
    elapsed = round(time.time() - start, 1)

    log_lines = []
    if "error" in result:
        log_lines.append(result["error"])
    else:
        log_lines.append(
            f"Processed: {result.get('processed', 0)}, "
            f"Drafted: {result.get('drafted', 0)}, "
            f"Errors: {result.get('errors', 0)}, "
            f"Elapsed: {elapsed}s"
        )

    return AutomationRunResult(
        success=result.get("success", False),
        processed=result.get("processed", 0),
        drafted=result.get("drafted", 0),
        errors=result.get("errors", 0),
        elapsed_seconds=elapsed,
        log_lines=log_lines,
    )


@router.get("/schedule")
def get_schedule():
    """Get the current state of the background scheduler."""
    return {
        "running": scheduler_state["running"],
        "interval_seconds": scheduler_state["interval"],
        "last_run": scheduler_state["last_run"],
        "next_run": scheduler_state["next_run"],
        "last_result": scheduler_state["last_result"],
        "total_runs": scheduler_state["total_runs"],
        "total_errors": scheduler_state["total_errors"],
    }


@router.post("/schedule/toggle")
def toggle_schedule():
    """Pause or resume the background scheduler."""
    scheduler_state["running"] = not scheduler_state["running"]
    return {
        "running": scheduler_state["running"],
        "message": "Scheduler " + ("resumed" if scheduler_state["running"] else "paused"),
    }


@router.post("/schedule/interval")
def set_schedule_interval(seconds: int = 60):
    """Change the scheduler interval (minimum 60 seconds)."""
    if seconds < 60:
        seconds = 60
    scheduler_state["interval"] = seconds
    return {
        "interval_seconds": seconds,
        "message": f"Interval set to {seconds}s ({seconds // 60} min)",
    }


@router.get("/status")
def get_automation_status(db=Depends(get_db)):
    """Get current processing status from recent logs."""
    logs = db.get_logs(limit=10)
    return {
        "recent_logs": [dict(row) for row in logs],
    }
