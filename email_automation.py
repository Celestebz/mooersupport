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
import re
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
        
        # 模板已迁移至数据库
        pdf_reader_path = os.path.join(os.getcwd(), "pdf_reader.py")
        product_manuals_path = os.path.join(os.getcwd(), "MOOER产品说明书")

        self.response_generator = ResponseGenerator(
            None,
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
            "human review",
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

    def _is_being_processed(self, email, cc_list):
        """Detect internal team emails that are being forwarded/CC'd for info.
        These should not receive an auto-reply."""
        if not cc_list:
            return False

        sender = email.get('sender', '').lower()
        cc_lower = [c.lower() for c in cc_list]

        # Internal MOOER domain in CC indicates internal discussion
        has_internal_cc = any('mooeraudio.com' in c for c in cc_lower)
        # Internal MOOER sender forwarding to support
        is_internal_sender = 'mooeraudio.com' in sender
        # Subject indicates forward
        subject = email.get('subject', '').lower()
        is_forward = subject.startswith(('fwd:', 'fw:', '转发'))

        return (has_internal_cc and is_internal_sender) or (is_internal_sender and is_forward)

    def _acquire_run_lock(self):
        """Prevent concurrent bot runs from stepping on the same SQLite DB."""
        try:
            lock_dir = os.path.dirname(self.run_lock_path)
            if lock_dir and not os.path.exists(lock_dir):
                os.makedirs(lock_dir)

            if os.path.exists(self.run_lock_path):
                if not self._clear_stale_run_lock_if_safe():
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

    def _read_run_lock_pid(self):
        """Return the PID recorded in the lock file, or None if unreadable."""
        try:
            with open(self.run_lock_path, "r", encoding="utf-8") as lock_file:
                for line in lock_file:
                    match = re.match(r"\s*pid\s*=\s*(\d+)\s*$", line)
                    if match:
                        return int(match.group(1))
        except Exception as e:
            self.logger.warning(f"Could not read automation lock file; falling back to age check: {e}")
        return None

    def _is_pid_running(self, pid):
        """Return True if a process with pid appears to still be running."""
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception as e:
            self.logger.warning(f"Could not check lock PID {pid}; falling back to age check: {e}")
            return None

    def _clear_stale_run_lock_if_safe(self):
        """Remove dead/stale lock files. Return True when a new lock can be tried."""
        pid = self._read_run_lock_pid()
        if pid:
            is_running = self._is_pid_running(pid)
            if is_running is True:
                self.logger.warning(
                    f"Automation lock is held by active process {pid}; skipping run: {self.run_lock_path}"
                )
                return False
            if is_running is False:
                try:
                    os.remove(self.run_lock_path)
                    self.logger.warning(f"Removed stale automation lock for dead process {pid}: {self.run_lock_path}")
                    return True
                except Exception as e:
                    self.logger.warning(f"Dead-process lock could not be removed; skipping run: {e}")
                    return False

        self.logger.warning("Automation lock file has no usable PID; falling back to age check")
        age_seconds = time.time() - os.path.getmtime(self.run_lock_path)
        if age_seconds < 3600:
            self.logger.warning(f"Automation lock file exists and is not stale yet; skipping run: {self.run_lock_path}")
            return False
        try:
            os.remove(self.run_lock_path)
            self.logger.warning(f"Removed stale automation lock older than 1 hour: {self.run_lock_path}")
            return True
        except Exception as e:
            self.logger.warning(f"Stale lock file could not be removed; skipping run: {e}")
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

        if "@promusicals.com" in sender:
            return "no_reply_needed", "Known distributor domain: promusicals.com", "Distributor - No Reply"

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

    def _precheck_email_flags(self, email, cc_list=None):
        """Collect deterministic risk flags before AI classification.

        These flags are evidence and guardrails only. They must not directly
        decide that a customer gets no reply.
        """
        text = f"{email.get('subject', '')}\n{email.get('sender', '')}\n{email.get('body', '')[:1200]}".lower()
        sender = (email.get('sender') or '').lower()
        subject = (email.get('subject') or '').lower()
        cc_list = cc_list or []
        flags = []

        def add_flag(code, reason, confidence=0.8):
            flags.append({
                "code": code,
                "reason": reason,
                "confidence": confidence,
            })

        bounce_markers = (
            'undelivered mail returned to sender',
            'delivery status notification',
            'mail delivery failed',
            'failure notice',
            'returned mail',
            'postmaster',
            'mailer-daemon',
        )
        if any(marker in text for marker in bounce_markers):
            add_flag("suspected_system_notification", "System bounce/delivery notification", 0.95)

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
            add_flag("suspected_marketing_or_spam", "Marketing/partnership/non-support keywords", 0.75)

        if sender.endswith('@mooeraudio.com>') or '@mooeraudio.com' in sender:
            if subject.startswith(('fwd:', 'fw:')):
                add_flag("suspected_internal_forward", "Internal MOOER forwarded email", 0.9)
            else:
                add_flag("suspected_internal_sender", "Internal MOOER sender", 0.85)

        if self._is_being_processed(email, cc_list):
            add_flag("suspected_being_processed", "Internal CC/forward suggests team handling", 0.85)

        known_distributors = (
            "@promusicals.com",
            "sales16@mooeraudio.com",
            "sales@mooeraudio.com",
            "support@mooeraudio.com",
            "sales@stringsandthings.co.uk",
            "repairs@andertons.co.uk",
        )
        if any(dist in sender for dist in known_distributors):
            add_flag("suspected_distributor", f"Known distributor/internal sender: {email.get('sender', '')}", 0.85)

        auto_reply_markers = (
            "automatic reply",
            "auto-reply",
            "out of office",
            "out-of-office",
            "vacation response",
            "do not reply",
        )
        if any(marker in text for marker in auto_reply_markers):
            add_flag("suspected_auto_reply", "Automatic reply markers found", 0.8)

        if not flags:
            return {"flags": [], "reason": "", "max_confidence": 0.0}

        return {
            "flags": flags,
            "reason": "; ".join(flag["reason"] for flag in flags),
            "max_confidence": max(flag["confidence"] for flag in flags),
        }

    def _safe_confidence(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _safe_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y"}
        return bool(value)

    def _classification_route(self, email_info, precheck):
        """Route using AI classification first and precheck flags as guardrails."""
        intent = email_info.get("problem_category") or "Other"
        mail_category = email_info.get("mail_category") or "unclassified"
        issue_category = email_info.get("issue_category") or "unknown_issue"
        confidence = self._safe_confidence(email_info.get("classification_confidence"))
        needs_review = self._safe_bool(email_info.get("needs_human_review"))
        flags = precheck.get("flags", []) if precheck else []
        flag_codes = {flag.get("code") for flag in flags}

        product_intents = {"Technical Support", "Firmware Update", "Warranty/Repair"}
        product_mail_categories = {
            "technical_support",
            "firmware_update",
            "warranty_repair",
            "parts_purchase",
            "registration_account",
        }
        nonreply_intents = {"Spam", "System Notification"}
        nonreply_mail_categories = {"spam_irrelevant", "system_notification"}
        source_risk_flags = {
            "suspected_internal_sender",
            "suspected_internal_forward",
            "suspected_being_processed",
            "suspected_distributor",
            "suspected_auto_reply",
        }

        is_product_issue = intent in product_intents or mail_category in product_mail_categories
        is_ai_no_reply = intent in nonreply_intents or mail_category in nonreply_mail_categories
        low_confidence = confidence < 0.65

        reason_parts = [
            f"AI intent={intent}",
            f"mail_category={mail_category}",
            f"issue_category={issue_category}",
            f"confidence={confidence:.2f}",
        ]
        if precheck and precheck.get("reason"):
            reason_parts.append(f"precheck={precheck.get('reason')}")
        if email_info.get("classification_reason"):
            reason_parts.append(f"AI reason={email_info.get('classification_reason')}")

        if is_ai_no_reply:
            allowed_no_reply_flags = {"suspected_system_notification", "suspected_marketing_or_spam"}
            if low_confidence or needs_review or (flag_codes - allowed_no_reply_flags):
                return "human_review", "AI No-Reply Conflict - Human", "needs_review", "; ".join(reason_parts)
            return "no_reply_needed", f"AI Intent: {intent}", "ignored", "; ".join(reason_parts)

        if is_product_issue:
            if flag_codes & source_risk_flags:
                return "human_review", "AI Product Issue + Source Risk", "needs_review", "; ".join(reason_parts)
            if low_confidence or needs_review:
                return "human_review", "Low Confidence - Human", "needs_review", "; ".join(reason_parts)
            return "draft", "AI Product Issue", "auto_confirmed", "; ".join(reason_parts)

        if intent == "Gratitude" or mail_category == "customer_followup_ack":
            return "human_review", "Customer Follow-up - Human", "needs_review", "; ".join(reason_parts)

        if low_confidence or needs_review:
            return "human_review", "Low Confidence - Human", "needs_review", "; ".join(reason_parts)

        return "human_review", "Non-Product - Human", "needs_review", "; ".join(reason_parts)

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

    def _build_internal_check_acknowledgement(self):
        return (
            "Dear customer,\n\n"
            "Thank you for contacting MOOER Support.\n\n"
            "We have received your question. I could not find a confirmed answer in our current support knowledge base, "
            "so I have forwarded your case to our support team for further checking. We will confirm the details internally "
            "and get back to you as soon as possible.\n\n"
            "Best regards,\n"
            "MOOER Support Team"
        )

    def _issue_slug(self, value, fallback="unknown"):
        text = str(value or "").lower()
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text[:80] or fallback

    def _knowledge_gap_title(self, email, email_info):
        product = (email_info.get("product_model") or "Unknown product").strip()
        keywords = email_info.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        summary = "; ".join(str(item).strip() for item in keywords[:2] if str(item).strip())
        if not summary:
            summary = re.sub(r"\s+", " ", email.get("subject") or "").strip()
        if not summary:
            summary = "Unanswered support question"
        return f"Knowledge gap: {product} - {summary}"[:180]

    def _record_knowledge_gap_issue(self, email_id, email, email_info, reason):
        """Create/update an issue bucket for a KB miss and link this email."""
        product = (email_info.get("product_model") or "Unknown").strip() or "Unknown"
        issue_key = (
            email_info.get("issue_fingerprint")
            or email_info.get("issue_category")
            or email.get("subject")
            or email_id
        )
        if str(issue_key).strip().lower() in {"unknown_issue", "unclassified", "none"}:
            issue_key = email.get("subject") or email_id

        signature = "knowledge_gap_{}_{}".format(
            self._issue_slug(product),
            self._issue_slug(issue_key, fallback=str(email_id)),
        )
        issue_id = self.db.upsert_support_issue({
            "product_model": product,
            "issue_title": self._knowledge_gap_title(email, email_info),
            "issue_category": "knowledge_gap",
            "issue_signature": signature,
            "status": "new_detected",
            "priority": "Medium",
            "rnd_status": "needs_review",
            "rnd_notes": reason or "Knowledge base did not contain a confirmed answer",
        })
        if issue_id:
            self.db.link_emails_to_issue(
                issue_id,
                [{
                    "id": email_id,
                    "sender": email.get("sender"),
                    "received_at": email.get("received_at") or email.get("date"),
                }],
                confidence=0.75,
                matched_by="knowledge_gap_escalation",
            )
        return issue_id

    def _is_rnd_update_bug(self, email, email_info, clean_body):
        """Detect unresolved GE1000/GS1000 update bug reports that should go to R&D."""
        import re

        product = (email_info.get('product_model') or '').strip().upper()
        issue_category = (email_info.get('issue_category') or '').strip().lower()
        if product == 'GS1000' and issue_category == 'gs1000_balance_output_issue':
            return False

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
        """Build the internal forward body for Leo/R&D.

        Returns a short intro only. The original email content and attachments
        are handled by save_draft in forward mode (original_html + attachments).
        """
        key_issues = email_info.get('keywords') or []
        if key_issues:
            summary = '; '.join(str(item) for item in key_issues)
        else:
            summary = 'update/firmware-related bug'

        sender = email.get('sender', 'Unknown')
        subject = email.get('subject', '')

        return f"""Hi Leo,

Forwarding a bug report from a {product_model} customer ({sender}):

  Subject: {subject}
  Issue: {summary}

Please check if this is a known issue or needs an R&D follow-up. Original email below.

Thanks,
MOOER Support

---------- Forwarded message ---------
From: {sender}
Date: {email.get('date', '')}
Subject: {subject}
To: support@mooeraudio.com

{clean_body}"""


    def _build_rnd_customer_reply(self, product_model):
        """Build the customer acknowledgement draft for R&D-forwarded cases."""
        return f"""Dear customer,

Thank you for contacting MOOER Support.

We have received your report regarding the update issue with your {product_model}. We are sorry for the inconvenience this has caused.

Your case has been forwarded to our R&D / technical team for further checking. They will review the issue based on the details you provided, including the firmware/update behavior you described.

We will get back to you as soon as we receive further feedback from the technical team.

Best regards,
MOOER Support Team"""

    def _issue_template_citation(self, issue):
        """Build internal citation metadata for drafts created from a solved issue."""
        if not issue:
            return []
        issue_id = issue.get("id")
        title = issue.get("issue_title") or issue.get("title") or f"Issue #{issue_id}"
        excerpt = issue.get("final_reply_template") or issue.get("solution_summary") or ""
        return [{
            "knowledge_type": "issue_solution",
            "title": title,
            "source": f"support_issues#{issue_id}" if issue_id else "support_issues",
            "section": "final_reply_template",
            "chunk_id": None,
            "excerpt": excerpt[:320],
        }]

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
                                'message_id': email.get('message_id', ''),
                                'in_reply_to': email.get('in_reply_to', ''),
                                'references': email.get('references', ''),
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
                        'message_id': email.get('message_id', ''),
                        'in_reply_to': email.get('in_reply_to', ''),
                        'references': email.get('references', ''),
                        'attachments': email.get('attachments', [])
                    })
                self.db.update_email_status(email_id, 'processing', increment_attempts=True)
                
                try:
                    # Clean and extract content
                    clean_body = self.content_extractor.clean_email_content(email['body'])
                    email_content = f"Subject: {email['subject']}\n\n{clean_body}"

                    # Extract relevant information using AI (pass cc_list and sender for smarter classification)
                    cc_list = email.get('cc_list', [])
                    precheck = self._precheck_email_flags(email, cc_list=cc_list)
                    email_info = self.content_extractor.extract_info(email_content, cc_list=cc_list, sender_email=email['sender'])
                    email_info['subject'] = email['subject']
                    email_info['body'] = clean_body
                    email_info['attachments'] = email.get('attachments', [])
                    email_info['precheck_flags'] = precheck.get('flags', [])
                    email_info['precheck_reason'] = precheck.get('reason', '')

                    route_status, route_label, classification_status, route_reason = self._classification_route(email_info, precheck)

                    # Log AI Analysis Result to DB
                    intent = email_info.get("problem_category", "Technical Support")
                    self.db.update_email_ai_analysis(email_id, {
                        'intent': intent,
                        'sentiment': email_info.get('sentiment'),
                        'product_model': email_info.get('product_model'),
                        'mail_category': email_info.get('mail_category'),
                        'issue_category': email_info.get('issue_category'),
                        'reply_template_category': email_info.get('reply_template_category'),
                        'classification_confidence': email_info.get('classification_confidence'),
                        'classification_status': classification_status,
                        'classification_reason': route_reason,
                        'classification_evidence': email_info.get('classification_evidence', []),
                        'issue_facts': email_info.get('issue_facts'),
                        'issue_fingerprint': email_info.get('issue_fingerprint'),
                        'precheck_flags': precheck.get('flags', []),
                        'precheck_reason': precheck.get('reason', ''),
                    })

                    self.logger.info(
                        "AI Classification - Model: %s, Intent: %s, Mail: %s, Issue: %s, Route: %s",
                        email_info.get('product_model'),
                        intent,
                        email_info.get('mail_category'),
                        email_info.get('issue_category'),
                        route_status,
                    )

                    thread_context = self.db.get_email_thread_context(email_id, limit=20) or {}
                    email_info['conversation_context'] = thread_context

                    if route_status in {"no_reply_needed", "human_review"}:
                        self.logger.info(f"Routing email: {email['subject']} -> {route_status} ({route_reason})")
                        self.imap_handler.add_label(email_id, route_label)
                        self.db.update_email_status(email_id, route_status, reasoning=route_reason, label=route_label)
                        self.imap_handler.mark_as_read(email_id)
                        continue

                    solved_issue = self.db.find_issue_final_reply_template(
                        email_info.get('product_model'),
                        email_info.get('issue_category'),
                        email_info.get('issue_fingerprint')
                    )
                    if not solved_issue:
                        linked_issue = thread_context.get('linked_issue') if isinstance(thread_context, dict) else None
                        if linked_issue and linked_issue.get('final_reply_template'):
                            solved_issue = linked_issue
                    if solved_issue:
                        response_body = solved_issue.get('final_reply_template') or ''
                        target_address_field = email.get('reply_to') if email.get('reply_to') else email.get('sender', '')
                        recipient = self._extract_email_address(target_address_field)

                        if recipient and response_body:
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
                                self.db.link_emails_to_issue(
                                    solved_issue.get('id'),
                                    [{
                                        'id': email_id,
                                        'sender': email.get('sender'),
                                        'received_at': email.get('date'),
                                    }],
                                    confidence=0.95,
                                    matched_by="final_reply_template"
                                )
                                self.imap_handler.mark_as_read(email_id)
                                self.db.update_email_status(
                                    email_id,
                                    'drafted',
                                    draft_body=response_body,
                                    reasoning=f"Used final reply template from issue #{solved_issue.get('id')}",
                                    label="Issue Final Template",
                                    knowledge_citations=self._issue_template_citation(solved_issue)
                                )
                                self.logger.info(
                                    "Used final reply template from issue #%s for email %s",
                                    solved_issue.get('id'),
                                    email_id,
                                )
                            else:
                                self.logger.error(f"Failed to save issue-template draft for email: {email['subject']}")
                            continue
                        if not recipient:
                            self.logger.error(f"Could not extract recipient email from: {target_address_field}")
                            self.imap_handler.add_label(email_id, 'Parse Failed - Needs Human')
                            self.db.update_email_status(email_id, 'human_review', reasoning="Invalid recipient address", label="Parse Failed")
                            self.imap_handler.mark_as_read(email_id)
                            continue

                    # 1. No-reply intents → skip
                    # 2. Human-review intents → skip, needs human
                    # 3. Product intents (Technical Support, Warranty/Repair, Firmware Update) → fall through to draft generation

                    # 2. R&D forwarding rule for unresolved GE1000/GS1000 update bugs.
                    # Known issues with a final_reply_template are handled above
                    # and should not be forwarded one by one anymore.
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

                        # Download original attachments to forward to Leo
                        rnd_attachments = self.imap_handler.download_attachments(email_id)

                        forward_success = self.imap_handler.save_draft(
                            recipient=self.rnd_forward_email,
                            subject=forward_subject,
                            body=forward_body,
                            original_msg_id=email.get('message_id'),
                            original_html=email.get('html_body'),
                            original_sender=email.get('sender'),
                            original_date=email.get('date'),
                            reply_mode=False,
                            attachments=rnd_attachments
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

                    if self.response_generator.last_human_review_required:
                        label = self.response_generator.last_human_review_label or "Knowledge Gap - Needs Human"
                        reason = (
                            self.response_generator.last_human_review_reason
                            or "Knowledge base did not contain a confirmed answer"
                        )
                        if self._is_invalid_draft_content(response_body):
                            response_body = self._build_internal_check_acknowledgement()

                        if not recipient:
                            self.logger.error(f"Could not extract recipient email from: {target_address_field}")
                            self.imap_handler.add_label(email_id, 'Parse Failed - Needs Human')
                            self.db.update_email_status(email_id, 'human_review', reasoning="Invalid recipient address", label="Parse Failed")
                            self.imap_handler.mark_as_read(email_id)
                            continue

                        issue_id = self._record_knowledge_gap_issue(email_id, email, email_info, reason)
                        if issue_id:
                            reason = f"{reason}; linked to issue #{issue_id}"

                        success = self.imap_handler.save_draft(
                            recipient=recipient,
                            subject=email['subject'],
                            body=response_body,
                            original_msg_id=email.get('message_id'),
                            original_html=email.get('html_body'),
                            original_sender=email.get('sender'),
                            original_date=email.get('date')
                        )
                        if not success:
                            self.logger.error(f"Failed to save knowledge-gap acknowledgement draft for: {email['subject']}")
                        self.imap_handler.add_label(email_id, label)
                        self.imap_handler.mark_as_read(email_id)
                        self.db.update_email_status(
                            email_id,
                            'human_review',
                            draft_body=response_body,
                            reasoning=reason,
                            label=label,
                            knowledge_citations=self.response_generator.last_knowledge_citations
                        )
                        self.db.log_event(
                            "INFO",
                            f"Knowledge gap routed to human review for: {email['subject']}",
                            "automation"
                        )
                        continue
                    
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
                            self.db.update_email_status(
                                email_id,
                                'drafted',
                                draft_body=response_body,
                                reasoning=route_reason,
                                label=route_label,
                                knowledge_citations=self.response_generator.last_knowledge_citations
                            )
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
    
    def regenerate_draft(self, email_id):
        """从 DB 重新生成指定邮件的 AI 草稿，不依赖 IMAP。

        用法: python email_automation.py --regenerate 7720
        可以传多个 ID: python email_automation.py --regenerate 7720 7721 7722
        """
        # 规范化：支持传入列表或逗号分隔字符串
        if isinstance(email_id, str) and (',' in email_id or ' ' in email_id):
            ids = [x.strip() for x in email_id.replace(',', ' ').split()]
        elif isinstance(email_id, list):
            ids = [str(x).strip() for x in email_id]
        else:
            ids = [str(email_id).strip()]

        results = []
        for eid in ids:
            result = self._regenerate_single(eid)
            results.append(result)

        # 打印汇总
        succeeded = [r for r in results if r.get('success')]
        failed = [r for r in results if not r.get('success')]
        print(f"\n=== Regenerate Summary ===")
        print(f"  Total: {len(results)}, OK: {len(succeeded)}, Failed: {len(failed)}")
        for r in succeeded:
            print(f"  [OK]   {r['id']}: {r.get('subject', '')[:60]}")
        for r in failed:
            print(f"  [FAIL] {r['id']}: {r.get('error', 'unknown')}")

        return results

    def _regenerate_single(self, email_id):
        """重新生成单个邮件的草稿"""
        result = {'id': email_id, 'success': False}

        # 1. 从 DB 加载邮件
        email = self.db.get_email_by_id(email_id)
        if not email:
            result['error'] = f"Email {email_id} not found in DB"
            self.logger.error(result['error'])
            print(f"[ERROR] {result['error']}")
            return result

        subject = email.get('subject', '(no subject)')
        result['subject'] = subject
        self.logger.info(f"Regenerating draft for [{email_id}] {subject}")

        # 2. 清理邮件正文 + 重新提取信息
        clean_body = self.content_extractor.clean_email_content(email.get('body', ''))
        email_content = f"Subject: {subject}\n\n{clean_body}"

        email_info = self.content_extractor.extract_info(
            email_content,
            cc_list=[],
            sender_email=email.get('sender', '')
        )
        email_info['subject'] = subject
        email_info['body'] = clean_body
        email_info['attachments'] = email.get('attachments', [])

        # 3. 调用 AI 生成草稿
        response_body = self.response_generator.generate_response(email_info, email_content)
        human_review_required = self.response_generator.last_human_review_required
        human_review_reason = (
            self.response_generator.last_human_review_reason
            or "Knowledge base did not contain a confirmed answer"
        )
        human_review_label = self.response_generator.last_human_review_label or "Knowledge Gap - Needs Human"
        if human_review_required and self._is_invalid_draft_content(response_body):
            response_body = self._build_internal_check_acknowledgement()

        # 4. 验证
        if not response_body or self._is_invalid_draft_content(response_body):
            error_msg = "AI 生成草稿为空或包含内部标记"
            result['error'] = error_msg
            self.logger.error(f"[{email_id}] {error_msg}")
            print(f"[ERROR] [{email_id}] {error_msg}")
            return result

        status = 'human_review' if human_review_required else 'drafted'
        reasoning = human_review_reason if human_review_required else "Manual regenerate"
        label = human_review_label if human_review_required else None
        if human_review_required:
            issue_id = self._record_knowledge_gap_issue(email_id, email, email_info, human_review_reason)
            if issue_id:
                reasoning = f"{reasoning}; linked to issue #{issue_id}"

        # 5. 存到 DB（更新 draft_body）
        self.db.update_email_status(
            email_id,
            status,
            draft_body=response_body,
            reasoning=reasoning,
            label=label,
            knowledge_citations=self.response_generator.last_knowledge_citations
        )

        # 更新 AI 分析结果
        self.db.update_email_ai_analysis(email_id, {
            'intent': email_info.get('problem_category', 'Technical Support'),
            'sentiment': email_info.get('sentiment'),
            'product_model': email_info.get('product_model'),
            'mail_category': email_info.get('mail_category'),
            'issue_category': email_info.get('issue_category'),
            'reply_template_category': email_info.get('reply_template_category'),
            'classification_confidence': email_info.get('classification_confidence'),
            'classification_status': 'manual_regenerated',
            'classification_reason': email_info.get('classification_reason'),
            'classification_evidence': email_info.get('classification_evidence', []),
            'issue_facts': email_info.get('issue_facts'),
            'issue_fingerprint': email_info.get('issue_fingerprint'),
        })

        # 6. 尝试更新 IMAP 草稿（如果 IMAP 可用）
        recipient = self._extract_email_address(
            email.get('sender') or ''
        )
        if recipient:
            try:
                if self.imap_handler.connect_imap():
                    success = self.imap_handler.save_draft(
                        recipient=recipient,
                        subject=subject,
                        body=response_body
                    )
                    if success:
                        self.logger.info(f"[{email_id}] IMAP draft updated")
                    else:
                        self.logger.warning(f"[{email_id}] IMAP draft update failed")
                    self.imap_handler.disconnect_imap()
            except Exception as e:
                self.logger.warning(f"[{email_id}] IMAP update skipped: {e}")
        else:
            self.logger.warning(f"[{email_id}] Cannot extract recipient, IMAP draft skipped")

        # 7. 输出草稿到控制台（前 500 字符预览）
        print(f"\n{'='*60}")
        print(f"[{email_id}] {subject}")
        print(f"Product: {email_info.get('product_model', 'Unknown')}")
        print(f"Intent:  {email_info.get('problem_category', 'N/A')}")
        print(f"{'='*60}")
        print(response_body[:2000])
        if len(response_body) > 2000:
            print(f"\n... ({len(response_body)} chars total, showing first 2000)")

        result['success'] = True
        result['preview'] = response_body[:500]
        self.logger.info(f"[{email_id}] Draft regenerated: {len(response_body)} chars")
        return result

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
    
    def start_scheduling(self, interval_minutes=1):
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
    parser.add_argument('--interval', type=int, default=1, help='Scheduling interval in minutes')
    parser.add_argument('--regenerate', type=str, nargs='*', default=None,
                        help='Regenerate draft for specific email ID(s). '
                             'Usage: --regenerate 7720 or --regenerate 7720 7721 7722')
    
    args = parser.parse_args()
    
    # Create and start the email automation system
    automation = EmailAutomation()
    
    if args.regenerate:
        # Regenerate specific draft(s)
        automation.regenerate_draft(args.regenerate)
    elif args.once:
        automation.logger.info("Running in single-pass mode")
        automation.process_emails()
    else:
        automation.start_scheduling(interval_minutes=args.interval)
