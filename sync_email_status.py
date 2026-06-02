#!/usr/bin/env python3
"""
修复 IMAP 未读邮件和数据库状态不同步的问题
"""
import sqlite3
import sys
import os

if "--force" not in sys.argv:
    print("DEPRECATED: sync_email_status.py can reset processed emails and cause duplicate drafts.")
    print("Run with --force only if you have reviewed the current state-machine rules.")
    sys.exit(1)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from imap_handler import IMAPHandler


def sync_email_status():
    print("开始同步邮件状态...")

    # Get all emails from IMAP
    imap = IMAPHandler()
    unread_emails = imap.get_unread_emails(max_emails=500)
    unread_ids = set(e['id'] for e in unread_emails)

    print(f"IMAP 未读邮件数量: {len(unread_ids)}")

    # Connect to DB
    conn = sqlite3.connect('mooer_support.db')
    cursor = conn.cursor()

    # Check DB status
    cursor.execute('SELECT status, COUNT(*) FROM emails GROUP BY status')
    print("\n当前数据库状态:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")

    # Find emails that are:
    # 1. In IMAP unread, but DB status is drafted/skipped/sent (should process again)
    cursor.execute('SELECT id, subject, status FROM emails WHERE status IN ("drafted", "sent", "skipped")')
    to_reprocess = []
    for row in cursor.fetchall():
        email_id = row[0]
        if email_id in unread_ids:
            to_reprocess.append(row)

    print(f"\n需要重新处理的邮件 (IMAP未读 + DB已处理): {len(to_reprocess)}")
    for row in to_reprocess[:10]:
        print(f"  ID: {row[0]}, Subject: {row[1][:40]}, Status: {row[2]}")

    # Reset status for these emails to 'new'
    if to_reprocess:
        email_ids = [row[0] for row in to_reprocess]
        placeholders = ','.join('?' * len(email_ids))
        cursor.execute(f'UPDATE emails SET status="new" WHERE id IN ({placeholders})', email_ids)
        conn.commit()
        print(f"\n已重置 {len(email_ids)} 封邮件状态为 'new'")

    # Also check: emails in DB but NOT in IMAP unread (可能已被处理或删除)
    cursor.execute('SELECT id, status FROM emails WHERE status="new"')
    new_emails = cursor.fetchall()

    not_in_imap = []
    for row in new_emails:
        if row[0] not in unread_ids:
            not_in_imap.append(row)

    print(f"\n数据库状态为 new 但不在 IMAP 未读的邮件: {len(not_in_imap)}")
    # 这些邮件可能是已读但数据库没更新，标记为 skipped
    if not_in_imap:
        email_ids = [row[0] for row in not_in_imap]
        placeholders = ','.join('?' * len(email_ids))
        cursor.execute(f'UPDATE emails SET status="skipped", ai_reasoning="Not in IMAP unread (possibly read manually)" WHERE id IN ({placeholders})', email_ids)
        conn.commit()
        print(f"已标记 {len(email_ids)} 封邮件为 skipped")

    conn.close()
    imap.disconnect_imap()

    print("\n同步完成!")


if __name__ == "__main__":
    sync_email_status()
