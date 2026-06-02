#!/usr/bin/env python3
"""Audit local support-bot state without changing mailbox or database data."""

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")


BAD_DRAFT_MARKERS = (
    "tool_calls",
    "dsml",
    "searchproductmanual",
    "search_product_manual",
    "check_official_downloads",
    "get_firmware_update_guide",
)


def main():
    conn = sqlite3.connect("mooer_support.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("== Status counts ==")
    for row in cursor.execute("SELECT status, COUNT(*) AS count FROM emails GROUP BY status ORDER BY count DESC"):
        print(f"{row['status']}: {row['count']}")

    print("\n== Label counts ==")
    for row in cursor.execute("SELECT COALESCE(label, '<null>') AS label, COUNT(*) AS count FROM emails GROUP BY label ORDER BY count DESC LIMIT 20"):
        print(f"{row['label']}: {row['count']}")

    print("\n== Drafts containing internal/tool markup ==")
    bad_conditions = " OR ".join(["LOWER(COALESCE(draft_body, '')) LIKE ?" for _ in BAD_DRAFT_MARKERS])
    params = [f"%{marker}%" for marker in BAD_DRAFT_MARKERS]
    for row in cursor.execute(
        f"SELECT id, status, subject FROM emails WHERE {bad_conditions} ORDER BY CAST(id AS INTEGER) DESC",
        params,
    ):
        print(f"{row['id']} [{row['status']}] {row['subject']}")

    print("\n== Repeated sender+subject groups ==")
    for row in cursor.execute(
        """
        SELECT sender, subject, COUNT(*) AS count, GROUP_CONCAT(id) AS ids, GROUP_CONCAT(status) AS statuses
        FROM emails
        GROUP BY sender, subject
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """
    ):
        print(f"{row['count']}x | {row['sender']} | {row['subject']} | ids={row['ids']} | statuses={row['statuses']}")

    conn.close()


if __name__ == "__main__":
    main()
