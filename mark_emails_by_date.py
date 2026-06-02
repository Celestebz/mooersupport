"""
Mark emails as read/unread based on date
- Yesterday and today: mark as UNREAD
- Other dates: mark as READ
"""
import sys
import os
from datetime import datetime, timedelta

if "--force" not in sys.argv:
    print("DEPRECATED: mark_emails_by_date.py changes mailbox read/unread flags in bulk.")
    print("Run with --force only if you intentionally want to override bot state.")
    sys.exit(1)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from imap_handler import IMAPHandler
import yaml
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def mark_emails_by_date():
    """Mark emails: yesterday/today = unread, others = read"""

    # Load config
    with open('config.yml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    imap_handler = IMAPHandler()
    imap_handler.connect_imap()

    try:
        # Select inbox
        status, _ = imap_handler.imap.select('INBOX')
        if status != 'OK':
            logger.error("Failed to select inbox")
            return

        # Get all emails (limit to recent 1000 to avoid timeout)
        status, response = imap_handler.imap.search(None, 'ALL')
        if status != 'OK':
            logger.error("Failed to search emails")
            return

        email_ids = response[0].split()
        logger.info(f"Found {len(email_ids)} total emails")

        # Calculate date boundaries
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        unread_count = 0
        read_count = 0

        # Process each email
        for email_id in email_ids:
            if isinstance(email_id, bytes):
                email_id = email_id.decode('utf-8')

            # Fetch email headers to get date
            status, msg_data = imap_handler.imap.fetch(email_id, '(FLAGS INTERNALDATE)')
            if status != 'OK':
                continue

            try:
                internal_date = msg_data[0]
                if isinstance(internal_date, tuple):
                    internal_date = internal_date[1]

                # Parse the internal date
                if isinstance(internal_date, bytes):
                    internal_date_str = internal_date.decode('utf-8')
                else:
                    internal_date_str = str(internal_date)

                # IMAP internal date format: "DD-Mon-YYYY HH:MM:SS +ZZZZ"
                try:
                    email_date = datetime.strptime(internal_date_str.split(' +')[0], '%d-%b-%Y %H:%M:%S')
                    email_date = email_date.replace(hour=0, minute=0, second=0, microsecond=0)
                except:
                    # Fallback: use today
                    email_date = today

                # Check flags for current read status
                flags = msg_data[0]
                if isinstance(flags, tuple):
                    flags = flags[0]
                flags_str = flags.decode('utf-8') if isinstance(flags, bytes) else str(flags)

                is_seen = '\\Seen' in flags_str

                # Determine target status
                if email_date >= yesterday:  # Yesterday or today
                    target_unread = True
                else:
                    target_unread = False

                # Only change if status is different
                should_change = (target_unread and is_seen) or (not target_unread and not is_seen)

                if should_change:
                    if target_unread:
                        # Mark as unread (remove Seen flag)
                        imap_handler.imap.store(email_id, '-FLAGS', '\\Seen')
                        unread_count += 1
                    else:
                        # Mark as read (add Seen flag)
                        imap_handler.imap.store(email_id, '+FLAGS', '\\Seen')
                        read_count += 1

            except Exception as e:
                logger.error(f"Error processing email {email_id}: {e}")
                continue

        logger.info(f"\n=== Summary ===")
        logger.info(f"Marked as UNREAD: {unread_count} (yesterday/today)")
        logger.info(f"Marked as READ: {read_count} (older)")

    finally:
        imap_handler.disconnect_imap()

if __name__ == "__main__":
    mark_emails_by_date()
