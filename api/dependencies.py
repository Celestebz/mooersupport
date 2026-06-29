"""
Shared dependencies for the API layer.
Provides DatabaseHandler, EmailAnalyzer, config, etc. as FastAPI dependencies.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

# Ensure parent dir is on path so we can import project modules
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

import yaml
from database import DatabaseHandler
from email_analyzer import EmailAnalyzer


@lru_cache()
def get_config() -> dict:
    """Load config.yml once and cache."""
    config_path = _PARENT / "config.yml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_db: DatabaseHandler | None = None


def get_db() -> DatabaseHandler:
    """Get or create the shared DatabaseHandler instance."""
    global _db
    if _db is None:
        db_path = os.environ.get("MOOER_DB_PATH", str(_PARENT / "mooer_support.db"))
        _db = DatabaseHandler(db_path=db_path)
    return _db


_analyzer: EmailAnalyzer | None = None


def get_analyzer() -> EmailAnalyzer:
    """Get or create the shared EmailAnalyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = EmailAnalyzer(config_path=str(_PARENT / "config.yml"))
    return _analyzer
