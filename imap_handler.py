import imaplib
import email
from email.header import decode_header
import email.utils
import logging
import yaml
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class IMAPHandler:
    """Handles IMAP operations for reading emails and saving drafts"""
    
    def __init__(self, config_path=None):
        """Initialize IMAPHandler with configuration"""
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_path)
        self.imap = None
        self.smtp = None
    
    def _load_config(self, config_path):
        """Load configuration from YAML file or environment variables"""
        config = {}
        
        # Try to load from YAML file if provided
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        else:
            # Load from environment variables
            config = {
                'email': {
                    'address': os.getenv('EMAIL_ADDRESS', 'support@mooeraudio.com'),
                    'password': os.getenv('EMAIL_PASSWORD', ''),
                    'imap': {
                        'server': os.getenv('IMAP_SERVER', 'imap.example.com'),
                        'port': int(os.getenv('IMAP_PORT', 993)),
                        'ssl': os.getenv('IMAP_SSL', 'True').lower() == 'true',
                        'folder': os.getenv('IMAP_FOLDER', 'INBOX')
                    },
                    'smtp': {
                        'server': os.getenv('SMTP_SERVER', 'smtp.example.com'),
                        'port': int(os.getenv('SMTP_PORT', 465)),
                        'ssl': os.getenv('SMTP_SSL', 'True').lower() == 'true'
                    },
                    'draft_folder': os.getenv('DRAFT_FOLDER', 'Drafts')
                }
            }
        
        return config
    
    def connect_imap(self):
        """Connect to the IMAP server"""
        try:
            if self.config['email']['imap']['ssl']:
                self.imap = imaplib.IMAP4_SSL(
                    self.config['email']['imap']['server'],
                    self.config['email']['imap']['port']
                )
            else:
                self.imap = imaplib.IMAP4(
                    self.config['email']['imap']['server'],
                    self.config['email']['imap']['port']
                )
            
            # Login to the server
            self.imap.login(
                self.config['email']['address'],
                self.config['email']['password']
            )
            
            self.logger.info(f"Connected to IMAP server: {self.config['email']['imap']['server']}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to IMAP server: {e}")
            return False
    
    def disconnect_imap(self):
        """Disconnect from the IMAP server"""
        if self.imap:
            try:
                self.imap.logout()
                self.logger.info("Disconnected from IMAP server")
            except Exception as e:
                self.logger.error(f"Error disconnecting from IMAP server: {e}")
            finally:
                self.imap = None
    
    def get_unread_emails(self, max_emails=10):
        """Get unread emails from the INBOX"""
        emails = []
        
        if not self.imap:
            if not self.connect_imap():
                return emails
        
        try:
            # Select the inbox
            status, messages = self.imap.select(self.config['email']['imap']['folder'])
            if status != 'OK':
                self.logger.error(f"Failed to select mailbox: {status}")
                return emails
            
            # Get number of messages
            messages = int(messages[0])
            self.logger.info(f"Found {messages} messages in inbox")
            
            # Fetch unread emails
            status, response = self.imap.search(None, '(UNSEEN)')
            if status != 'OK':
                self.logger.error(f"Failed to search for unread emails: {status}")
                return emails
            
            # Process email IDs
            email_ids = response[0].split()
            if not email_ids:
                self.logger.info("No unread emails found")
                return emails
            
            # Limit the number of emails to process
            email_ids = email_ids[-min(max_emails, len(email_ids)):]
            
            # Fetch each email
            for email_id in email_ids:
                if isinstance(email_id, bytes):
                    email_id_str = email_id.decode('utf-8')
                else:
                    email_id_str = str(email_id)

                status, msg_data = self.imap.fetch(email_id_str, '(RFC822)')
                if status != 'OK':
                    self.logger.error(f"Failed to fetch email {email_id_str}: {status}")
                    continue
                
                # Parse the email
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        email_data = self._parse_email(msg)
                        email_data['id'] = email_id_str
                        emails.append(email_data)

            
            self.logger.info(f"Fetched {len(emails)} unread emails")
            return emails
            
        except Exception as e:
            self.logger.error(f"Error getting unread emails: {e}")
            return emails
    
    def _parse_email(self, msg):
        """Parse email content"""
        # Decode email subject
        try:
            subject, encoding = decode_header(msg['Subject'])[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or 'utf-8', errors='replace')
        except Exception:
            subject = str(msg['Subject'])
        
        # Decode email sender
        try:
            sender, encoding = decode_header(msg['From'])[0]
            if isinstance(sender, bytes):
                sender = sender.decode(encoding or 'utf-8', errors='replace')
        except Exception:
            sender = str(msg['From'])
        
        # Get email date
        date = msg.get('Date', '')
        
        # Get Message-ID
        message_id = msg.get('Message-ID', '')
        
        # Get email body
        body = ""
        html_body = ""
        
        # Helper to extract body from payload
        def get_payload_decoded(part):
            charset = part.get_content_charset() or 'utf-8'
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(charset, errors='replace')
            except Exception as e:
                self.logger.error(f"Error decoding payload: {e}")
            return ""

        if msg.is_multipart():
            # Iterate over email parts
            for part in msg.walk():
                # Skip attachments
                if part.get_content_disposition() is not None:
                    continue
                
                content_type = part.get_content_type()
                
                # Get text/plain content
                if content_type == 'text/plain' and not body:
                    body = get_payload_decoded(part)
                
                # Get text/html content
                elif content_type == 'text/html' and not html_body:
                    html_body = get_payload_decoded(part)
        else:
            # If email is not multipart
            content_type = msg.get_content_type()
            decoded = get_payload_decoded(msg)
            
            if content_type == 'text/plain':
                body = decoded
            elif content_type == 'text/html':
                html_body = decoded
                # Try to get plain text from HTML if body is empty
                if not body:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html_body, 'html.parser')
                        body = soup.get_text(separator='\n')
                    except Exception:
                        pass # bs4 might not be installed

        # If body is still empty but we have html_body, try to extract text
        if not body and html_body:
            try:
                # Remove HTML tags (simple regex fallback if bs4 fails/not available)
                import re
                body = re.sub(r'<[^>]+>', '\n', html_body)
                body = re.sub(r'\n+', '\n', body).strip()
            except Exception:
                pass

        return {
            'subject': subject,
            'sender': sender,
            'date': date,
            'message_id': message_id,
            'body': body,
            'html_body': html_body
        }
    
    def save_draft(self, recipient, subject, body, original_msg_id=None, original_html=None, original_sender=None, original_date=None):
        """Save an email as a draft with reply formatting"""
        try:
            if not self.imap:
                if not self.connect_imap():
                    return False
            
            # Create a MIME email message
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.header import Header
            import time
            import html
            
            # Create message container
            msg = MIMEMultipart('alternative')
            
            # Set headers
            msg['From'] = self.config['email']['address']
            msg['To'] = recipient
            
            # Handle Subject (add RE: if not present)
            if not subject.lower().startswith('re:'):
                msg['Subject'] = Header(f"Re: {subject}", 'utf-8')
            else:
                msg['Subject'] = Header(subject, 'utf-8')
            
            # Set message date
            msg['Date'] = email.utils.formatdate(localtime=True)
            
            # Set Reply headers if original message ID is provided
            if original_msg_id:
                msg['In-Reply-To'] = original_msg_id
                msg['References'] = original_msg_id
            
            # --- Construct Plain Text Body ---
            # NOTE: For this implementation, we assume 'body' is just the NEW response text.
            # We will construct the full body.
            
            # 1. Plain Text Part
            full_plain_text = body
            if original_sender and original_date:
                 full_plain_text += f"\n\nOn {original_date}, {original_sender} wrote:\n> ..."
            
            msg.attach(MIMEText(full_plain_text, 'plain', 'utf-8'))
            
            # --- Construct HTML Body ---
            # Convert new response to HTML (simple conversion)
            # Replace newlines with <br>
            new_response_html = html.escape(body).replace('\n', '<br>')
            
            full_html = f'<div dir="ltr">{new_response_html}</div>'
            
            if original_html:
                # Append original HTML
                full_html += f'<br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">On {original_date}, {html.escape(original_sender or "")} wrote:<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">{original_html}</blockquote></div>'
            elif original_sender and original_date:
                 # Fallback if no HTML available but we have metadata
                 full_html += f'<br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">On {original_date}, {html.escape(original_sender)} wrote:<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">...</blockquote></div>'

            msg.attach(MIMEText(full_html, 'html', 'utf-8'))
            
            # Convert message to bytes
            msg_bytes = msg.as_bytes()
            
            # Append the message to the Drafts folder
            # Using \Draft special flag to mark as draft - correct IMAP format
            flags = '(\\Draft)'
            date_time = time.time()
            
            # Get the draft folder name
            draft_folder = self.config['email']['draft_folder']
            
            # Append the message
            status = self.imap.append(
                draft_folder,
                flags,
                imaplib.Time2Internaldate(date_time),
                msg_bytes
            )
            
            if status[0] == 'OK':
                self.logger.info(f"Draft saved for {recipient}: {subject}")
                return True
            else:
                self.logger.error(f"Failed to save draft: {status}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error saving draft: {e}")
            return False
    
    def mark_as_read(self, email_id):
        """Mark an email as read"""
        if not self.imap:
            if not self.connect_imap():
                return False
        
        try:
            self.imap.store(email_id, '+FLAGS', '(\Seen)')
            self.logger.info(f"Marked email {email_id} as read")
            return True
        except Exception as e:
            self.logger.error(f"Error marking email {email_id} as read: {e}")
            return False

    def add_label(self, email_id, label):
        """Add a label (keyword/flag) to an email"""
        if not self.imap:
            if not self.connect_imap():
                return False
        
        try:
            # IMAP keywords often need to be supported by the server
            # Common ones are $Label1, $Label2, etc. or custom keywords
            # For simplicity, we try to add it as a flag.
            # Note: Many servers treat custom flags as keywords.
            self.imap.store(email_id, '+FLAGS', f'({label})')
            self.logger.info(f"Added label {label} to email {email_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error adding label to email {email_id}: {e}")
            return False

if __name__ == "__main__":
    # Test the IMAPHandler
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Create IMAPHandler instance
    imap_handler = IMAPHandler()
    
    # Connect to IMAP server
    if imap_handler.connect_imap():
        # Get unread emails
        emails = imap_handler.get_unread_emails(max_emails=5)
        
        # Print email summaries
        for email in emails:
            print(f"\nSubject: {email['subject']}")
            print(f"From: {email['sender']}")
            print(f"Date: {email['date']}")
            print(f"Body snippet: {email['body'][:100]}...")
        
        # Disconnect
        imap_handler.disconnect_imap()
