#!/usr/bin/env python3
"""Generic support-issue scanner.

Commands:
  auto-detect     Scan all recent emails for issue clusters across all products.
  scan            Keyword-based scan for a specific product + issue.
  sync-daily      Sync issues from daily report JSON (today_issues.json).
"""

import argparse
import json
import re
import sys

# Fix GBK encoding issues on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from database import DatabaseHandler


def _extract_email(sender):
    """Extract email address from 'Name <email>' format."""
    m = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender or "")
    return m.group(0).lower() if m else ""


def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── auto-detect ──────────────────────────────────────────────────────

def cmd_auto_detect(db, args):
    result = db.auto_detect_issues(days=args.days, min_users=args.min_users)
    _print_json(result)

    if args.create and result.get("candidates"):
        created = 0
        for c in result["candidates"]:
            issue_id = db.upsert_support_issue({
                "issue_signature": c["issue_signature"],
                "issue_title": c["issue_title"],
                "issue_category": c["issue_category"],
                "product_model": c["product_model"],
                "priority": c["priority"],
                "status": "new_detected",
            })
            if issue_id:
                # Link matching emails
                rows = db.get_emails(limit=5000)
                matched = [
                    r for r in rows
                    if (r.get("product_model") or "").strip().upper() == c["product_model"].upper()
                ]
                db.link_emails_to_issue(issue_id, matched, confidence=0.85, matched_by="auto_detect_cli")
                created += 1
                print("  Created issue #{}: {} | linked {} emails".format(
                    issue_id, c["issue_title"], len(matched)))
        print("\nAuto-created {} issues from {} candidates.".format(created, len(result["candidates"])))
        return 0

    return 0 if not result.get("error") else 1


# ── scan ─────────────────────────────────────────────────────────────

def cmd_scan(db, args):
    """Keyword-based issue scan for a specific product."""
    keywords = args.keywords if args.keywords else [args.issue_title]

    sig = "{}_{}".format(
        args.product.upper().replace(" ", "_"),
        args.issue_title.replace(" ", "_").lower()
    )
    title = "{} - {}".format(args.product.upper(), args.issue_title)

    # Create issue
    issue_id = db.upsert_support_issue({
        "issue_signature": sig,
        "issue_title": title,
        "issue_category": args.category,
        "product_model": args.product.upper(),
        "priority": args.priority,
        "status": "new_detected",
    })

    if not issue_id:
        print("Failed to create/update issue bucket.", file=sys.stderr)
        return 1

    # Search matching emails
    rows = db.get_emails(limit=5000)
    matched = []
    for row in rows:
        model = (row.get("product_model") or "").upper()
        if args.product.upper() not in model and args.product.upper() not in (row.get("subject") or "").upper():
            continue
        combined = "{} {}".format(row.get("subject") or "", row.get("body") or "").lower()
        if any(kw.lower() in combined for kw in keywords):
            matched.append(row)

    if matched:
        db.link_emails_to_issue(issue_id, matched, confidence=0.9, matched_by="cli_scan")
        unique_users = len({_extract_email(row.get("sender") or "") for row in matched})
    else:
        unique_users = 0

    result = {
        "issue_id": issue_id,
        "issue_signature": sig,
        "matched_emails": len(matched),
        "unique_users": unique_users,
        "keywords_used": keywords,
    }
    _print_json(result)
    return 0


# ── sync-daily ───────────────────────────────────────────────────────

def cmd_sync_daily(db, args):
    """Sync issues from a daily report JSON file.

    Supports two formats:
    1. today_db_issues.json — list of issue summaries with product_model, issue_types, etc.
    2. today_db.json — list of email entries (will auto-group by product_model)
    """
    path = args.report_path
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("File not found: {}".format(path), file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print("Invalid JSON: {}".format(e), file=sys.stderr)
        return 1

    # Detect format
    if isinstance(data, dict):
        # Format: {"period": "...", "issues": [...]} or {"emails": [...]}
        if "issues" in data:
            issues = data["issues"]
        elif "emails" in data:
            issues = data["emails"]
        else:
            print("Unrecognized dict format. Expected 'issues' or 'emails' key.", file=sys.stderr)
            return 1
    elif isinstance(data, list) and len(data) > 0:
        first = data[0]
        # Format 1: issue summary list (has product_model + issue_types or issues)
        if "product_model" in first and ("issue_types" in first or "issues" in first):
            issues = data
        # Format 2: email list (has id, from, subject, body) — auto-group
        else:
            from collections import defaultdict
            grouped = defaultdict(lambda: {"count": 0, "users": set(), "subjects": [], "intents": set()})
            for em in data:
                model = (em.get("product_model") or "").strip()
                if not model or model == "Unknown":
                    continue
                g = grouped[model]
                g["count"] += 1
                sender = _extract_email(em.get("from") or "")
                if sender:
                    g["users"].add(sender)
                g["subjects"].append(em.get("subject") or "")
                if em.get("ai_intent"):
                    g["intents"].add(em["ai_intent"])
            issues = []
            for model, g in sorted(grouped.items()):
                issues.append({
                    "product_model": model,
                    "email_count": g["count"],
                    "unique_users": len(g["users"]),
                    "issue_types": list(g["intents"])[:3] or ["Unclassified"],
                    "sample_subjects": g["subjects"][:3],
                })
    else:
        print("Empty or unrecognized report format.", file=sys.stderr)
        return 1

    synced = []
    for item in issues:
        model = (item.get("product_model") or "").strip()
        if not model:
            continue

        issue_types = item.get("issue_types") or item.get("issues") or ["Unclassified"]
        title = "{} - {} ({} users)".format(
            model,
            issue_types[0] if issue_types else "Auto-detected",
            item.get("unique_users", item.get("user_count", 0)),
        )
        sig = "{}_{}".format(
            model.lower().replace(" ", "_"),
            (issue_types[0] if issue_types else "auto").lower().replace(" ", "_").replace("/", "_")[:40]
        )

        issue_id = db.upsert_support_issue({
            "issue_signature": sig,
            "issue_title": title,
            "issue_category": issue_types[0] if issue_types else "Unclassified",
            "product_model": model,
            "priority": "High" if item.get("email_count", item.get("count", 0)) >= 3 else "Medium",
            "status": "new_detected",
        })
        synced.append({"issue_id": issue_id, "title": title, "signature": sig})
        print("  Synced issue #{}: {}".format(issue_id, title))

    result = {
        "synced_count": len(synced),
        "issues": synced,
        "source": path,
    }
    _print_json(result)
    return 0


# ── main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scan support emails into issue buckets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  issue_scanner.py auto-detect --days 7
  issue_scanner.py scan GS1000 "balance output" --keywords balance XLR firmware
  issue_scanner.py sync-daily "Daily Report/today_db_issues.json"
        """,
    )
    parser.add_argument("--db", default="mooer_support.db", help="SQLite database path.")

    sub = parser.add_subparsers(dest="command", help="Sub-command")

    # auto-detect
    p_auto = sub.add_parser("auto-detect", help="Auto-detect issue clusters from all products")
    p_auto.add_argument("--days", type=int, default=30, help="Look back N days (default: 30)")
    p_auto.add_argument("--min-users", type=int, default=2, help="Min unique users for a cluster (default: 2)")
    p_auto.add_argument("--create", action="store_true", help="Auto-create issues and link emails")

    # scan
    p_scan = sub.add_parser("scan", help="Keyword-based scan for a specific product + issue")
    p_scan.add_argument("product", help="Product model, e.g. GS1000 or GE300")
    p_scan.add_argument("issue_title", help="Short title, e.g. 'balance output after firmware update'")
    p_scan.add_argument("--keywords", nargs="+", help="Keywords to search in subject+body")
    p_scan.add_argument("--category", default="Bug Report", help="Issue category (default: Bug Report)")
    p_scan.add_argument("--priority", default="High", help="Priority: P0, High, Medium, Low")

    # sync-daily
    p_sync = sub.add_parser("sync-daily", help="Sync issues from daily report JSON")
    p_sync.add_argument("report_path", help="Path to today_db_issues.json or today_db.json")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    db = DatabaseHandler(args.db)

    if args.command == "auto-detect":
        return cmd_auto_detect(db, args)
    elif args.command == "scan":
        return cmd_scan(db, args)
    elif args.command == "sync-daily":
        return cmd_sync_daily(db, args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
