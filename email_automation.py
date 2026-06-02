#!/usr/bin/env python3
"""
Main script for the Mooer Email Support Automation System
This script: 
1. Checks the support@mooeraudio.com inbox periodically
2. Extracts relevant information from new emails
3. Generates professional English responses
4. Saves responses as drafts in the email account
"""

import logging
import os
import schedule
import time
from datetime import datetime
from dotenv import load_dotenv

# Import custom modules
from imap_handler import IMAPHandler
from content_extractor import ContentExtractor
from response_generator import ResponseGenerator
from database import DatabaseHandler

class EmailAutomation:
    """Main email automation class"""

    DONE_STATUSES = {'sent', 'drafted', 'forwarded_drafted', 'no_reply_needed', 'human_review'}
    RETRY_STATUSES = {'new', 'processing', 'failed_retry'}
    
    def __init__(self, config_path=None):
        """Initialize the email automation system"""
        # Set up logging
        self._setup_logging()
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing Mooer Email Automation System...")
        
        # Configuration
        self.config_path = config_path
        
        # Initialize components
        load_dotenv()
        self.imap_handler = IMAPHandler(config_path)
        self.content_extractor = ContentExtractor()
        
        # Initialize Database
        self.db = DatabaseHandler()
        
        # Set up paths for response generator
        templates_path = os.path.join(os.getcwd(), "售后模板", "Customer Service Email.txt")
        pdf_reader_path = os.path.join(os.getcwd(), "pdf_reader.py")
        product_manuals_path = os.path.join(os.getcwd(), "MOOER产品说明书")
        
        self.response_generator = ResponseGenerator(
            templates_path,
            pdf_reader_path,
            product_manuals_path
        )
        
        # Processing settings
        self.max_emails_per_run = int(os.getenv('MAX_EMAILS_PER_RUN', 20))
        self.rnd_forward_email = os.getenv('RND_FORWARD_EMAIL', 'wxk@mooeraudio.com')
        self.run_lock_path = os.path.join(os.getcwd(), "logs", "email_automation.lock")
        self._run_lock_fd = None
        
        # Legacy tracking files (migration handled by skipping if ID exists in DB)
        # We now rely on DB for deduplication and processing status
        
        self.logger.info("Email Automation System initialized successfully")

    def _is_final_skip_reason(self, reasoning, label=None):
        """Return True when a skipped email should not be retried."""
        text = f"{reasoning or ''} {label or ''}".lower()
        final_markers = (
            "non-product",
            "being processed",
            "known distributor",
            "distributor",
            "spam",
            "system notification",
            "invalid recipient address",
            "parse failed",
            "already has draft",
            "already sent",
            "already handled",
        )
        return any(marker in text for marker in final_markers)

    def _is_no_reply_intent(self, intent):
        """Return True for mail that should not receive an automatic reply."""
        return intent in {"Spam", "System Notification", "Gratitude"}

    def _route_non_product_status(self, intent):
        """Route non-product mail into either no-reply or human-review."""
        if self._is_no_reply_intent(intent):
            return "no_reply_needed", f"AI Intent: {intent}", f"AI Intent: {intent}"
        return "human_review", "Non-product email - requires human attention", "Non-Product - Human"

    def _acquire_run_lock(self):
        """Prevent concurrent bot runs from stepping on the same SQLite DB."""
        try:
            lock_dir = os.path.dirname(self.run_lock_path)
            if lock_dir and not os.path.exists(lock_dir):
                os.makedirs(lock_dir)

            if os.path.exists(self.run_lock_path):
                age_seconds = time.time() - os.path.getmtime(self.run_lock_path)
                if age_seconds < 3600:
                    self.logger.warning(f"Automation lock file exists, skipping run: {self.run_lock_path}")
                    return False
                try:
                    os.remove(self.run_lock_path)
                except Exception:
                    self.logger.warning("Stale lock file could not be removed; skipping run")
                    return False

            self._run_lock_fd = os.open(self.run_lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            payload = f"pid={os.getpid()}\nstarted={datetime.now().isoformat()}\n"
            os.write(self._run_lock_fd, payload.encode("utf-8"))
            return True
        except FileExistsError:
            self.logger.warning("Automation is already running elsewhere; skipping this run")
            return False
        except Exception as e:
            self.logger.error(f"Failed to acquire automation lock: {e}")
            return False

    def _release_run_lock(self):
        """Release the cross-process automation lock."""
        try:
            if self._run_lock_fd is not None:
                try:
                    os.close(self._run_lock_fd)
                finally:
                    self._run_lock_fd = None
            if os.path.exists(self.run_lock_path):
                os.remove(self.run_lock_path)
        except Exception as e:
            self.logger.warning(f"Failed to release automation lock: {e}")

    def _pre_classify_email(self, email):
        """Fast deterministic triage before spending AI tokens."""
        text = f"{email.get('subject', '')}\n{email.get('sender', '')}\n{email.get('body', '')[:1200]}".lower()
        sender = (email.get('sender') or '').lower()
        subject = (email.get('subject') or '').lower()

        bounce_markers = (
            'undelivered mail returned to sender',
            'delivery status notification',
            'mail delivery failed',
            'failure notice',
            'returned mail',
            'postmaster',
            'mailer-daemon',
            '退信',
        )
        if any(marker in text for marker in bounce_markers):
            return "no_reply_needed", "System bounce/delivery notification", "System Notification"

        marketing_markers = (
            'seo',
            'backlink',
            'guest post',
            'sponsored post',
            'content removal',
            'copyright claim',
            'collaboration proposal',
            'influencer',
            'partnership opportunity',
            'secure your hotel',
            'booth',
            'trade show',
            'newsletter',
            'unsubscribe',
        )
        if any(marker in text for marker in marketing_markers):
            return "human_review", "Marketing/partnership/non-support email", "Non-Product - Human"

        if sender.endswith('@mooeraudio.com>') or '@mooeraudio.com' in sender:
            if subject.startswith(('fwd:', 'fw:', '转发')):
                return "human_review", "Internal forwarded email requires human review", "Internal Forward"
            return "no_reply_needed", "Internal MOOER email - no customer reply", "Internal"

        return None

    def _is_invalid_draft_content(self, body):
        """Reject internal model/tool output before saving a customer draft."""
        if not body:
            return True

        lowered = body.lower()
        invalid_markers = (
            "tool_calls",
            "<tool_call",
            "dsml",
            "<｜｜dsml｜｜",
            "｜｜dsml｜｜",
            "searchproductmanual",
            "search_product_manual",
            "check_official_downloads",
            "get_firmware_update_guide",
            "escalate_to_human",
        )
        return any(marker in lowered for marker in invalid_markers)

    def _is_rnd_update_bug(self, email, email_info, clean_body):
        """Detect GE1000/GS1000 update bug reports that should go to R&D."""
        import re

        subject = email.get('subject', '') or ''
        model = email_info.get('product_model') or ''
        keywords = ' '.join(str(k) for k in email_info.get('keywords', []) or [])
        text = f"{subject}\n{model}\n{keywords}\n{clean_body or ''}"
        text_upper = text.upper()
        text_lower = text.lower()

        has_target_model = bool(
            re.search(r'(?<![A-Z0-9])GE1000(?![A-Z0-9])', text_upper)
            or re.search(r'(?<![A-Z0-9])GS1000(?![A-Z0-9])', text_upper)
        )
        if not has_target_model:
            return False

        update_bug_markers = (
            'update bug',
            'firmware bug',
            'latest update',
            'after update',
            'after updating',
            'update failed',
            'failed update',
            'firmware update',
            'updating firmware',
            'reinstall firmware',
            'factory reset',
            'bug with the latest update',
        )
        if any(marker in text_lower for marker in update_bug_markers):
            return True

        return ('update' in text_lower or 'firmware' in text_lower) and 'bug' in text_lower

    def _get_rnd_product_model(self, email, email_info, clean_body):
        """Return GE1000 or GS1000 for the R&D forward rule."""
        import re

        text = f"{email.get('subject', '')}\n{email_info.get('product_model') or ''}\n{clean_body or ''}".upper()
        if re.search(r'(?<![A-Z0-9])GE1000(?![A-Z0-9])', text):
            return 'GE1000'
        if re.search(r'(?<![A-Z0-9])GS1000(?![A-Z0-9])', text):
            return 'GS1000'
        return email_info.get('product_model') or 'GE1000/GS1000'

    def _build_rnd_forward_body(self, email, email_info, clean_body, product_model):
        """Build the internal draft for Leo/R&D."""
        attachments = email.get('attachments') or []
        if attachments:
            attachment_lines = []
            for item in attachments:
                if isinstance(item, dict):
                    filename = item.get('filename', 'Unknown attachment')
                    size = item.get('size', '')
                    attachment_lines.append(f"- {filename} {f'({size})' if size else ''}".strip())
                else:
                    attachment_lines.append(f"- {item}")
            attachments_text = '\n'.join(attachment_lines)
        else:
            attachments_text = 'None'

        key_issues = email_info.get('keywords') or []
        if key_issues:
            summary = '; '.join(str(item) for item in key_issues)
        else:
            summary = 'Customer reported an update/firmware bug. Please review the original email below.'

        return f"""Hi Leo,

This customer reported an update/firmware-related bug for {product_model}. Please help check whether this is a known issue or needs R&D follow-up.

Customer:
{email.get('sender', '')}

Subject:
{email.get('subject', '')}

Date:
{email.get('date', '')}

Product:
{product_model}

Issue summary:
{summary}

Attachments:
{attachments_text}

Original customer email:
---
{clean_body}
---

Best regards,
MOOER Support Bot"""

    def _build_rnd_customer_reply(self, product_model):
        """Build the customer acknowledgement draft for R&D-forwarded cases."""
        return f"""Dear customer,

Thank you for contacting MOOER Support.

We have received your report regarding the update issue with your {product_model}. We are sorry for the inconvenience this has caused.

Your case has been forwarded to our R&D / technical team for further checking. They will review the issue based on the details you provided, including the firmware/update behavior you described.

We will get back to you as soon as we receive further feedback from the technical team.

Best regards,
MOOER Support Team"""

    def _sync_email_status(self):
        """Sync IMAP unread status with database status"""
        import sqlite3
        conn = None
        try:
            # Get all unread emails from IMAP
            unread_emails = self.imap_handler.get_unread_emails(max_emails=500)
            unread_ids = set(e['id'] for e in unread_emails)

            if not unread_ids:
                self.logger.info("No unread IMAP emails found during sync")
                return

            conn = sqlite3.connect('mooer_support.db', timeout=30)
            conn.execute('PRAGMA busy_timeout = 30000')
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(unread_ids))

            # Already handled emails should not block the unread queue. Keep DB
            # status and clear the IMAP unread flag.
            cursor.execute(f'''
                SELECT id, status FROM emails
                WHERE id IN ({placeholders})
                AND status IN ("drafted", "sent", "forwarded_drafted", "no_reply_needed", "human_review")
            ''', list(unread_ids))
            handled_unread = cursor.fetchall()
            for email_id, status in handled_unread:
                if self.imap_handler.mark_as_read(email_id):
                    self.logger.info(f"Marked already {status} email as read: {email_id}")

            # skipped emails are retried unless the skip reason is a final
            # triage decision. This prevents stale/incorrect skipped rows from
            # permanently blocking unread customer emails.
            cursor.execute(f'''
                SELECT id, ai_reasoning, label FROM emails
                WHERE id IN ({placeholders}) AND status = "skipped"
            ''', list(unread_ids))
            skipped_unread = cursor.fetchall()
            retry_ids = []
            final_ids = []
            for email_id, reasoning, label in skipped_unread:
                if self._is_final_skip_reason(reasoning, label):
                    final_ids.append(email_id)
                else:
                    retry_ids.append(email_id)

            for email_id in final_ids:
                if self.imap_handler.mark_as_read(email_id):
                    self.logger.info(f"Marked final skipped email as read: {email_id}")

            if retry_ids:
                retry_placeholders = ','.join('?' * len(retry_ids))
                cursor.execute(
                    f'UPDATE emails SET status="new" WHERE id IN ({retry_placeholders})',
                    retry_ids
                )
                self.logger.info(f"Reset {len(retry_ids)} skipped unread emails for retry")
                conn.commit()

        except Exception as e:
            self.logger.error(f"Error syncing email status: {e}")
        finally:
            if conn:
                conn.close()
            self.imap_handler.disconnect_imap()
    def _setup_logging(self):
        """Set up logging configuration"""
        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(os.getcwd(), "logs")
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
        
        # Configure logging
        log_file = os.path.join(logs_dir, f"email_automation_{datetime.now().strftime('%Y%m%d')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    
    def process_emails(self):
        """Process new emails from the inbox"""
        self.logger.info("Starting email processing run...")
        self.db.log_event("INFO", "Starting email processing run", "automation")

        if not self._acquire_run_lock():
            return False

        # Sync email status before processing
        self._sync_email_status()

        try:
            # Connect to IMAP server
            if not self.imap_handler.connect_imap():
                self.logger.error("Failed to connect to IMAP server, skipping this run")
                self.db.log_event("ERROR", "Failed to connect to IMAP server", "automation")
                return False
            
            # Fetch a wider unread window because already-handled unread emails
            # can otherwise consume the whole per-run limit and starve older
            # emails that still need a draft.
            fetch_limit = max(self.max_emails_per_run * 5, 100)
            emails = self.imap_handler.get_unread_emails(max_emails=fetch_limit)
            
            if not emails:
                self.logger.info("No unread emails to process")
                self.imap_handler.disconnect_imap()
                return True
            
            # Process each email
            processed_this_run = 0
            for email in emails:
                email_id = email['id']
                if processed_this_run >= self.max_emails_per_run:
                    self.logger.info(f"Reached processing limit of {self.max_emails_per_run} emails")
                    break
                
                # Check if email has already been processed in DB.
                existing_email = self.db.get_email_by_id(email_id)
                if existing_email and existing_email['status'] in self.DONE_STATUSES:
                    self.logger.info(f"Skipping already processed email: {email['subject']} (ID: {email_id}, status: {existing_email['status']})")
                    self.imap_handler.mark_as_read(email_id)
                    continue

                if existing_email and existing_email['status'] == 'skipped' and self._is_final_skip_reason(existing_email.get('ai_reasoning'), existing_email.get('label')):
                    self.logger.info(f"Skipping already processed email: {email['subject']} (ID: {email_id}, status: {existing_email['status']})")
                    self.imap_handler.mark_as_read(email_id)
                    continue

                # Migration guard: older DB rows used IMAP sequence numbers,
                # so the same mailbox message may now appear with a new UID.
                # If an identical sender+subject+date already has a draft/sent
                # record, treat this UID as the same migrated message and clear
                # the unread flag. Do not skip new replies in the same thread.
                sender = email.get('sender', '')
                subject = email.get('subject', '')
                email_date = email.get('date', '')
                if sender and subject and email_date:
                    import sqlite3
                    conn = sqlite3.connect('mooer_support.db', timeout=30)
                    conn.execute('PRAGMA busy_timeout = 30000')
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT id, status FROM emails WHERE sender=? AND subject=? AND received_at=? AND status IN ('drafted', 'sent') LIMIT 1",
                        (sender, subject, email_date)
                    )
                    duplicate_handled = cursor.fetchone()
                    conn.close()
                    if duplicate_handled:
                        if not existing_email:
                            self.db.add_email({
                                'id': email_id,
                                'sender': email['sender'],
                                'subject': email['subject'],
                                'body': email['body'],
                                'date': email.get('date'),
                                'attachments': email.get('attachments', [])
                            })
                        self.db.update_email_status(
                            email_id,
                            'no_reply_needed',
                            reasoning=f"Already handled by {duplicate_handled[1]} record {duplicate_handled[0]}",
                            label="Already handled"
                        )
                        self.imap_handler.mark_as_read(email_id)
                        self.logger.info(f"Marked duplicate already-handled email as read: {subject} from {sender}")
                        continue

                self.logger.info(f"Processing email: {email['subject']} from {email['sender']} (ID: {email_id})")
                self.db.log_event("INFO", f"Processing email: {email['subject']}", "automation")
                processed_this_run += 1
                
                # Add to DB as 'new' if not exists
                if not existing_email:
                    self.db.add_email({
                        'id': email_id,
                        'sender': email['sender'],
                        'subject': email['subject'],
                        'body': email['body'],
                        'date': email.get('date'),
                        'attachments': email.get('attachments', [])
                    })
                self.db.update_email_status(email_id, 'processing', increment_attempts=True)
                
                try:
                    # Clean and extract content
                    clean_body = self.content_extractor.clean_email_content(email['body'])
                    email_content = f"Subject: {email['subject']}\n\n{clean_body}"

                    pre_classification = self._pre_classify_email(email)
                    if pre_classification:
                        status, reasoning, label = pre_classification
                        self.logger.info(f"Pre-classified email: {email['subject']} -> {status} ({reasoning})")
                        self.imap_handler.add_label(email_id, label)
                        self.db.update_email_status(email_id, status, reasoning=reasoning, label=label)
                        self.imap_handler.mark_as_read(email_id)
                        continue

                    # Extract relevant information using AI (pass cc_list and sender for smarter classification)
                    cc_list = email.get('cc_list', [])
                    email_info = self.content_extractor.extract_info(email_content, cc_list=cc_list, sender_email=email['sender'])
                    email_info['subject'] = email['subject']
                    email_info['body'] = clean_body

                    # Log AI Analysis Result to DB
                    intent = email_info.get("problem_category", "Technical Support")
                    email_type = email_info.get("email_type", "other")
                    self.db.update_email_ai_analysis(email_id, {
                        'intent': intent,
                        'sentiment': email_info.get('sentiment'),
                        'product_model': email_info.get('product_model')
                    })

                    self.logger.info(f"AI Classification - Model: {email_info.get('product_model')}, Intent: {intent}, Email Type: {email_type}, Sentiment: {email_info.get('sentiment')}")

                    # Check if email should be skipped based on AI email_type
                    should_skip = False

                    # 0. AI-Driven Email Type Classification (NEW)
                    if email_type == "being_processed":
                        self.logger.info(f"Detected email being processed: {email['subject']} from {email['sender']}")
                        self.imap_handler.add_label(email_id, 'Being processed')
                        self.db.update_email_status(email_id, 'no_reply_needed', reasoning="Email being processed - no reply needed", label="Being processed")
                        self.imap_handler.mark_as_read(email_id)
                        continue

                    if email_type == "non_product":
                        self.logger.info(f"Detected non-product email: {email['subject']} from {email['sender']}")
                        status, reasoning, label = self._route_non_product_status(intent)
                        self.imap_handler.add_label(email_id, label)
                        self.db.update_email_status(email_id, status, reasoning=reasoning, label=label)
                        self.imap_handler.mark_as_read(email_id)
                        continue

                    # Check for known distributors/Non-customer emails
                    known_distributors = [
                        "support@promusicals.com",
                        "sales16@mooeraudio.com",  # MOOER internal sales
                        "sales@mooeraudio.com",
                        "support@mooeraudio.com",
                        "sales@stringsandthings.co.uk",
                        "repairs@andertons.co.uk"
                    ]
                    sender_lower = email.get('sender', '').lower()

                    if any(dist in sender_lower for dist in known_distributors):
                        self.logger.info(f"Skipping email from known distributor: {email['sender']}")
                        self.imap_handler.add_label(email_id, 'Distributor - No Reply')
                        self.db.update_email_status(email_id, 'no_reply_needed', reasoning=f"Known distributor: {email['sender']}", label="Distributor - No Reply")
                        self.imap_handler.mark_as_read(email_id)
                        continue

                    # 1. AI-Driven Intent Triage (Spam, Gratitude, etc.)
                    if self._is_no_reply_intent(intent):
                        should_skip = True
                        self.logger.info(f"Skipping email based on AI Intent: {intent}")
                        self.db.update_email_status(email_id, 'no_reply_needed', reasoning=f"AI Intent: {intent}", label=f"AI Intent: {intent}")

                    if should_skip:
                        # Mark as read but don't generate response
                        self.imap_handler.mark_as_read(email_id)
                        self.logger.info(f"Marked email as read but skipped response: {email['subject']}")
                        continue

                    # 2. R&D forwarding rule for GE1000/GS1000 update bugs.
                    # This creates two drafts: one internal forward to Leo and
                    # one customer acknowledgement. Nothing is auto-sent.
                    if self._is_rnd_update_bug(email, email_info, clean_body):
                        product_model = self._get_rnd_product_model(email, email_info, clean_body)
                        target_address_field = email.get('reply_to') if email.get('reply_to') else email.get('sender', '')
                        recipient = self._extract_email_address(target_address_field)

                        if not recipient:
                            self.logger.error(f"Could not extract recipient email from: {target_address_field}")
                            self.imap_handler.add_label(email_id, 'Parse Failed - Needs Human')
                            self.db.update_email_status(email_id, 'human_review', reasoning="Invalid recipient address", label="Parse Failed")
                            self.imap_handler.mark_as_read(email_id)
                            continue

                        forward_subject = f"[R&D Forward] {product_model} update bug - {email.get('subject', '')}"
                        forward_body = self._build_rnd_forward_body(email, email_info, clean_body, product_model)
                        customer_reply = self._build_rnd_customer_reply(product_model)

                        forward_success = self.imap_handler.save_draft(
                            recipient=self.rnd_forward_email,
                            subject=forward_subject,
                            body=forward_body,
                            reply_mode=False
                        )
                        reply_success = self.imap_handler.save_draft(
                            recipient=recipient,
                            subject=email['subject'],
                            body=customer_reply,
                            original_msg_id=email.get('message_id'),
                            original_html=email.get('html_body'),
                            original_sender=email.get('sender'),
                            original_date=email.get('date')
                        )

                        if forward_success and reply_success:
                            self.imap_handler.mark_as_read(email_id)
                            self.db.update_email_status(
                                email_id,
                                'forwarded_drafted',
                                draft_body=customer_reply,
                                reasoning=f"R&D forward draft created for {self.rnd_forward_email}",
                                label="R&D Forwarded"
                            )
                            self.logger.info(f"Created R&D forward and customer acknowledgement drafts for: {email['subject']}")
                            self.db.log_event("INFO", f"R&D forwarded draft for: {email['subject']}", "automation")
                        else:
                            self.logger.error(f"Failed to create both R&D/customer drafts for: {email['subject']}")
                            self.db.log_event("ERROR", f"Failed R&D forward drafts for: {email['subject']}", "automation")
                        continue
                    
                    # Generate response
                    response_body = self.response_generator.generate_response(email_info, email_content)
                    
                    # Extract recipient email from Reply-To (preferred) or Sender field
                    target_address_field = email.get('reply_to') if email.get('reply_to') else email.get('sender', '')
                    recipient = self._extract_email_address(target_address_field)
                    
                    # Save as draft
                    if self._is_invalid_draft_content(response_body):
                        self.logger.error("Generated response contains internal tool-call markup or is empty; keeping email unread for retry")
                        self.db.update_email_status(
                            email_id,
                            'failed_retry',
                            reasoning="Invalid or empty AI draft content",
                            label="Retry - Bad Draft",
                            last_error="Invalid or empty AI draft content"
                        )
                        continue

                    if recipient and response_body:
                        # Use the new save_draft with HTML reply support
                        success = self.imap_handler.save_draft(
                            recipient=recipient,
                            subject=email['subject'],
                            body=response_body,
                            original_msg_id=email.get('message_id'),
                            original_html=email.get('html_body'),
                            original_sender=email.get('sender'),
                            original_date=email.get('date')
                        )
                        
                        if success:
                            # Mark email as read
                            self.imap_handler.mark_as_read(email_id)
                            # Update DB status
                            self.db.update_email_status(email_id, 'drafted', draft_body=response_body)
                            self.logger.info(f"Successfully drafted email: {email['subject']}")
                            self.db.log_event("INFO", f"Drafted response for: {email['subject']}", "automation")
                        else:
                            self.logger.error(f"Failed to save draft for email: {email['subject']}")
                            self.db.log_event("ERROR", f"Failed to save draft for: {email['subject']}", "automation")
                    else:
                        if not recipient:
                            self.logger.error(f"Could not extract recipient email from: {target_address_field}")
                            # Add a specific label so human can review this un-processable email
                            self.imap_handler.add_label(email_id, 'Parse Failed - Needs Human')
                            self.db.update_email_status(email_id, 'human_review', reasoning="Invalid recipient address", label="Parse Failed")
                            self.imap_handler.mark_as_read(email_id)  # Mark as read to avoid loop processing
                        elif not response_body:
                            # AI failed to generate response - keep unread for retry
                            self.logger.warning(f"Failed to generate response body - keeping email as unread for retry")
                            self.db.update_email_status(
                                email_id,
                                'failed_retry',
                                reasoning="No draft generated",
                                label="Retry - No Draft",
                                last_error="No draft generated"
                            )
                            # Do NOT mark as read
                        
                except Exception as e:
                    self.logger.error(f"Error processing email {email['subject']}: {e}", exc_info=True)
                    self.db.log_event("ERROR", f"Error processing email {email['subject']}: {e}", "automation")
                    # Do NOT mark as read - keep it unread so it will be retried next time
                    self.db.update_email_status(
                        email_id,
                        'failed_retry',
                        reasoning="Processing exception",
                        label="Retry - Exception",
                        last_error=str(e)
                    )
                    self.logger.warning(f"Keeping email {email['subject']} as unread for retry")
                    continue
            
            # Disconnect from IMAP server
            self.imap_handler.disconnect_imap()
            
            self.logger.info(f"Email processing run completed. Fetched {len(emails)} unread emails, processed {processed_this_run}.")
            return True
            
        except Exception as e:
            self.logger.error(f"Error in email processing run: {e}", exc_info=True)
            self.db.log_event("ERROR", f"Fatal error in run: {e}", "automation")
            # Ensure connection is closed
            try:
                self.imap_handler.disconnect_imap()
            except:
                pass
            return False
        finally:
            self._release_run_lock()
    
    def _extract_email_address(self, sender_string):
        """Extract email address from sender string"""
        try:
            import re
            # Extract email using regex
            match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender_string)
            if match:
                return match.group()
            return None
        except Exception as e:
            self.logger.error(f"Error extracting email address: {e}")
            return None
    
    def _load_processed_emails(self):
        """Load the list of processed email IDs from file"""
        processed = set()
        
        if os.path.exists(self.processed_emails_file):
            try:
                with open(self.processed_emails_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        email_id = line.strip()
                        if email_id:
                            processed.add(email_id)
            except Exception as e:
                self.logger.error(f"Error loading processed emails: {e}")
        
        self.logger.info(f"Loaded {len(processed)} processed email IDs")
        return processed
    
    def _save_processed_email(self, email_id):
        """Save an email ID to the processed emails file"""
        if email_id not in self.processed_emails:
            try:
                with open(self.processed_emails_file, 'a', encoding='utf-8') as f:
                    f.write(email_id + '\n')
                self.processed_emails.add(email_id)
                self.logger.debug(f"Added email {email_id} to processed list")
            except Exception as e:
                self.logger.error(f"Error saving processed email: {e}")

    def _load_processed_hashes(self):
        """Load processed email content hashes"""
        hashes = set()
        if os.path.exists(self.processed_hashes_file):
            try:
                with open(self.processed_hashes_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        h = line.strip()
                        if h:
                            hashes.add(h)
            except Exception as e:
                self.logger.error(f"Error loading processed hashes: {e}")
        return hashes

    def _save_processed_hash(self, email_hash):
        """Save an email hash to the processed hashes file"""
        if email_hash and email_hash not in self.processed_hashes:
            try:
                with open(self.processed_hashes_file, 'a', encoding='utf-8') as f:
                    f.write(email_hash + '\n')
                self.processed_hashes.add(email_hash)
            except Exception as e:
                self.logger.error(f"Error saving processed hash: {e}")

    def _calculate_email_hash(self, sender, subject, body):
        """Calculate MD5 hash of email content for deduplication"""
        try:
            import hashlib
            # Normalize content: lowercase and remove whitespace
            # Use sender + subject + body (limit body to first 500 chars to avoid signature diffs if any)
            # Actually, using full body is safer for "identical" emails.
            # If the user sends "Help" and then "Help" later, they are identical.
            content = f"{sender}|{subject}|{body}".lower()
            # Remove all whitespace to handle formatting differences
            content = "".join(content.split())
            
            return hashlib.md5(content.encode('utf-8', errors='ignore')).hexdigest()
        except Exception as e:
            self.logger.error(f"Error calculating email hash: {e}")
            return None
    
    def start_scheduling(self, interval_minutes=30):
        """Start the scheduling service"""
        self.logger.info(f"Starting email automation service with interval: {interval_minutes} minutes")
        
        # Schedule the job
        schedule.every(interval_minutes).minutes.do(self.process_emails)
        
        # Run the job immediately on startup
        self.process_emails()
        
        # Run the scheduler loop
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            self.logger.info("Email automation service stopped by user")
        except Exception as e:
            self.logger.error(f"Unexpected error in scheduler loop: {e}", exc_info=True)
        finally:
            self.logger.info("Email automation service shutting down")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Mooer Email Support Automation')
    parser.add_argument('--once', action='store_true', help='Run once and exit instead of scheduling')
    parser.add_argument('--interval', type=int, default=30, help='Scheduling interval in minutes')
    
    args = parser.parse_args()
    
    # Create and start the email automation system
    automation = EmailAutomation()
    
    if args.once:
        automation.logger.info("Running in single-pass mode")
        automation.process_emails()
    else:
        automation.start_scheduling(interval_minutes=args.interval)
