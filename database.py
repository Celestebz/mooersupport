import sqlite3
import os
import json
import logging
import re
import html
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
from issue_facts import extract_issue_facts, normalize_model

class DatabaseHandler:
    """Handles SQLite database operations for the Mooer Support Bot"""
    
    def __init__(self, db_path="mooer_support.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_db()

    def _connect(self):
        """Create a SQLite connection with a longer timeout and busy handler."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn
        
    def _init_db(self):
        """Initialize database schema"""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            
            # Emails table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT PRIMARY KEY,
                sender TEXT,
                subject TEXT,
                body TEXT,
                received_at TIMESTAMP,
                status TEXT, -- new, processing, drafted, forwarded_drafted, sent, no_reply_needed, human_review, failed_retry, skipped(legacy)
                ai_intent TEXT,
                ai_reasoning TEXT,
                ai_sentiment TEXT,
                product_model TEXT,
                draft_body TEXT,
                is_read BOOLEAN DEFAULT 0,
                attachments TEXT -- JSON list of attachments
            )
            ''')
            
            # Check if attachments column exists (for migration)
            try:
                cursor.execute('SELECT attachments FROM emails LIMIT 1')
            except sqlite3.OperationalError:
                # Column doesn't exist, add it
                self.logger.info("Adding 'attachments' column to emails table")
                cursor.execute('ALTER TABLE emails ADD COLUMN attachments TEXT')

            # Check if label column exists (for migration)
            try:
                cursor.execute('SELECT label FROM emails LIMIT 1')
            except sqlite3.OperationalError:
                self.logger.info("Adding 'label' column to emails table")
                cursor.execute('ALTER TABLE emails ADD COLUMN label TEXT')

            # Track retries/errors without changing the existing table contract.
            try:
                cursor.execute('SELECT processing_attempts FROM emails LIMIT 1')
            except sqlite3.OperationalError:
                self.logger.info("Adding 'processing_attempts' column to emails table")
                cursor.execute('ALTER TABLE emails ADD COLUMN processing_attempts INTEGER DEFAULT 0')

            try:
                cursor.execute('SELECT last_error FROM emails LIMIT 1')
            except sqlite3.OperationalError:
                self.logger.info("Adding 'last_error' column to emails table")
                cursor.execute('ALTER TABLE emails ADD COLUMN last_error TEXT')

            # AI-first classification fields. Keep the legacy ai_intent column
            # for existing dashboard/report compatibility while storing the new
            # stable taxonomy used for routing and reporting.
            migration_columns = [
                ('mail_category', 'TEXT'),
                ('issue_category', 'TEXT'),
                ('reply_template_category', 'TEXT'),
                ('classification_confidence', 'REAL'),
                ('classification_status', 'TEXT'),
                ('precheck_flags', 'TEXT'),
                ('precheck_reason', 'TEXT'),
                ('classification_evidence', 'TEXT'),
                ('issue_facts', 'TEXT'),
                ('issue_fingerprint', 'TEXT'),
                ('knowledge_citations', 'TEXT'),
            ]
            for column_name, column_type in migration_columns:
                try:
                    cursor.execute(f'SELECT {column_name} FROM emails LIMIT 1')
                except sqlite3.OperationalError:
                    self.logger.info(f"Adding '{column_name}' column to emails table")
                    cursor.execute(f'ALTER TABLE emails ADD COLUMN {column_name} {column_type}')

            email_context_columns = [
                ('message_id', 'TEXT'),
                ('in_reply_to', 'TEXT'),
                ('references', 'TEXT'),
                ('normalized_subject', 'TEXT'),
                ('sender_email', 'TEXT'),
                ('thread_key', 'TEXT'),
                ('direction', 'TEXT'),
                ('reply_to_email_id', 'TEXT'),
            ]
            existing_email_columns = {
                row[1] for row in cursor.execute('PRAGMA table_info(emails)').fetchall()
            }
            for column_name, column_type in email_context_columns:
                quoted = f'"{column_name}"' if column_name == 'references' else column_name
                if column_name not in existing_email_columns:
                    self.logger.info(f"Adding '{column_name}' column to emails table")
                    cursor.execute(f'ALTER TABLE emails ADD COLUMN {quoted} {column_type}')
                    existing_email_columns.add(column_name)
            
            # Logs table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                level TEXT,
                message TEXT,
                module TEXT
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                name TEXT,
                first_seen_at TIMESTAMP,
                last_seen_at TIMESTAMP,
                tags TEXT,
                notes TEXT
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS support_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_model TEXT,
                issue_title TEXT,
                issue_category TEXT,
                issue_signature TEXT UNIQUE,
                status TEXT DEFAULT 'new_detected',
                priority TEXT DEFAULT 'Medium',
                user_count INTEGER DEFAULT 0,
                email_count INTEGER DEFAULT 0,
                first_seen_at TIMESTAMP,
                last_seen_at TIMESTAMP,
                rnd_status TEXT DEFAULT 'not_sent',
                rnd_notes TEXT,
                solution_summary TEXT,
                final_reply_template TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS email_issue_links (
                email_id TEXT,
                issue_id INTEGER,
                confidence REAL DEFAULT 1.0,
                matched_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (email_id, issue_id),
                FOREIGN KEY (email_id) REFERENCES emails(id),
                FOREIGN KEY (issue_id) REFERENCES support_issues(id)
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS issue_candidate_links (
                email_id TEXT,
                issue_id INTEGER,
                candidate_status TEXT DEFAULT 'pending',
                confidence REAL DEFAULT 0.0,
                matched_by TEXT,
                matched_keywords TEXT,
                evidence_snippet TEXT,
                review_note TEXT,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (email_id, issue_id),
                FOREIGN KEY (email_id) REFERENCES emails(id),
                FOREIGN KEY (issue_id) REFERENCES support_issues(id)
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS reply_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                category TEXT,
                product_model TEXT,
                issue_category TEXT,
                language TEXT DEFAULT 'en',
                body TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS bulk_reply_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER,
                template_id INTEGER,
                status TEXT DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                FOREIGN KEY (issue_id) REFERENCES support_issues(id),
                FOREIGN KEY (template_id) REFERENCES reply_templates(id)
            )
            ''')

            # ── Part prices table ──
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS part_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_model TEXT NOT NULL,
                part_name TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT DEFAULT 'USD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(product_model, part_name)
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT UNIQUE NOT NULL,
                knowledge_type TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                title TEXT NOT NULL,
                product_model TEXT,
                source_path TEXT,
                source_url TEXT,
                source_table TEXT,
                source_id TEXT,
                artifact_path TEXT,
                version TEXT,
                checksum TEXT,
                status TEXT DEFAULT 'active',
                reviewed_by TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                knowledge_type TEXT NOT NULL,
                product_model TEXT,
                chunk_type TEXT,
                section_title TEXT,
                page_number INTEGER,
                content TEXT NOT NULL,
                keywords TEXT,
                status TEXT DEFAULT 'active',
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES knowledge_documents(id)
            )
            ''')

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_emails_product_model ON emails(product_model)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_emails_sender_subject ON emails(sender_email, normalized_subject)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_support_issues_status ON support_issues(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_email_issue_links_issue ON email_issue_links(issue_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_issue_candidate_links_issue ON issue_candidate_links(issue_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_issue_candidate_links_status ON issue_candidate_links(candidate_status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_documents_type ON knowledge_documents(knowledge_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status ON knowledge_documents(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_documents_product ON knowledge_documents(product_model)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_type_product ON knowledge_chunks(knowledge_type, product_model)')
            self._backfill_email_context_fields(cursor)
            
            conn.commit()
            conn.close()
            self.logger.info("Database initialized successfully")
        except Exception as e:
            self.logger.error(f"Error initializing database: {e}")

    def _normalize_subject(self, subject):
        """Normalize email subject for lightweight thread matching."""
        value = re.sub(r'\s+', ' ', subject or '').strip()
        while value:
            new_value = re.sub(r'^(re|fw|fwd|答复|回复|转发)\s*[:：]\s*', '', value, flags=re.IGNORECASE).strip()
            if new_value == value:
                break
            value = new_value
        return value.lower()

    def _make_thread_key(self, sender_email, normalized_subject):
        if not sender_email or not normalized_subject:
            return ""
        safe_subject = re.sub(r'[^a-z0-9]+', '-', normalized_subject.lower()).strip('-')
        return f"{sender_email.lower()}::{safe_subject}"

    def _backfill_email_context_fields(self, cursor, batch_size=2000):
        """Fill lightweight thread fields for existing rows."""
        try:
            cursor.execute('''
                SELECT id, sender, subject
                FROM emails
                WHERE sender_email IS NULL
                   OR sender_email = ''
                   OR sender_email NOT LIKE '%@%'
                   OR normalized_subject IS NULL
                   OR normalized_subject = ''
                   OR thread_key IS NULL
                   OR thread_key = ''
                LIMIT ?
            ''', (batch_size,))
            rows = cursor.fetchall()
            for email_id, sender, subject in rows:
                sender_email = self._extract_email_address(sender)
                normalized_subject = self._normalize_subject(subject)
                thread_key = self._make_thread_key(sender_email, normalized_subject)
                cursor.execute('''
                    UPDATE emails
                    SET sender_email = ?,
                        normalized_subject = ?,
                        thread_key = ?,
                        direction = COALESCE(direction, 'inbound')
                    WHERE id = ?
                ''', (sender_email, normalized_subject, thread_key, email_id))
        except Exception as e:
            self.logger.warning(f"Email context backfill skipped: {e}")

    def add_email(self, email_data):
        """Add a new email to the database"""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            sender_email = self._extract_email_address(email_data.get('sender'))
            normalized_subject = self._normalize_subject(email_data.get('subject'))
            thread_key = self._make_thread_key(sender_email, normalized_subject)

            cursor.execute('''
            INSERT OR IGNORE INTO emails (
                id, sender, subject, body, received_at, status, is_read, attachments,
                message_id, in_reply_to, "references", normalized_subject,
                sender_email, thread_key, direction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                email_data['id'],
                email_data['sender'],
                email_data['subject'],
                email_data['body'],
                email_data.get('date', datetime.now().isoformat()),
                'new',
                False,
                json.dumps(email_data.get('attachments', [])),
                email_data.get('message_id', ''),
                email_data.get('in_reply_to', ''),
                email_data.get('references', ''),
                normalized_subject,
                sender_email,
                thread_key,
                email_data.get('direction', 'inbound')
            ))

            # Existing rows from older schema versions may have been inserted
            # before Message-ID/thread fields existed. Backfill empty context
            # fields even when INSERT OR IGNORE skips the row.
            cursor.execute('''
                UPDATE emails
                SET message_id = COALESCE(NULLIF(message_id, ''), ?),
                    in_reply_to = COALESCE(NULLIF(in_reply_to, ''), ?),
                    "references" = COALESCE(NULLIF("references", ''), ?),
                    normalized_subject = COALESCE(NULLIF(normalized_subject, ''), ?),
                    sender_email = COALESCE(NULLIF(sender_email, ''), ?),
                    thread_key = COALESCE(NULLIF(thread_key, ''), ?),
                    direction = COALESCE(NULLIF(direction, ''), ?)
                WHERE id = ?
            ''', (
                email_data.get('message_id', ''),
                email_data.get('in_reply_to', ''),
                email_data.get('references', ''),
                normalized_subject,
                sender_email,
                thread_key,
                email_data.get('direction', 'inbound'),
                email_data['id'],
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error adding email: {e}")
            return False

    def update_email_ai_analysis(self, email_id, analysis_result):
        """Update email with AI analysis and stable classification fields."""
        try:
            conn = self._connect()
            cursor = conn.cursor()

            field_map = {
                'ai_intent': analysis_result.get('intent'),
                'ai_sentiment': analysis_result.get('sentiment'),
                'product_model': analysis_result.get('product_model'),
                'mail_category': analysis_result.get('mail_category'),
                'issue_category': analysis_result.get('issue_category'),
                'reply_template_category': analysis_result.get('reply_template_category'),
                'classification_confidence': analysis_result.get('classification_confidence'),
                'classification_status': analysis_result.get('classification_status'),
                'precheck_flags': analysis_result.get('precheck_flags'),
                'precheck_reason': analysis_result.get('precheck_reason'),
                'classification_evidence': analysis_result.get('classification_evidence'),
                'issue_facts': analysis_result.get('issue_facts'),
                'issue_fingerprint': analysis_result.get('issue_fingerprint'),
                'ai_reasoning': analysis_result.get('classification_reason') or analysis_result.get('reasoning'),
            }

            update_fields = []
            params = []
            for field, value in field_map.items():
                if value is None:
                    continue
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                update_fields.append(f"{field} = ?")
                params.append(value)

            if not update_fields:
                conn.close()
                return False

            params.append(email_id)
            cursor.execute(f"UPDATE emails SET {', '.join(update_fields)} WHERE id = ?", params)
            updated = cursor.rowcount > 0
            
            conn.commit()
            conn.close()
            return updated
        except Exception as e:
            self.logger.error(f"Error updating AI analysis: {e}")
            return False

    def update_email_status(self, email_id, status, draft_body=None, reasoning=None, label=None,
                            last_error=None, increment_attempts=False, knowledge_citations=None):
        """Update email status, draft, reasoning and label"""
        try:
            conn = self._connect()
            cursor = conn.cursor()

            update_fields = ["status = ?"]
            params = [status]

            if draft_body is not None:
                update_fields.append("draft_body = ?")
                params.append(draft_body)

            if reasoning is not None:
                update_fields.append("ai_reasoning = ?")
                params.append(reasoning)

            if label is not None:
                update_fields.append("label = ?")
                params.append(label)

            if last_error is not None:
                update_fields.append("last_error = ?")
                params.append(last_error)

            if knowledge_citations is not None:
                update_fields.append("knowledge_citations = ?")
                if isinstance(knowledge_citations, str):
                    params.append(knowledge_citations)
                else:
                    params.append(json.dumps(knowledge_citations, ensure_ascii=False))

            if increment_attempts:
                update_fields.append("processing_attempts = COALESCE(processing_attempts, 0) + 1")

            params.append(email_id)
            
            sql = f"UPDATE emails SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(sql, params)
            updated = cursor.rowcount > 0
            
            conn.commit()
            conn.close()
            return updated
        except Exception as e:
            self.logger.error(f"Error updating email status: {e}")
            return False

    def get_emails(self, status=None, limit=50):
        """Get emails, optionally filtered by status"""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if status:
                cursor.execute('SELECT * FROM emails WHERE status = ? ORDER BY received_at DESC LIMIT ?', (status, limit))
            else:
                cursor.execute('SELECT * FROM emails ORDER BY received_at DESC LIMIT ?', (limit,))
                
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Error getting emails: {e}")
            return []

    def get_emails_by_date(self, since_date, before_date, limit=500):
        """Get emails received within a date range. Dates are ISO-format strings like '2026-06-04'."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT *
                FROM emails
                WHERE received_at >= ? AND received_at < ?
                ORDER BY received_at DESC
                LIMIT ?
            ''', (since_date, before_date, limit))

            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Error getting emails by date: {e}")
            return []

    def get_support_issue_summary(self):
        """Return all support issues with basic stats for daily report aggregation."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    product_model,
                    issue_title,
                    issue_category,
                    status,
                    priority,
                    user_count,
                    email_count,
                    first_seen_at,
                    last_seen_at
                FROM support_issues
                ORDER BY
                    CASE priority
                        WHEN 'P0' THEN 1 WHEN 'High' THEN 2
                        WHEN 'Medium' THEN 3 WHEN 'Low' THEN 4 ELSE 5
                    END,
                    user_count DESC
            ''')

            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Error getting support issue summary: {e}")
            return []

    def get_email_by_id(self, email_id):
        """Get a single email by ID"""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM emails WHERE id = ?', (email_id,))
            row = cursor.fetchone()
            conn.close()

            if row:
                return dict(row)
            return None
        except Exception as e:
            self.logger.error(f"Error getting email: {e}")
            return None

    def log_event(self, level, message, module="system"):
        """Log an event to the database"""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO logs (level, message, module)
            VALUES (?, ?, ?)
            ''', (level, message, module))
            
            conn.commit()
            conn.close()
        except Exception as e:
            # Fallback to standard logging if DB fails
            logging.error(f"Failed to write to log DB: {e}")

    def get_logs(self, limit=100):
        """Get recent logs"""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Error getting logs: {e}")
            return []

    def _extract_email_address(self, sender):
        if not sender:
            return ""
        match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender)
        return match.group(0).lower() if match else ""

    def get_email_thread_context(self, email_id, limit=20):
        """Return recent emails from the same sender and normalized subject."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM emails WHERE id = ?', (str(email_id),))
            current = cursor.fetchone()
            if not current:
                conn.close()
                return None

            current_dict = dict(current)
            stored_sender_email = current_dict.get('sender_email') or ""
            sender_email = stored_sender_email if "@" in stored_sender_email else self._extract_email_address(current_dict.get('sender'))
            normalized_subject = current_dict.get('normalized_subject') or self._normalize_subject(current_dict.get('subject'))
            thread_key = current_dict.get('thread_key') or self._make_thread_key(sender_email, normalized_subject)

            if not sender_email or not normalized_subject:
                item = self._thread_item(current_dict)
                digest = self._build_thread_digest([item])
                conn.close()
                return {
                    "email_id": str(email_id),
                    "thread_key": thread_key,
                    "customer_email": sender_email,
                    "normalized_subject": normalized_subject,
                    "summary": "上下文不足：缺少用户邮箱或规范化主题，暂时无法聚合同主题历史邮件。已显示当前邮件摘要。",
                    "conversation_summary": digest.get("conversation_summary") or "",
                    "customer_need": digest.get("customer_need") or "",
                    "current_stage": digest.get("current_stage") or "",
                    "latest_message_summary": digest.get("latest_message_summary") or "",
                    "timeline_summary": digest.get("timeline_summary") or [],
                    "linked_issue": None,
                    "items": [item],
                }

            cursor.execute('''
                UPDATE emails
                SET sender_email = COALESCE(NULLIF(sender_email, ''), ?),
                    normalized_subject = COALESCE(NULLIF(normalized_subject, ''), ?),
                    thread_key = COALESCE(NULLIF(thread_key, ''), ?),
                    direction = COALESCE(direction, 'inbound')
                WHERE id = ?
            ''', (sender_email, normalized_subject, thread_key, str(email_id)))

            cursor.execute('''
                SELECT *
                FROM emails
                WHERE sender_email = ?
                  AND normalized_subject = ?
                ORDER BY received_at DESC
                LIMIT ?
            ''', (sender_email, normalized_subject, limit))
            rows = [dict(row) for row in cursor.fetchall()]
            rows = list(reversed(rows))

            issue = self._find_thread_issue(cursor, [row.get('id') for row in rows])
            items = [self._thread_item(row, issue) for row in rows]
            digest = self._build_thread_digest(items, issue)

            conn.commit()
            conn.close()
            return {
                "email_id": str(email_id),
                "thread_key": thread_key,
                "customer_email": sender_email,
                "normalized_subject": normalized_subject,
                "summary": self._build_thread_summary(items, issue),
                "conversation_summary": digest.get("conversation_summary") or "",
                "customer_need": digest.get("customer_need") or "",
                "current_stage": digest.get("current_stage") or "",
                "latest_message_summary": digest.get("latest_message_summary") or "",
                "timeline_summary": digest.get("timeline_summary") or [],
                "linked_issue": issue,
                "items": items,
            }
        except Exception as e:
            self.logger.error(f"Error getting email thread context: {e}")
            return None

    def _find_thread_issue(self, cursor, email_ids):
        email_ids = [str(email_id) for email_id in email_ids if email_id]
        if not email_ids:
            return None
        placeholders = ",".join("?" for _ in email_ids)
        cursor.execute(f'''
            SELECT si.*
            FROM email_issue_links l
            JOIN support_issues si ON si.id = l.issue_id
            WHERE l.email_id IN ({placeholders})
            ORDER BY si.updated_at DESC, si.id DESC
            LIMIT 1
        ''', email_ids)
        row = cursor.fetchone()
        return dict(row) if row else None

    def _clean_thread_excerpt(self, body, max_chars=500):
        """Create a compact excerpt from the newest customer-written part."""
        text = (body or '').replace('\r\n', '\n').replace('\r', '\n').strip()
        text = html.unescape(text)
        forwarded_markers = [
            "----------转发的邮件信息----------",
            "---------- Forwarded message ---------",
            "-----Original Message-----",
        ]
        for marker in forwarded_markers:
            if marker.lower() in text.lower():
                pattern = re.escape(marker)
                parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) == 2 and parts[1].strip():
                    text = parts[1].strip()
                break
        text = re.sub(
            r'(?im)^\s*(发件人|日期|收件人|抄送|主题|from|date|sent|to|cc|subject)\s*[：:].*$',
            ' ',
            text,
        )
        text = re.split(
            r'\n\s*(On .{0,180} wrote:|[-]{2,}\s*Original Message\s*[-]{2,}|From:\s.+\nSent:\s)',
            text,
            maxsplit=1,
            flags=re.IGNORECASE | re.DOTALL,
        )[0]
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) > max_chars:
            return text[:max_chars].rstrip() + "..."
        return text

    def _status_step_label(self, status):
        labels = {
            "new": "新邮件，尚未处理",
            "processing": "处理中",
            "drafted": "已生成草稿，等待人工审核/发送",
            "forwarded_drafted": "已准备转研发，并给客户确认回复",
            "sent": "已发送回复",
            "no_reply_needed": "判断为无需回复",
            "human_review": "需要人工复核",
            "failed_retry": "生成或发送失败，等待重试",
            "skipped": "已跳过",
        }
        return labels.get(status or "", status or "状态未知")

    def _thread_item(self, row, issue=None):
        snippet = self._clean_thread_excerpt(row.get('body'), max_chars=500)
        attachments = row.get('attachments') or []
        if isinstance(attachments, str):
            try:
                attachments = json.loads(attachments) if attachments.strip() else []
            except Exception:
                attachments = []
        if not isinstance(attachments, list):
            attachments = []
        return {
            "id": str(row.get('id') or ''),
            "sender": row.get('sender') or '',
            "sender_email": row.get('sender_email') or self._extract_email_address(row.get('sender')),
            "received_at": str(row.get('received_at') or ''),
            "subject": row.get('subject') or '',
            "normalized_subject": row.get('normalized_subject') or self._normalize_subject(row.get('subject')),
            "direction": row.get('direction') or 'inbound',
            "status": row.get('status') or '',
            "step_label": self._status_step_label(row.get('status') or ''),
            "body_snippet": snippet,
            "body_full": row.get('body') or '',
            "draft_body": row.get('draft_body') or '',
            "attachments": attachments,
            "ai_intent": row.get('ai_intent') or '',
            "ai_sentiment": row.get('ai_sentiment') or '',
            "product_model": row.get('product_model') or '',
            "issue_category": row.get('issue_category') or '',
            "mail_category": row.get('mail_category') or '',
            "reply_template_category": row.get('reply_template_category') or '',
            "linked_issue": {
                "id": issue.get('id'),
                "title": issue.get('issue_title') or '',
                "status": issue.get('status') or '',
            } if issue else None,
        }

    def _build_thread_summary(self, items, issue=None):
        if not items:
            return "未找到同用户、同主题的历史邮件。"

        first = items[0]
        latest = items[-1]
        digest = self._build_thread_digest(items, issue)
        parts = [digest.get("conversation_summary") or f"该线程共找到 {len(items)} 封同用户、同主题邮件。"]
        if digest.get("customer_need"):
            parts.append(f"客户需求：{digest.get('customer_need')}")
        if digest.get("current_stage"):
            parts.append(f"当前阶段：{digest.get('current_stage')}")
        if latest.get('id') != first.get('id'):
            parts.append(f"最新邮件：{latest.get('received_at', '')}，状态：{latest.get('status', '')}。")
        if issue:
            parts.append(f"已关联 Issue #{issue.get('id')}：{issue.get('issue_title') or ''}。")
        if digest.get("latest_message_summary"):
            parts.append(f"最新内容：{digest.get('latest_message_summary')}")
        return "\n".join(parts)

    def _build_thread_digest(self, items, issue=None):
        if not items:
            return {
                "conversation_summary": "未找到同用户、同主题的历史邮件。",
                "customer_need": "",
                "current_stage": "",
                "latest_message_summary": "",
                "timeline_summary": [],
            }

        first = items[0]
        latest = items[-1]
        product = latest.get('product_model') or first.get('product_model') or "未知产品"
        intent = latest.get('ai_intent') or latest.get('reply_template_category') or latest.get('mail_category') or "未分类需求"
        issue_category = latest.get('issue_category') or latest.get('reply_template_category') or ""
        latest_excerpt = (latest.get('body_snippet') or '').strip()
        latest_short = latest_excerpt[:220].rstrip()
        if latest_excerpt and len(latest_excerpt) > 220:
            latest_short += "..."

        customer_need_parts = [f"{product} / {intent}"]
        if issue_category and issue_category not in customer_need_parts[0]:
            customer_need_parts.append(issue_category)
        if latest_short:
            customer_need_parts.append(latest_short)

        if issue:
            issue_title = issue.get('issue_title') or ''
            issue_status = issue.get('status') or ''
            rnd_status = issue.get('rnd_status') or ''
            if issue.get('final_reply_template') or issue.get('solution_summary'):
                current_stage = f"已有关联 Issue #{issue.get('id')} 的最终方案，可按方案回复。"
            elif rnd_status and rnd_status != 'not_sent':
                current_stage = f"关联 Issue #{issue.get('id')} 正在研发流程中（{rnd_status}）。"
            else:
                current_stage = f"关联 Issue #{issue.get('id')}：{issue_title}（{issue_status or '状态未知'}）。"
        else:
            current_stage = latest.get('step_label') or self._status_step_label(latest.get('status'))

        if len(items) == 1:
            conversation_summary = (
                f"这是该客户在当前主题下的第 1 封邮件，主题为“{latest.get('subject') or '无主题'}”。"
            )
        else:
            conversation_summary = (
                f"该线程共 {len(items)} 封同用户、同主题邮件，从 {str(first.get('received_at') or '')[:19]} "
                f"开始，最近更新于 {str(latest.get('received_at') or '')[:19]}。"
            )

        timeline_summary = []
        for item in items[-6:]:
            snippet = (item.get('body_snippet') or '').strip()
            if len(snippet) > 120:
                snippet = snippet[:120].rstrip() + "..."
            timeline_summary.append({
                "received_at": str(item.get('received_at') or '')[:19],
                "status": item.get('status') or '',
                "step_label": item.get('step_label') or self._status_step_label(item.get('status')),
                "subject": item.get('subject') or '',
                "product_model": item.get('product_model') or '',
                "ai_intent": item.get('ai_intent') or '',
                "summary": snippet,
            })

        return {
            "conversation_summary": conversation_summary,
            "customer_need": "；".join(part for part in customer_need_parts if part),
            "current_stage": current_stage,
            "latest_message_summary": latest_short,
            "timeline_summary": timeline_summary,
        }

    def upsert_customer(self, sender, seen_at=None, tags=None):
        """Create or update a customer record from an email sender field."""
        email_address = self._extract_email_address(sender)
        if not email_address:
            return None

        seen_at = seen_at or datetime.now().isoformat()
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO customers (email, first_seen_at, last_seen_at, tags)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    tags = COALESCE(customers.tags, excluded.tags)
            ''', (email_address, seen_at, seen_at, tags))
            conn.commit()
            customer_id = cursor.execute('SELECT id FROM customers WHERE email = ?', (email_address,)).fetchone()[0]
            conn.close()
            return customer_id
        except Exception as e:
            self.logger.error(f"Error upserting customer: {e}")
            return None

    def upsert_support_issue(self, issue_data):
        """Create or update a support issue bucket and return its ID."""
        now = datetime.now().isoformat()
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO support_issues (
                    product_model, issue_title, issue_category, issue_signature,
                    status, priority, rnd_status, rnd_notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(issue_signature) DO UPDATE SET
                    product_model = excluded.product_model,
                    issue_title = excluded.issue_title,
                    issue_category = excluded.issue_category,
                    priority = excluded.priority,
                    updated_at = excluded.updated_at
            ''', (
                issue_data.get('product_model'),
                issue_data.get('issue_title'),
                issue_data.get('issue_category'),
                issue_data.get('issue_signature'),
                issue_data.get('status', 'new_detected'),
                issue_data.get('priority', 'Medium'),
                issue_data.get('rnd_status', 'not_sent'),
                issue_data.get('rnd_notes'),
                now,
                now
            ))
            issue_id = cursor.execute(
                'SELECT id FROM support_issues WHERE issue_signature = ?',
                (issue_data.get('issue_signature'),)
            ).fetchone()[0]
            conn.commit()
            conn.close()
            return issue_id
        except Exception as e:
            self.logger.error(f"Error upserting support issue: {e}")
            return None

    def link_emails_to_issue(self, issue_id, emails, confidence=1.0, matched_by="manual_scan"):
        """Link email rows to a support issue and refresh aggregate counts."""
        if not issue_id:
            return 0

        try:
            conn = self._connect()
            cursor = conn.cursor()
            linked = 0
            for email_row in emails:
                email_id = email_row.get('id')
                if not email_id:
                    continue
                sender_email = self._extract_email_address(email_row.get('sender'))
                if sender_email:
                    seen_at = email_row.get('received_at') or datetime.now().isoformat()
                    cursor.execute('''
                        INSERT INTO customers (email, first_seen_at, last_seen_at, tags)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(email) DO UPDATE SET
                            last_seen_at = excluded.last_seen_at,
                            tags = COALESCE(customers.tags, excluded.tags)
                    ''', (sender_email, seen_at, seen_at, 'support'))
                cursor.execute('''
                    INSERT OR IGNORE INTO email_issue_links (email_id, issue_id, confidence, matched_by)
                    VALUES (?, ?, ?, ?)
                ''', (email_id, issue_id, confidence, matched_by))
                linked += cursor.rowcount

            conn.commit()
            conn.close()
            self.refresh_support_issue_counts(issue_id)
            return linked
        except Exception as e:
            self.logger.error(f"Error linking emails to issue: {e}")
            return 0

    def upsert_issue_candidates(self, issue_id, emails, confidence=0.5,
                                matched_by="scan", matched_keywords=None):
        """Store scan matches as review candidates instead of confirmed links."""
        if not issue_id:
            return 0

        keyword_text = ", ".join(matched_keywords or [])
        try:
            conn = self._connect()
            cursor = conn.cursor()
            inserted = 0
            for email_row in emails:
                email_id = email_row.get('id')
                if not email_id:
                    continue
                evidence = self._build_candidate_evidence(email_row, matched_keywords or [])
                cursor.execute('''
                    INSERT INTO issue_candidate_links (
                        email_id, issue_id, candidate_status, confidence,
                        matched_by, matched_keywords, evidence_snippet, updated_at
                    )
                    VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
                    ON CONFLICT(email_id, issue_id) DO UPDATE SET
                        confidence = excluded.confidence,
                        matched_by = excluded.matched_by,
                        matched_keywords = excluded.matched_keywords,
                        evidence_snippet = excluded.evidence_snippet,
                        updated_at = excluded.updated_at
                    WHERE issue_candidate_links.candidate_status != 'excluded'
                ''', (
                    email_id,
                    issue_id,
                    confidence,
                    matched_by,
                    keyword_text,
                    evidence,
                    datetime.now().isoformat(),
                ))
                inserted += cursor.rowcount
            conn.commit()
            conn.close()
            return inserted
        except Exception as e:
            self.logger.error(f"Error upserting issue candidates: {e}")
            return 0

    def _build_candidate_evidence(self, email_row, keywords):
        """Return a short evidence snippet around the first matched keyword."""
        facts = email_row.get('_issue_facts') or {}
        if facts:
            parts = []
            if facts.get("issue_fingerprint"):
                parts.append(f"fingerprint={facts.get('issue_fingerprint')}")
            if facts.get("failure_stage"):
                parts.append("failure_stage=" + ", ".join(facts.get("failure_stage") or []))
            if facts.get("symptoms"):
                parts.append("symptoms=" + ", ".join(facts.get("symptoms") or []))
            if facts.get("versions"):
                parts.append("versions=" + ", ".join(facts.get("versions") or []))
            if facts.get("platforms"):
                parts.append("platforms=" + ", ".join(facts.get("platforms") or []))
            if facts.get("negative_reasons"):
                parts.append("negative=" + ", ".join(facts.get("negative_reasons") or []))
            if facts.get("evidence"):
                parts.append("evidence: " + facts.get("evidence"))
            if parts:
                return "\n".join(parts)[:1200]

        text = f"{email_row.get('subject') or ''}\n{email_row.get('body') or ''}"
        normalized = re.sub(r'\s+', ' ', text).strip()
        lower = normalized.lower()
        for kw in keywords:
            kw = (kw or '').strip().lower()
            if not kw:
                continue
            idx = lower.find(kw)
            if idx >= 0:
                return normalized[max(0, idx - 180):idx + 420]
        return normalized[:600]

    def get_issue_candidates(self, issue_id, status=None, limit=500):
        """Return candidate emails for an issue with review metadata."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            params = [issue_id]
            status_sql = ""
            if status:
                status_sql = "AND c.candidate_status = ?"
                params.append(status)
            params.append(limit)
            cursor.execute(f'''
                SELECT e.*, c.candidate_status, c.confidence, c.matched_by,
                       c.matched_keywords, c.evidence_snippet, c.review_note,
                       c.reviewed_at, c.created_at AS candidate_created_at,
                       c.updated_at AS candidate_updated_at
                FROM issue_candidate_links c
                JOIN emails e ON e.id = c.email_id
                WHERE c.issue_id = ?
                {status_sql}
                ORDER BY
                    CASE c.candidate_status
                        WHEN 'pending' THEN 1
                        WHEN 'unsure' THEN 2
                        WHEN 'weak_related' THEN 3
                        WHEN 'confirmed' THEN 4
                        WHEN 'excluded' THEN 5
                        ELSE 9
                    END,
                    e.received_at DESC
                LIMIT ?
            ''', params)
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Error getting issue candidates: {e}")
            return []

    def review_issue_candidate(self, issue_id, email_id, candidate_status,
                               review_note=None, reviewer="dashboard"):
        """Update candidate review status. Confirmed candidates become formal issue links."""
        allowed = {"pending", "confirmed", "weak_related", "excluded", "unsure"}
        if candidate_status not in allowed:
            return False
        try:
            conn = self._connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                UPDATE issue_candidate_links
                SET candidate_status = ?, review_note = ?, reviewed_at = ?,
                    matched_by = COALESCE(matched_by, ?), updated_at = ?
                WHERE issue_id = ? AND email_id = ?
            ''', (candidate_status, review_note, now, reviewer, now, issue_id, str(email_id)))
            changed = cursor.rowcount
            conn.commit()
            conn.close()

            if changed and candidate_status == "confirmed":
                row = self.get_email_by_id(str(email_id))
                if row:
                    self.link_emails_to_issue(
                        issue_id,
                        [row],
                        confidence=1.0,
                        matched_by="candidate_confirmed",
                    )
            elif changed:
                self.refresh_support_issue_counts(issue_id)
            return changed > 0
        except Exception as e:
            self.logger.error(f"Error reviewing issue candidate: {e}")
            return False

    def refresh_support_issue_counts(self, issue_id):
        """Refresh user/email counts and first/last seen timestamps for an issue."""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT e.id, e.sender, e.received_at
                FROM email_issue_links l
                JOIN emails e ON e.id = l.email_id
                WHERE l.issue_id = ?
            ''', (issue_id,))
            rows = cursor.fetchall()
            email_count = len({row[0] for row in rows})
            user_emails = set()
            fallback_senders = set()
            received_values = []
            for _, sender, received_at in rows:
                sender_email = self._extract_email_address(sender or "")
                if sender_email:
                    user_emails.add(sender_email.lower())
                elif sender:
                    fallback_senders.add(str(sender).strip().lower())
                if received_at:
                    received_values.append(received_at)
            user_count = len(user_emails) + len(fallback_senders)
            def _date_key(value):
                if not value:
                    return datetime.min
                try:
                    return parsedate_to_datetime(str(value)).replace(tzinfo=None)
                except Exception:
                    try:
                        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        return datetime.min

            if received_values:
                ordered_dates = sorted(received_values, key=_date_key)
                first_seen_at = ordered_dates[0]
                last_seen_at = ordered_dates[-1]
            else:
                first_seen_at = None
                last_seen_at = None
            cursor.execute('''
                UPDATE support_issues
                SET email_count = ?, user_count = ?, first_seen_at = ?,
                    last_seen_at = ?, updated_at = ?
                WHERE id = ?
            ''', (
                email_count or 0,
                user_count or 0,
                first_seen_at,
                last_seen_at,
                datetime.now().isoformat(),
                issue_id
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.error(f"Error refreshing support issue counts: {e}")

    def _support_issue_model_matches(self, issue_product_model, product_model):
        issue_model = (issue_product_model or "").strip()
        product_model = (product_model or "").strip()
        if not issue_model or not product_model:
            return False

        requested = normalize_model(product_model)
        raw_parts = re.split(r"\s*(?:/|,|\+|\bor\b|\band\b)\s*", issue_model, flags=re.IGNORECASE)
        issue_models = {normalize_model(part) for part in raw_parts if part.strip()}
        issue_models.add(normalize_model(issue_model))

        if requested in issue_models:
            return True

        # Some issue buckets intentionally cover a product family, for example
        # "GE300 Lite / GE300". Keep this explicit and conservative.
        if requested == "ge300" and "ge300lite" in issue_models:
            return True
        if requested == "ge300lite" and "ge300" in issue_models:
            return True
        return False

    def find_issue_final_reply_template(self, product_model, issue_category, issue_fingerprint=None):
        """Find a support issue with a final reply template for this product/problem."""
        product_model = (product_model or "").strip()
        issue_category = (issue_category or "").strip()
        issue_fingerprint = (issue_fingerprint or "").strip()
        if not product_model:
            return None

        match_keys = {
            key for key in [issue_category, issue_fingerprint]
            if key and key not in {"unknown_issue", "unclassified"}
        }
        if not match_keys:
            return None

        signatures = {
            "{}_{}".format(
                product_model.lower().replace(" ", "_"),
                key.lower().replace("/", "_").replace(" ", "_")
            )
            for key in match_keys
        }

        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT *
                FROM support_issues
                WHERE final_reply_template IS NOT NULL
                  AND trim(final_reply_template) != ''
                ORDER BY updated_at DESC, id ASC
            ''')
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            for row in rows:
                if not self._support_issue_model_matches(row.get("product_model"), product_model):
                    continue
                row_issue_category = row.get("issue_category") or ""
                row_signature = row.get("issue_signature") or ""
                if row_issue_category in match_keys or row_signature in match_keys or row_signature in signatures:
                    return row
                if any(row_signature.endswith("_" + key) for key in match_keys):
                    return row
            return None
        except Exception as e:
            self.logger.error(f"Error finding issue final reply template: {e}")
            return None

    def update_support_issue(self, issue_id, status=None, rnd_status=None, rnd_notes=None, solution_summary=None, final_reply_template=None):
        """Update issue tracking fields from the dashboard."""
        fields = []
        params = []
        for column, value in (
            ('status', status),
            ('rnd_status', rnd_status),
            ('rnd_notes', rnd_notes),
            ('solution_summary', solution_summary),
            ('final_reply_template', final_reply_template),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                params.append(value)

        if not fields:
            return False

        fields.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(issue_id)

        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute(f"UPDATE support_issues SET {', '.join(fields)} WHERE id = ?", params)
            if final_reply_template is not None and str(final_reply_template).strip():
                self._sync_issue_final_reply_template(cursor, issue_id)
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error updating support issue: {e}")
            return False

    def _sync_issue_final_reply_template(self, cursor, issue_id):
        """Mirror an issue final reply into reply_templates for long-term browsing."""
        cursor.execute('SELECT * FROM support_issues WHERE id = ?', (issue_id,))
        issue = cursor.fetchone()
        if not issue:
            return

        columns = [desc[0] for desc in cursor.description]
        issue = dict(zip(columns, issue))
        body = (issue.get('final_reply_template') or '').strip()
        if not body:
            return

        now = datetime.now().isoformat()
        name = f"Issue #{issue_id} - {issue.get('issue_title') or ''}".strip()
        category = "issue_final_reply"
        product_model = issue.get('product_model') or ''
        issue_category = issue.get('issue_category') or ''

        cursor.execute('''
            SELECT id FROM reply_templates
            WHERE category = ?
              AND issue_category = ?
              AND product_model = ?
              AND name = ?
            ORDER BY id ASC
            LIMIT 1
        ''', (category, issue_category, product_model, name))
        row = cursor.fetchone()
        if row:
            cursor.execute('''
                UPDATE reply_templates
                SET body = ?, status = 'active', updated_at = ?
                WHERE id = ?
            ''', (body, now, row[0]))
        else:
            cursor.execute('''
                INSERT INTO reply_templates (
                    name, category, product_model, issue_category,
                    language, body, status, updated_at
                )
                VALUES (?, ?, ?, ?, 'en', ?, 'active', ?)
            ''', (name, category, product_model, issue_category, body, now))

    def get_support_issues(self, status=None, limit=100):
        """Return support issue buckets for the dashboard."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if status:
                cursor.execute('''
                    SELECT * FROM support_issues
                    WHERE status = ?
                    ORDER BY id ASC
                    LIMIT ?
                ''', (status, limit))
            else:
                cursor.execute('''
                    SELECT * FROM support_issues
                    ORDER BY id ASC
                    LIMIT ?
                ''', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Error getting support issues: {e}")
            return []

    def get_issue_emails(self, issue_id, limit=500):
        """Return emails linked to a support issue."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT e.*, l.confidence, l.matched_by, l.created_at AS linked_at
                FROM email_issue_links l
                JOIN emails e ON e.id = l.email_id
                WHERE l.issue_id = ?
                ORDER BY e.received_at DESC
                LIMIT ?
            ''', (issue_id, limit))
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Error getting issue emails: {e}")
            return []

    def auto_detect_issues(self, days=30, min_users=2):
        """Automatically scan recent emails and detect issue clusters.

        Groups emails by (product_model, issue_category) and checks if enough
        unique users reported similar issues to warrant creating an Issue bucket.

        Returns a list of candidate issue dicts ready for upsert.
        """
        import re
        from collections import defaultdict

        try:
            since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, sender, subject, body, received_at,
                       product_model, ai_intent, ai_sentiment, status,
                       mail_category, issue_category, reply_template_category,
                       classification_confidence, classification_status,
                       issue_facts, issue_fingerprint
                FROM emails
                WHERE product_model IS NOT NULL
                  AND product_model != ''
                  AND product_model != 'Unknown'
                  AND received_at >= ?
                ORDER BY received_at DESC
            ''', (since,))
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()

            if not rows:
                return {"candidates": [], "summary": "No emails with product models found in the last {} days.".format(days)}

            # Group by (product_model, stable issue category). New AI-first
            # classifications take precedence; legacy ai_intent is only a
            # fallback for older rows that have not been reprocessed.
            clusters = defaultdict(lambda: {
                "emails": [],
                "users": set(),
                "subjects": [],
                "sentiments": [],
                "facts": [],
            })
            for row in rows:
                mail_category = (row.get("mail_category") or "").strip()
                legacy_intent = (row.get("ai_intent") or "").strip().lower()
                current_text_for_guard = f"{row.get('subject') or ''} {row.get('body') or ''}".lower()
                if mail_category in {
                    "business_media",
                    "spam_irrelevant",
                    "system_notification",
                    "sales_stock",
                    "customer_followup_ack",
                }:
                    continue
                if any(x in legacy_intent for x in [
                    "partnership", "collaboration", "press", "media",
                    "dealer", "sales", "gratitude", "spam", "system notification"
                ]):
                    continue
                if any(x in current_text_for_guard for x in [
                    "collaboration proposal",
                    "artist collaboration",
                    "endorsed artist",
                    "artist program",
                    "business proposal",
                    "marketing",
                    "amazon could be a great channel",
                ]):
                    continue

                stored_facts = {}
                if row.get("issue_facts"):
                    try:
                        stored_facts = json.loads(row.get("issue_facts") or "{}")
                    except Exception:
                        stored_facts = {}

                facts = stored_facts or extract_issue_facts(
                    row.get("subject"),
                    row.get("body"),
                    fallback_model=row.get("product_model"),
                )
                model = (facts.get("product_model") or row.get("product_model") or "").strip()
                if not model or model == "Unknown":
                    continue

                stable_issue = (row.get("issue_category") or "").strip()
                intent = (row.get("ai_intent") or "").strip()
                fact_fingerprint = (row.get("issue_fingerprint") or facts.get("issue_fingerprint") or "").strip()
                fact_issue_type = (facts.get("issue_type") or "").strip()

                if fact_fingerprint and fact_fingerprint != "unknown_issue":
                    intent_key = fact_fingerprint
                elif fact_issue_type and fact_issue_type != "unknown_issue":
                    intent_key = fact_issue_type
                elif stable_issue and stable_issue not in {"unknown_issue", "spam_irrelevant"}:
                    intent_key = stable_issue
                else:
                    # Normalize legacy intent: collapse similar categories.
                    intent_norm = intent.lower()
                    if any(kw in intent_norm for kw in ["defect", "hardware", "broken", "brick", "dead", "won't turn", "no power"]):
                        intent_key = "hardware_defect"
                    elif any(kw in intent_norm for kw in ["firmware", "update", "software", "bug", "crash", "freeze"]):
                        intent_key = "firmware_software_bug"
                    elif any(kw in intent_norm for kw in ["complaint", "angry", "shame", "disappointed", "competition"]):
                        intent_key = "customer_complaint"
                    elif any(kw in intent_norm for kw in ["question", "how to", "setup", "guide", "manual", "instruction"]):
                        intent_key = "usage_question"
                    elif any(kw in intent_norm for kw in ["warranty", "repair", "return", "refund", "replacement"]):
                        intent_key = "warranty_return"
                    elif any(kw in intent_norm for kw in ["download", "preset", "tone", "patch", "app", "software download"]):
                        intent_key = "download_software_access"
                    elif any(kw in intent_norm for kw in ["unlock", "activation", "license", "code", "key"]):
                        intent_key = "activation_license"
                    elif any(kw in intent_norm for kw in ["led", "display", "screen", "light"]):
                        intent_key = "display_led_issue"
                    elif any(kw in intent_norm for kw in ["audio", "sound", "noise", "output", "signal"]):
                        intent_key = "audio_signal_issue"
                    else:
                        intent_key = "unclassified"

                if intent_key in {"unclassified", "unknown_issue", "spam_irrelevant"}:
                    continue
                if facts.get("negative_reasons") and "no_current_message_failure_fact" in facts.get("negative_reasons", []):
                    if fact_fingerprint == "unknown_issue":
                        continue

                key = (model, intent_key)
                clusters[key]["emails"].append(row)
                clusters[key]["facts"].append(facts)
                sender = self._extract_email_address(row.get("sender") or "")
                if sender:
                    clusters[key]["users"].add(sender)
                clusters[key]["subjects"].append(row.get("subject") or "")
                clusters[key]["sentiments"].append(row.get("ai_sentiment") or "")

            # Filter: need at least min_users unique users to be a candidate issue
            candidates = []
            for (model, intent_key), data in sorted(clusters.items()):
                if len(data["users"]) < min_users:
                    continue

                # Determine priority
                negative = sum(1 for s in data["sentiments"] if s and s.lower() in ("negative", "angry", "frustrated"))
                priority = "High" if negative >= 2 else "Medium"
                if len(data["users"]) >= 5 or intent_key == "Hardware Defect":
                    priority = "P0"

                # Generate signature and title
                sig = "{}_{}".format(
                    model.lower().replace(" ", "_"),
                    intent_key.lower().replace("/", "_").replace(" ", "_")
                )
                display_issue = intent_key.replace("_", " ")
                title = "{} - {} ({} users)".format(model, display_issue, len(data["users"]))
                sample_facts = []
                for facts in data.get("facts", []):
                    compact = {
                        "product_model": facts.get("product_model"),
                        "issue_fingerprint": facts.get("issue_fingerprint"),
                        "failure_stage": facts.get("failure_stage", []),
                        "symptoms": facts.get("symptoms", []),
                        "versions": facts.get("versions", []),
                        "platforms": facts.get("platforms", []),
                        "evidence": facts.get("evidence", ""),
                        "negative_reasons": facts.get("negative_reasons", []),
                    }
                    if compact not in sample_facts:
                        sample_facts.append(compact)
                    if len(sample_facts) >= 5:
                        break

                candidates.append({
                    "product_model": model,
                    "issue_title": title,
                    "issue_category": intent_key,
                    "issue_signature": sig,
                    "user_count": len(data["users"]),
                    "email_count": len(data["emails"]),
                    "priority": priority,
                    "status": "new_detected",
                    "email_ids": [r.get("id") for r in data["emails"] if r.get("id")],
                    "email_facts": {
                        str(row.get("id")): facts
                        for row, facts in zip(data["emails"], data.get("facts", []))
                        if row.get("id")
                    },
                    "sample_subjects": list(set(data["subjects"]))[:5],
                    "sample_users": sorted(data["users"])[:10],
                    "sample_facts": sample_facts,
                    "dominant_sentiment": max(set(data["sentiments"]), key=data["sentiments"].count, default="neutral"),
                })

            # Sort: P0 first, then by user count
            priority_order = {"P0": 0, "High": 1, "Medium": 2, "Low": 3}
            candidates.sort(key=lambda c: (priority_order.get(c["priority"], 9), -c["user_count"]))

            return {
                "candidates": candidates,
                "total_emails_scanned": len(rows),
                "days_scanned": days,
                "products_found": len({r.get("product_model") for r in rows}),
                "summary": "Found {} issue candidates from {} emails across {} products.".format(
                    len(candidates), len(rows),
                    len({r.get("product_model") for r in rows}),
                ),
            }

        except Exception as e:
            self.logger.error("Error auto-detecting issues: {}".format(e))
            return {"candidates": [], "summary": "Auto-detection failed: {}".format(e), "error": str(e)}

    # ── Part Prices CRUD ──

    def get_part_price(self, product_model, part_name):
        """Get a single part price from DB. Returns dict or None."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            normalized_model = product_model.strip()
            normalized_part = part_name.strip()
            cursor.execute(
                'SELECT * FROM part_prices WHERE product_model = ? AND part_name = ?',
                (normalized_model, normalized_part)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return dict(row)
            return None
        except Exception as e:
            self.logger.error(f"Error getting part price: {e}")
            return None

    def get_all_prices_for_model(self, product_model):
        """Get all part prices for a product model. Returns dict {part_name: price} or None."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM part_prices WHERE product_model = ?',
                (product_model.strip(),)
            )
            rows = cursor.fetchall()
            conn.close()
            if rows:
                return {r['part_name']: r['price'] for r in rows}
            return None
        except Exception as e:
            self.logger.error(f"Error getting all prices for model: {e}")
            return None

    def list_all_part_prices(self):
        """List all part prices. Returns list of dicts."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM part_prices ORDER BY product_model, part_name')
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            self.logger.error(f"Error listing part prices: {e}")
            return []

    def upsert_part_price(self, product_model, part_name, price, currency="USD"):
        """Insert or update a part price. Returns True on success."""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO part_prices (product_model, part_name, price, currency, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(product_model, part_name) DO UPDATE SET
                    price = excluded.price,
                    currency = excluded.currency,
                    updated_at = excluded.updated_at
            ''', (product_model.strip(), part_name.strip(), price, currency, now))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error upserting part price: {e}")
            return False

    def delete_part_price(self, part_price_id):
        """Delete a part price by ID. Returns True on success."""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM part_prices WHERE id = ?', (part_price_id,))
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Error deleting part price: {e}")
            return False

    # ── Reply Templates CRUD ──

    def list_reply_templates(self, status=None, limit=200):
        """List reply templates, optionally filtered by status."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    'SELECT * FROM reply_templates WHERE status = ? ORDER BY updated_at DESC LIMIT ?',
                    (status, limit)
                )
            else:
                cursor.execute(
                    'SELECT * FROM reply_templates ORDER BY updated_at DESC LIMIT ?',
                    (limit,)
                )
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            self.logger.error(f"Error listing reply templates: {e}")
            return []

    def get_reply_templates_by_category(self, category, product_model=None, language='en'):
        """Get active templates matching category and optionally product_model. Returns list of dicts."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if product_model:
                cursor.execute('''
                    SELECT * FROM reply_templates
                    WHERE category = ? AND product_model = ? AND status = 'active' AND language = ?
                    ORDER BY updated_at DESC
                ''', (category, product_model, language))
            else:
                cursor.execute('''
                    SELECT * FROM reply_templates
                    WHERE category = ? AND status = 'active' AND language = ?
                    ORDER BY updated_at DESC
                ''', (category, language))
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            self.logger.error(f"Error getting reply templates by category: {e}")
            return []

    def upsert_reply_template(self, name, category, body, product_model=None,
                              issue_category=None, language='en'):
        """Insert a new reply template. Returns the new ID."""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO reply_templates (name, category, product_model, issue_category, language, body, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, category, product_model, issue_category, language, body, now))
            new_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return new_id
        except Exception as e:
            self.logger.error(f"Error upserting reply template: {e}")
            return None

    def update_reply_template(self, template_id, **fields):
        """Update reply template fields. Returns True on success."""
        allowed = {'name', 'category', 'product_model', 'issue_category', 'language', 'body', 'status'}
        valid_fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not valid_fields:
            return False
        valid_fields['updated_at'] = datetime.now().isoformat()
        try:
            conn = self._connect()
            cursor = conn.cursor()
            set_clause = ', '.join(f"{k} = ?" for k in valid_fields)
            values = list(valid_fields.values()) + [template_id]
            cursor.execute(f'UPDATE reply_templates SET {set_clause} WHERE id = ?', values)
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Error updating reply template: {e}")
            return False

    def delete_reply_template(self, template_id):
        """Soft-delete a reply template (set status to 'inactive')."""
        return self.update_reply_template(template_id, status='inactive')

    # -- Knowledge base CRUD -------------------------------------------------

    def upsert_knowledge_document(self, document):
        """Insert or update a knowledge document. Returns document id."""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            metadata = document.get('metadata')
            if metadata is not None and not isinstance(metadata, str):
                metadata = json.dumps(metadata, ensure_ascii=False)

            values = {
                'source_key': document.get('source_key') or '',
                'knowledge_type': document.get('knowledge_type') or '',
                'source_kind': document.get('source_kind') or '',
                'title': document.get('title') or '',
                'product_model': document.get('product_model') or '',
                'source_path': document.get('source_path') or '',
                'source_url': document.get('source_url') or '',
                'source_table': document.get('source_table') or '',
                'source_id': str(document.get('source_id') or ''),
                'artifact_path': document.get('artifact_path') or '',
                'version': document.get('version') or '',
                'checksum': document.get('checksum') or '',
                'status': document.get('status') or 'active',
                'reviewed_by': document.get('reviewed_by') or '',
                'metadata': metadata or '',
                'updated_at': now,
            }

            cursor.execute('''
                INSERT INTO knowledge_documents (
                    source_key, knowledge_type, source_kind, title, product_model,
                    source_path, source_url, source_table, source_id, artifact_path,
                    version, checksum, status, reviewed_by, metadata, updated_at
                )
                VALUES (
                    :source_key, :knowledge_type, :source_kind, :title, :product_model,
                    :source_path, :source_url, :source_table, :source_id, :artifact_path,
                    :version, :checksum, :status, :reviewed_by, :metadata, :updated_at
                )
                ON CONFLICT(source_key) DO UPDATE SET
                    knowledge_type = excluded.knowledge_type,
                    source_kind = excluded.source_kind,
                    title = excluded.title,
                    product_model = excluded.product_model,
                    source_path = excluded.source_path,
                    source_url = excluded.source_url,
                    source_table = excluded.source_table,
                    source_id = excluded.source_id,
                    artifact_path = excluded.artifact_path,
                    version = excluded.version,
                    checksum = excluded.checksum,
                    status = excluded.status,
                    reviewed_by = excluded.reviewed_by,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
            ''', values)
            cursor.execute('SELECT id FROM knowledge_documents WHERE source_key = ?', (values['source_key'],))
            row = cursor.fetchone()
            conn.commit()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            self.logger.error(f"Error upserting knowledge document: {e}")
            return None

    def replace_knowledge_chunks(self, document_id, chunks):
        """Replace all chunks for a document."""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('DELETE FROM knowledge_chunks WHERE document_id = ?', (document_id,))
            for chunk in chunks:
                metadata = chunk.get('metadata')
                if metadata is not None and not isinstance(metadata, str):
                    metadata = json.dumps(metadata, ensure_ascii=False)
                cursor.execute('''
                    INSERT INTO knowledge_chunks (
                        document_id, knowledge_type, product_model, chunk_type,
                        section_title, page_number, content, keywords, status,
                        metadata, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    document_id,
                    chunk.get('knowledge_type') or '',
                    chunk.get('product_model') or '',
                    chunk.get('chunk_type') or '',
                    chunk.get('section_title') or '',
                    chunk.get('page_number'),
                    chunk.get('content') or '',
                    chunk.get('keywords') or '',
                    chunk.get('status') or 'active',
                    metadata or '',
                    now,
                ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error replacing knowledge chunks: {e}")
            return False

    def list_knowledge_documents(self, knowledge_type=None, status=None, limit=500):
        """List knowledge documents with optional filters."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            clauses = []
            params = []
            if knowledge_type:
                clauses.append('knowledge_type = ?')
                params.append(knowledge_type)
            if status:
                clauses.append('status = ?')
                params.append(status)
            where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
            params.append(limit)
            cursor.execute(f'''
                SELECT d.*,
                       (SELECT count(*) FROM knowledge_chunks c WHERE c.document_id = d.id) AS chunk_count
                FROM knowledge_documents d
                {where}
                ORDER BY knowledge_type, source_kind, title
                LIMIT ?
            ''', params)
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            self.logger.error(f"Error listing knowledge documents: {e}")
            return []

    def get_knowledge_summary(self):
        """Return grouped knowledge counts for dashboard/API."""
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            by_type = cursor.execute('''
                SELECT knowledge_type, status, count(*) AS document_count,
                       COALESCE(sum(chunk_count), 0) AS chunk_count
                FROM (
                    SELECT d.id, d.knowledge_type, d.status, count(c.id) AS chunk_count
                    FROM knowledge_documents d
                    LEFT JOIN knowledge_chunks c ON c.document_id = d.id
                    GROUP BY d.id
                )
                GROUP BY knowledge_type, status
                ORDER BY knowledge_type, status
            ''').fetchall()
            by_source = cursor.execute('''
                SELECT source_kind, count(*) AS document_count
                FROM knowledge_documents
                GROUP BY source_kind
                ORDER BY source_kind
            ''').fetchall()
            totals = cursor.execute('''
                SELECT
                    (SELECT count(*) FROM knowledge_documents) AS documents,
                    (SELECT count(*) FROM knowledge_chunks) AS chunks
            ''').fetchone()
            conn.close()
            return {
                "totals": dict(totals) if totals else {"documents": 0, "chunks": 0},
                "by_type": [dict(r) for r in by_type],
                "by_source": [dict(r) for r in by_source],
            }
        except Exception as e:
            self.logger.error(f"Error getting knowledge summary: {e}")
            return {"totals": {"documents": 0, "chunks": 0}, "by_type": [], "by_source": []}

    def search_manual_chunks(self, source_path=None, product_model=None, keywords=None, limit=4):
        """Search indexed manual chunks. Prefer exact source_path to avoid model-name collisions."""
        try:
            keywords = [str(k).strip() for k in (keywords or []) if str(k).strip()]
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            docs = []
            if source_path:
                normalized = str(source_path).replace('/', os.sep).replace('\\', os.sep)
                alt = normalized.replace(os.sep, '/')
                cursor.execute('''
                    SELECT * FROM knowledge_documents
                    WHERE knowledge_type = 'product_manual'
                      AND status = 'active'
                      AND (source_path = ? OR replace(source_path, '\\', '/') = ?)
                    LIMIT 1
                ''', (normalized, alt))
                row = cursor.fetchone()
                if row:
                    docs = [dict(row)]

            if not docs and product_model:
                cursor.execute('''
                    SELECT * FROM knowledge_documents
                    WHERE knowledge_type = 'product_manual'
                      AND status = 'active'
                      AND lower(product_model) = lower(?)
                    LIMIT 5
                ''', (product_model,))
                docs = [dict(r) for r in cursor.fetchall()]

            if not docs:
                conn.close()
                return []

            doc_ids = [d['id'] for d in docs]
            placeholders = ','.join('?' for _ in doc_ids)
            rows = cursor.execute(f'''
                SELECT c.*, d.title, d.source_path, d.artifact_path
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE c.document_id IN ({placeholders})
                  AND c.status = 'active'
                ORDER BY c.id
            ''', doc_ids).fetchall()
            conn.close()

            scored = []
            for row in rows:
                item = dict(row)
                content = item.get('content') or ''
                haystack = f"{item.get('section_title') or ''}\n{content}".lower()
                if keywords:
                    score = 0
                    for keyword in keywords:
                        key = keyword.lower()
                        if not key:
                            continue
                        occurrences = haystack.count(key)
                        if occurrences:
                            score += 10 + occurrences
                    if score <= 0:
                        continue
                else:
                    score = 1
                item['score'] = score
                scored.append(item)

            scored.sort(key=lambda x: (-x.get('score', 0), x.get('id', 0)))
            return scored[:limit]
        except Exception as e:
            self.logger.error(f"Error searching manual chunks: {e}")
            return []

    def search_knowledge_chunks(self, knowledge_type, keywords=None, product_model=None, source_kind=None, limit=5):
        """Search active knowledge chunks in a specific knowledge layer."""
        try:
            keywords = [str(k).strip() for k in (keywords or []) if str(k).strip()]
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            clauses = ["d.knowledge_type = ?", "d.status = 'active'", "c.status = 'active'"]
            params = [knowledge_type]
            if product_model:
                clauses.append("(d.product_model = '' OR lower(d.product_model) = lower(?))")
                params.append(product_model)
            if source_kind:
                clauses.append("d.source_kind = ?")
                params.append(source_kind)

            rows = cursor.execute(f'''
                SELECT c.*, d.title, d.source_kind, d.source_url, d.source_path
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                WHERE {' AND '.join(clauses)}
                ORDER BY d.id, c.id
            ''', params).fetchall()
            conn.close()

            scored = []
            for row in rows:
                item = dict(row)
                content = item.get('content') or ''
                haystack = f"{item.get('title') or ''}\n{item.get('section_title') or ''}\n{content}".lower()
                if keywords:
                    score = 0
                    for keyword in keywords:
                        key = keyword.lower()
                        if not key:
                            continue
                        occurrences = haystack.count(key)
                        if occurrences:
                            score += 10 + occurrences
                    if score <= 0:
                        continue
                else:
                    score = 1
                item['score'] = score
                scored.append(item)

            scored.sort(key=lambda x: (-x.get('score', 0), x.get('id', 0)))
            return scored[:limit]
        except Exception as e:
            self.logger.error(f"Error searching knowledge chunks: {e}")
            return []

    # ── End of new CRUD methods ──

    def scan_gs1000_balance_output_issue(self):
        """Find and bucket GS1000 balance-output complaints after updates."""
        issue_data = {
            'product_model': 'GS1000',
            'issue_title': 'GS1000 balance output issue after firmware update',
            'issue_category': 'Audio Output / Firmware Update',
            'issue_signature': 'gs1000_firmware_balance_output',
            'status': 'new_detected',
            'priority': 'High',
            'rnd_status': 'needs_review',
        }

        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT *
                FROM emails
                WHERE
                    (
                        upper(COALESCE(product_model, '')) LIKE '%GS1000%'
                        OR upper(COALESCE(subject, '')) LIKE '%GS1000%'
                        OR upper(COALESCE(body, '')) LIKE '%GS1000%'
                    )
                    AND (
                        lower(COALESCE(subject, '')) LIKE '%balance%'
                        OR lower(COALESCE(body, '')) LIKE '%balance%'
                        OR lower(COALESCE(subject, '')) LIKE '%balanced output%'
                        OR lower(COALESCE(body, '')) LIKE '%balanced output%'
                        OR COALESCE(subject, '') LIKE '%平衡%'
                        OR COALESCE(body, '') LIKE '%平衡%'
                    )
                    AND (
                        lower(COALESCE(subject, '')) LIKE '%update%'
                        OR lower(COALESCE(body, '')) LIKE '%update%'
                        OR lower(COALESCE(subject, '')) LIKE '%firmware%'
                        OR lower(COALESCE(body, '')) LIKE '%firmware%'
                        OR COALESCE(subject, '') LIKE '%更新%'
                        OR COALESCE(body, '') LIKE '%更新%'
                        OR COALESCE(subject, '') LIKE '%升级%'
                        OR COALESCE(body, '') LIKE '%升级%'
                    )
                ORDER BY received_at DESC
            ''')
            matches = [dict(row) for row in cursor.fetchall()]
            conn.close()

            issue_id = self.upsert_support_issue(issue_data)
            linked_count = self.link_emails_to_issue(
                issue_id,
                matches,
                confidence=0.92,
                matched_by='gs1000_balance_output_keyword_scan'
            )

            linked_emails = self.get_issue_emails(issue_id) if issue_id else []
            unique_users = sorted({
                self._extract_email_address(row.get('sender'))
                for row in linked_emails
                if self._extract_email_address(row.get('sender'))
            })

            return {
                'issue_id': issue_id,
                'matched_count': len(matches),
                'linked_count': linked_count,
                'total_linked_emails': len(linked_emails),
                'unique_user_count': len(unique_users),
                'unique_users': unique_users,
                'issue': issue_data,
            }
        except Exception as e:
            self.logger.error(f"Error scanning GS1000 balance output issue: {e}")
            return {
                'issue_id': None,
                'matched_count': 0,
                'linked_count': 0,
                'total_linked_emails': 0,
                'unique_user_count': 0,
                'unique_users': [],
                'issue': issue_data,
                'error': str(e),
            }
