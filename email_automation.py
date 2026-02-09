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
        self.max_emails_per_run = int(os.getenv('MAX_EMAILS_PER_RUN', 10))
        
        # Legacy tracking files (migration handled by skipping if ID exists in DB)
        # We now rely on DB for deduplication and processing status
        
        self.logger.info("Email Automation System initialized successfully")
    
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
        
        try:
            # Connect to IMAP server
            if not self.imap_handler.connect_imap():
                self.logger.error("Failed to connect to IMAP server, skipping this run")
                self.db.log_event("ERROR", "Failed to connect to IMAP server", "automation")
                return False
            
            # Get unread emails
            emails = self.imap_handler.get_unread_emails(max_emails=self.max_emails_per_run)
            
            if not emails:
                self.logger.info("No unread emails to process")
                self.imap_handler.disconnect_imap()
                return True
            
            # Process each email
            for email in emails:
                email_id = email['id']
                
                # Check if email has already been processed in DB
                existing_email = self.db.get_email_by_id(email_id)
                if existing_email and existing_email['status'] != 'new':
                    self.logger.info(f"Skipping already processed email: {email['subject']} (ID: {email_id})")
                    continue
                
                self.logger.info(f"Processing email: {email['subject']} from {email['sender']} (ID: {email_id})")
                self.db.log_event("INFO", f"Processing email: {email['subject']}", "automation")
                
                # Add to DB as 'new' if not exists
                if not existing_email:
                    self.db.add_email({
                        'id': email_id,
                        'sender': email['sender'],
                        'subject': email['subject'],
                        'body': email['body'],
                        'date': email.get('date')
                    })
                
                try:
                    # Clean and extract content
                    clean_body = self.content_extractor.clean_email_content(email['body'])
                    email_content = f"Subject: {email['subject']}\n\n{clean_body}"
                    
                    # Extract relevant information using AI
                    email_info = self.content_extractor.extract_info(email_content)
                    email_info['subject'] = email['subject']
                    email_info['body'] = clean_body
                    
                    # Log AI Analysis Result to DB
                    intent = email_info.get("problem_category", "Technical Support") 
                    self.db.update_email_ai_analysis(email_id, {
                        'intent': intent,
                        'sentiment': email_info.get('sentiment'),
                        'product_model': email_info.get('product_model')
                    })
                    
                    self.logger.info(f"AI Classification - Model: {email_info.get('product_model')}, Intent: {intent}, Sentiment: {email_info.get('sentiment')}")

                    # Check if email should be skipped based on AI Intent
                    should_skip = False
                    
                    # 0. Check for Distributor/Sales emails
                    sender_lower = email['sender'].lower()
                    if 'support@promusicals.com' in sender_lower:
                        self.logger.info(f"Detected distributor email: {email['subject']}")
                        self.imap_handler.add_label(email_id, 'Distributor')
                        self.db.update_email_status(email_id, 'skipped', reasoning="Distributor email")
                        continue

                    # 1. AI-Driven Triage
                    skip_intents = ["Spam", "Gratitude", "System Notification"]
                    
                    if intent in skip_intents:
                        should_skip = True
                        self.logger.info(f"Skipping email based on AI Intent: {intent}")
                        self.db.update_email_status(email_id, 'skipped', reasoning=f"AI Intent: {intent}")
                    
                    if should_skip:
                        # Mark as read but don't generate response
                        self.imap_handler.mark_as_read(email_id)
                        self.logger.info(f"Marked email as read but skipped response: {email['subject']}")
                        continue
                    
                    # Generate response
                    response_body = self.response_generator.generate_response(email_info, email_content)
                    
                    # Extract recipient email from sender field
                    recipient = self._extract_email_address(email['sender'])
                    
                    # Save as draft
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
                            self.logger.error(f"Could not extract recipient email from sender: {email['sender']}")
                            self.db.update_email_status(email_id, 'skipped', reasoning="Invalid recipient")
                        if not response_body:
                             self.logger.error(f"Failed to generate response body")
                             self.db.update_email_status(email_id, 'skipped', reasoning="Empty response generation")
                        
                except Exception as e:
                    self.logger.error(f"Error processing email {email['subject']}: {e}", exc_info=True)
                    self.db.log_event("ERROR", f"Error processing email {email['subject']}: {e}", "automation")
                    continue
            
            # Disconnect from IMAP server
            self.imap_handler.disconnect_imap()
            
            self.logger.info(f"Email processing run completed. Processed {len(emails)} emails.")
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
