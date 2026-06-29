"""
Background scheduler state and sync runner.
Shared between main.py (lifespan loop) and routers/automation.py (control endpoints).
No circular imports — both import from here.
"""
from __future__ import annotations

import subprocess
import sys
import re
import time
import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment."""
    try:
        value = int(os.getenv(name, "").strip())
        return value if value > 0 else default
    except Exception:
        return default

# ── Shared state ──
scheduler_state: dict = {
    "running": True,      # can be toggled via API
    "interval": _env_int("EMAIL_POLL_INTERVAL_SECONDS", 60),
    "last_run": None,     # ISO timestamp of last run
    "next_run": None,     # ISO timestamp of next scheduled run
    "last_result": None,  # summary of last run
    "total_runs": 0,
    "total_errors": 0,
}


def run_automation_sync() -> dict:
    """Run email_automation.py --once synchronously. Returns result dict."""
    project_dir = Path(__file__).resolve().parent.parent
    automation_script = project_dir / "email_automation.py"
    if not automation_script.exists():
        return {"success": False, "error": f"Script not found: {automation_script}"}

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(automation_script), "--once"],
            capture_output=True, text=True, timeout=300,
            cwd=str(project_dir),
        )
        elapsed = round(time.time() - start, 1)
        output = result.stdout + "\n" + result.stderr

        processed = drafted = errors = 0
        for line in output.splitlines():
            if "processed" in line.lower():
                m = re.search(r'(\d+)\s+processed', line)
                if m:
                    processed = int(m.group(1))
            if "draft" in line.lower():
                m = re.search(r'(\d+)\s+draft', line)
                if m:
                    drafted = int(m.group(1))
            if "error" in line.lower():
                m = re.search(r'(\d+)\s+error', line)
                if m:
                    errors = int(m.group(1))

        return {
            "success": result.returncode == 0,
            "processed": processed,
            "drafted": drafted,
            "errors": errors,
            "elapsed_seconds": elapsed,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timed out after 300s"}
    except Exception as e:
        return {"success": False, "error": str(e)}
