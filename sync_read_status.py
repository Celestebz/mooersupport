"""
同步邮箱已读状态
检查数据库中已处理的邮件，在邮箱中标记为已读
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if "--force" not in sys.argv:
    print("DEPRECATED: sync_read_status.py bulk-marks mailbox messages as read.")
    print("Run with --force only after confirming it will not hide actionable mail.")
    sys.exit(1)

from database import DatabaseHandler
from imap_handler import IMAPHandler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    db = DatabaseHandler()
    imap = IMAPHandler()

    try:
        # 连接 IMAP
        if not imap.connect_imap():
            logger.error("Failed to connect to IMAP")
            return

        # 获取所有已处理邮件（在数据库中状态为 sent 或 skipped）
        emails = db.get_emails(limit=500)

        sent_or_skipped = [e for e in emails if e['status'] in ('sent', 'skipped')]
        logger.info(f"Found {len(sent_or_skipped)} processed emails in DB")

        # 检查每封邮件在邮箱中的状态
        marked_read = 0
        for email in sent_or_skipped:
            email_id = email['id']
            # 检查邮件是否在邮箱中仍为未读
            # 如果 IMAP UID 有效，标记为已读
            try:
                imap.mark_as_read(email_id)
                marked_read += 1
                if marked_read % 10 == 0:
                    logger.info(f"Marked {marked_read} emails as read...")
            except Exception as e:
                logger.warning(f"Could not mark email {email_id} as read: {e}")

        logger.info(f"Done! Marked {marked_read} emails as read in mailbox")

    finally:
        imap.disconnect_imap()


if __name__ == "__main__":
    main()
