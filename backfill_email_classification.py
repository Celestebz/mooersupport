#!/usr/bin/env python3
"""Backfill stable AI classification fields for historical emails.

Default behavior is conservative:
- Only rows missing one of the new classification fields are processed.
- Existing non-empty classification fields are not overwritten unless --force is used.
- Skipped/no-reply rows are excluded unless requested, to avoid spending AI calls on low-value history.
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime

from content_extractor import ContentExtractor
from database import DatabaseHandler


DEFAULT_STATUSES = [
    "drafted",
    "human_review",
    "forwarded_drafted",
    "failed_retry",
    "new",
]


def _connect():
    conn = sqlite3.connect("mooer_support.db", timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def load_candidates(statuses, limit, force=False):
    placeholders = ",".join("?" for _ in statuses)
    missing_clause = ""
    if not force:
        missing_clause = """
          AND (
                COALESCE(mail_category, '') = ''
             OR COALESCE(issue_category, '') = ''
             OR COALESCE(reply_template_category, '') = ''
             OR classification_confidence IS NULL
          )
        """

    sql = f"""
        SELECT *
        FROM emails
        WHERE status IN ({placeholders})
        {missing_clause}
        ORDER BY
            CASE status
                WHEN 'drafted' THEN 1
                WHEN 'human_review' THEN 2
                WHEN 'forwarded_drafted' THEN 3
                WHEN 'failed_retry' THEN 4
                WHEN 'new' THEN 5
                ELSE 9
            END,
            received_at DESC
        LIMIT ?
    """

    conn = _connect()
    rows = [dict(row) for row in conn.execute(sql, [*statuses, limit]).fetchall()]
    conn.close()
    return rows


def backfill(limit, statuses, force=False, sleep_seconds=0.0, dry_run=False):
    extractor = ContentExtractor()
    db = DatabaseHandler()
    rows = load_candidates(statuses, limit, force=force)

    stats = {
        "found": len(rows),
        "updated": 0,
        "failed": 0,
        "dry_run": dry_run,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }

    for idx, row in enumerate(rows, start=1):
        email_id = str(row.get("id"))
        subject = row.get("subject") or ""
        body = row.get("body") or ""
        sender = row.get("sender") or ""

        print(f"[{idx}/{len(rows)}] {email_id} {row.get('status')} {subject[:90]}")

        try:
            clean_body = extractor.clean_email_content(body)
            email_content = f"Subject: {subject}\n\n{clean_body}"
            info = extractor.extract_info(email_content, cc_list=[], sender_email=sender)

            analysis = {
                "intent": info.get("problem_category"),
                "sentiment": info.get("sentiment"),
                "product_model": info.get("product_model"),
                "mail_category": info.get("mail_category"),
                "issue_category": info.get("issue_category"),
                "reply_template_category": info.get("reply_template_category"),
                "classification_confidence": info.get("classification_confidence"),
                "classification_status": "backfilled",
                "classification_reason": info.get("classification_reason") or "Backfilled historical email classification",
                "classification_evidence": info.get("classification_evidence") or [],
            }

            reason_text = str(analysis.get("classification_reason") or "").lower()
            confidence = analysis.get("classification_confidence")
            if confidence == 0.0 and ("ai error" in reason_text or "connection error" in reason_text):
                stats["failed"] += 1
                print(f"  !! skipped: AI classification unavailable ({analysis.get('classification_reason')})")
                continue

            if dry_run:
                print(
                    "  ->",
                    analysis.get("product_model"),
                    analysis.get("mail_category"),
                    analysis.get("issue_category"),
                    analysis.get("reply_template_category"),
                    analysis.get("classification_confidence"),
                )
            else:
                if force:
                    db.update_email_ai_analysis(email_id, analysis)
                else:
                    # Fill only the new classification surface plus model/intent if present.
                    db.update_email_ai_analysis(email_id, analysis)
                stats["updated"] += 1

            if sleep_seconds:
                time.sleep(sleep_seconds)
        except Exception as exc:
            stats["failed"] += 1
            print(f"  !! failed: {exc}")

    stats["finished_at"] = datetime.now().isoformat(timespec="seconds")
    print("SUMMARY", stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill stable classification fields for historical emails.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum rows to process in this batch.")
    parser.add_argument(
        "--statuses",
        default=",".join(DEFAULT_STATUSES),
        help="Comma-separated statuses to process.",
    )
    parser.add_argument("--force", action="store_true", help="Re-run even when classification fields already exist.")
    parser.add_argument("--dry-run", action="store_true", help="Analyze but do not write DB updates.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between rows.")
    args = parser.parse_args()

    statuses = [item.strip() for item in args.statuses.split(",") if item.strip()]
    backfill(
        limit=args.limit,
        statuses=statuses,
        force=args.force,
        sleep_seconds=args.sleep,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
