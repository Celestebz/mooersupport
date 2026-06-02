import sqlite3
import os
import json
import logging
from datetime import datetime

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
            
            conn.commit()
            conn.close()
            self.logger.info("Database initialized successfully")
        except Exception as e:
            self.logger.error(f"Error initializing database: {e}")

    def add_email(self, email_data):
        """Add a new email to the database"""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT OR IGNORE INTO emails (id, sender, subject, body, received_at, status, is_read, attachments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                email_data['id'],
                email_data['sender'],
                email_data['subject'],
                email_data['body'],
                email_data.get('date', datetime.now().isoformat()),
                'new',
                False,
                json.dumps(email_data.get('attachments', []))
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error adding email: {e}")
            return False

    def update_email_ai_analysis(self, email_id, analysis_result):
        """Update email with AI analysis results"""
        try:
            conn = self._connect()
            cursor = conn.cursor()
            
            cursor.execute('''
            UPDATE emails 
            SET ai_intent = ?, ai_sentiment = ?, product_model = ?
            WHERE id = ?
            ''', (
                analysis_result.get('intent'),
                analysis_result.get('sentiment'),
                analysis_result.get('product_model'),
                email_id
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.error(f"Error updating AI analysis: {e}")

    def update_email_status(self, email_id, status, draft_body=None, reasoning=None, label=None, last_error=None, increment_attempts=False):
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

            if increment_attempts:
                update_fields.append("processing_attempts = COALESCE(processing_attempts, 0) + 1")

            params.append(email_id)
            
            sql = f"UPDATE emails SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(sql, params)
            
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.error(f"Error updating email status: {e}")

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
