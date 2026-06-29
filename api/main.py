"""
MOOER 客服系统 API
=================
MOOER 客服邮件管理系统统一 API。

接口资源：
  /api/v1/emails      — 邮件查询与管理
  /api/v1/issues      — 售后问题队列与扫描
  /api/v1/analysis    — AI 问题分析与报表
  /api/v1/automation  — 邮件处理任务控制
  /api/v1/drafts      — 邮箱草稿管理
  /api/v1/logs        — 系统日志

启动：  uvicorn api.main:app --host 0.0.0.0 --port 8100 --reload
文档：  http://localhost:8100/docs
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    emails_router, issues_router, analysis_router,
    automation_router, drafts_router, logs_router,
    prices_router, templates_router, knowledge_router,
)
from .scheduler import scheduler_state, run_automation_sync

logger = logging.getLogger("mooer-api")


# ── Background scheduler ──────────────────────────────────────────────

async def _automation_scheduler_loop():
    """Background asyncio loop — triggers email automation every N seconds."""
    from datetime import datetime, timezone

    # Wait briefly on startup before first poll so the API can finish warming up.
    try:
        startup_delay = int(os.getenv("EMAIL_POLL_STARTUP_DELAY_SECONDS", "5"))
    except ValueError:
        startup_delay = 5
    await asyncio.sleep(max(startup_delay, 0))

    while True:
        if scheduler_state["running"]:
            now = datetime.now(timezone.utc)
            scheduler_state["last_run"] = now.isoformat()
            scheduler_state["total_runs"] += 1
            scheduler_state["last_result"] = None

            try:
                result = await asyncio.to_thread(run_automation_sync)
                scheduler_state["last_result"] = result
                if not result.get("success"):
                    scheduler_state["total_errors"] += 1
                logger.info(
                    "Scheduled run #%d: processed=%d drafted=%d errors=%d",
                    scheduler_state["total_runs"],
                    result.get("processed", 0),
                    result.get("drafted", 0),
                    result.get("errors", 0),
                )
            except Exception as e:
                scheduler_state["total_errors"] += 1
                scheduler_state["last_result"] = {"success": False, "error": str(e)}
                logger.error("Scheduled run #%d failed: %s", scheduler_state["total_runs"], e)

        # Calculate next run time
        from datetime import datetime as dt, timedelta
        scheduler_state["next_run"] = (
            dt.now() + timedelta(seconds=scheduler_state["interval"])
        ).isoformat()

        await asyncio.sleep(scheduler_state["interval"])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start background scheduler on app startup, clean up on shutdown."""
    task = asyncio.create_task(_automation_scheduler_loop())
    logger.info("Email automation scheduler started (every %ds)", scheduler_state["interval"])
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Email automation scheduler stopped")


app = FastAPI(
    title="MOOER 客服系统 API",
    description="客服邮件管理与售后问题跟踪 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — allow local dev and dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers under /api/v1
API_PREFIX = "/api/v1"
app.include_router(emails_router, prefix=API_PREFIX)
app.include_router(issues_router, prefix=API_PREFIX)
app.include_router(analysis_router, prefix=API_PREFIX)
app.include_router(automation_router, prefix=API_PREFIX)
app.include_router(drafts_router, prefix=API_PREFIX)
app.include_router(logs_router, prefix=API_PREFIX)
app.include_router(prices_router, prefix=API_PREFIX)
app.include_router(templates_router, prefix=API_PREFIX)
app.include_router(knowledge_router, prefix=API_PREFIX)


@app.get("/")
def root():
    """API root — redirect to docs."""
    return {
        "service": "MOOER 客服系统 API",
        "version": "1.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "scheduler": {
            "running": scheduler_state["running"],
            "interval_seconds": scheduler_state["interval"],
            "last_run": scheduler_state["last_run"],
            "next_run": scheduler_state["next_run"],
            "total_runs": scheduler_state["total_runs"],
        },
    }
