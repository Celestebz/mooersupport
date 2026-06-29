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
                config = yaml.safe_load(f) or {}
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

        email_config = config.setdefault('email', {})
        # Keep secrets out of config.yml. Environment variables always win.
        email_config['address'] = os.getenv('EMAIL_ADDRESS', email_config.get('address', 'support@mooeraudio.com'))
        email_config['password'] = os.getenv('EMAIL_PASSWORD', email_config.get('password', ''))
        
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

            # Fetch unread emails by UID. Sequence numbers are not stable: when
            # messages are moved/deleted, the same sequence number can point to
            # a different email. UIDs are stable within the mailbox and are safe
            # to store in the database.
            status, response = self.imap.uid('SEARCH', None, '(UNSEEN)')
            if status != 'OK':
                self.logger.error(f"Failed to search for unread emails: {status}")
                return emails

            # Process email UIDs
            email_uids = response[0].split()
            if not email_uids:
                self.logger.info("No unread emails found")
                return emails

            # Limit the number of emails to process
            email_uids = email_uids[-min(max_emails, len(email_uids)):]

            # Fetch each email
            for email_uid in email_uids:
                if isinstance(email_uid, bytes):
                    email_id_str = email_uid.decode('utf-8')
                else:
                    email_id_str = str(email_uid)

                # BODY.PEEK[] reads the message without setting the \Seen flag.
                status, msg_data = self.imap.uid('FETCH', email_id_str, '(BODY.PEEK[])')
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
            decoded_subject_parts = decode_header(msg['Subject'])
            subject_parts = []
            for part, encoding in decoded_subject_parts:
                if isinstance(part, bytes):
                    subject_parts.append(part.decode(encoding or 'utf-8', errors='replace'))
                else:
                    subject_parts.append(str(part))
            subject = ''.join(subject_parts)
        except Exception:
            subject = str(msg['Subject'])
        
        # Decode email sender
        try:
            decoded_sender_parts = decode_header(msg['From'])
            sender_parts = []
            for part, encoding in decoded_sender_parts:
                if isinstance(part, bytes):
                    sender_parts.append(part.decode(encoding or 'utf-8', errors='replace'))
                else:
                    sender_parts.append(str(part))
            sender = ''.join(sender_parts)
        except Exception:
            sender = str(msg['From'])
            
        # Decode Reply-To
        reply_to = ''
        if msg['Reply-To']:
            try:
                decoded_reply_parts = decode_header(msg['Reply-To'])
                reply_parts = []
                for part, encoding in decoded_reply_parts:
                    if isinstance(part, bytes):
                        reply_parts.append(part.decode(encoding or 'utf-8', errors='replace'))
                    else:
                        reply_parts.append(str(part))
                reply_to = ''.join(reply_parts)
            except Exception:
                reply_to = str(msg['Reply-To'])
        
        # Get email date
        date = msg.get('Date', '')
        
        # Get Message-ID
        message_id = msg.get('Message-ID', '')
        in_reply_to = msg.get('In-Reply-To', '')
        references = msg.get('References', '')

        # Get email CC
        cc_header = msg.get('CC', '')
        cc_list = []
        if cc_header:
            try:
                cc_decode, _ = decode_header(cc_header)
                if isinstance(cc_decode, list):
                    for cc_item, _ in cc_decode:
                        if isinstance(cc_item, bytes):
                            cc_item = cc_item.decode('utf-8', errors='replace')
                        if cc_item:
                            cc_list.append(cc_item)
                else:
                    if isinstance(cc_decode, bytes):
                        cc_decode = cc_decode.decode('utf-8', errors='replace')
                    if cc_decode:
                        cc_list.append(cc_decode)
            except Exception:
                pass

        # Get email body
        body = ""
        html_body = ""
        attachments = []
        
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

        # Helper to format file size
        def format_size(size_bytes):
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            else:
                return f"{size_bytes / (1024 * 1024):.1f} MB"

        if msg.is_multipart():
            # Iterate over email parts
            for part in msg.walk():
                # Check for attachments
                content_disposition = part.get_content_disposition()
                filename = part.get_filename()
                
                if filename or (content_disposition and content_disposition in ['attachment', 'inline']):
                    if not filename:
                        filename = "Untitled"
                    
                    # Decode filename if needed
                    try:
                        filename, encoding = decode_header(filename)[0]
                        if isinstance(filename, bytes):
                            filename = filename.decode(encoding or 'utf-8', errors='replace')
                    except Exception:
                        pass
                        
                    # Get size
                    payload = part.get_payload(decode=True)
                    size = len(payload) if payload else 0
                    
                    attachments.append({
                        "filename": filename,
                        "size": format_size(size)
                    })
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
            'reply_to': reply_to,
            'date': date,
            'message_id': message_id,
            'in_reply_to': in_reply_to,
            'references': references,
            'cc_list': cc_list,
            'body': body,
            'html_body': html_body,
            'attachments': attachments
        }
    
    def download_attachments(self, email_id):
        """Download all attachments from a specific email by UID.
        Returns list of dicts with {filename, filepath, content_type}."""
        import tempfile
        import os as _os

        attachments = []
        try:
            if not self.imap:
                if not self.connect_imap():
                    return attachments

            self.imap.select('INBOX')
            status, data = self.imap.uid('FETCH', email_id, '(BODY[])')
            if status != 'OK' or not data or not data[0]:
                return attachments

            import email as _email
            raw_email = data[0][1]
            msg = _email.message_from_bytes(raw_email)

            if not msg.is_multipart():
                return attachments

            for part in msg.walk():
                filename = part.get_filename()
                if not filename:
                    continue
                try:
                    from email.header import decode_header
                    fname, encoding = decode_header(filename)[0]
                    if isinstance(fname, bytes):
                        fname = fname.decode(encoding or 'utf-8', errors='replace')
                except Exception:
                    fname = filename

                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                # Save to temp dir
                tmpdir = tempfile.mkdtemp(prefix='mooer_attach_')
                filepath = _os.path.join(tmpdir, fname)
                with open(filepath, 'wb') as f:
                    f.write(payload)

                attachments.append({
                    'filename': fname,
                    'filepath': filepath,
                    'content_type': part.get_content_type(),
                })

            return attachments

        except Exception as e:
            self.logger.error(f"Error downloading attachments for {email_id}: {e}")
            return attachments

    def save_draft(self, recipient, subject, body, original_msg_id=None, original_html=None, original_sender=None, original_date=None, reply_mode=True, attachments=None):
        """Save an email as a draft with reply or forward formatting.

        reply_mode=True: customer reply with "Re:" subject and quoted original.
        reply_mode=False: internal forward with original email inline.
        attachments: list of dicts with {filename, filepath} to attach.
        """
        try:
            if not self.imap:
                if not self.connect_imap():
                    return False

            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
            from email.header import Header
            import time
            import html
            import os as _os

            has_attachments = attachments and len(attachments) > 0

            # Create message container - use 'mixed' if attachments, else 'alternative'
            if has_attachments:
                msg = MIMEMultipart('mixed')
            else:
                msg = MIMEMultipart('alternative')

            # Set headers
            msg['From'] = self.config['email']['address']
            msg['To'] = recipient

            # Handle Subject
            if reply_mode and not subject.lower().startswith('re:'):
                msg['Subject'] = Header(f"Re: {subject}", 'utf-8')
            else:
                msg['Subject'] = Header(subject, 'utf-8')

            # Set message date
            msg['Date'] = email.utils.formatdate(localtime=True)

            # Set Reply headers if original message ID is provided (reply mode only)
            if reply_mode and original_msg_id:
                msg['In-Reply-To'] = original_msg_id
                msg['References'] = original_msg_id

            # --- Construct Plain Text Body ---
            full_plain_text = body
            if reply_mode and original_sender and original_date:
                full_plain_text += f"\n\nOn {original_date}, {original_sender} wrote:\n> ..."
            elif not reply_mode and original_sender and original_date:
                # Forward mode: body already includes original email content
                # (from _build_rnd_forward_body). HTML uses original_html below.
                pass

            # --- Attach text/plain ---
            if has_attachments:
                # For mixed mode, wrap text parts in an 'alternative' sub-container
                alt_part = MIMEMultipart('alternative')
                alt_part.attach(MIMEText(full_plain_text, 'plain', 'utf-8'))

                # --- Construct HTML Body ---
                new_response_html = html.escape(body).replace('\n', '<br>')
                full_html = f'<div dir="ltr">{new_response_html}</div>'

                if not reply_mode and original_html:
                    # Forward mode: wrap original as quoted forward
                    forward_header = f'<br><div style="border:none;border-top:solid #B5C4DF 1.0pt;padding:3.0pt 0in 0in 0in"><p><b>---------- Forwarded message ---------</b><br>From: <b>{html.escape(original_sender or "")}</b><br>Date: {original_date}<br>Subject: {subject}<br>To: {html.escape(self.config["email"]["address"])}</p></div><br>'
                    full_html += forward_header + original_html
                elif reply_mode and original_html:
                    full_html += f'<br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">On {original_date}, {html.escape(original_sender or "")} wrote:<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">{original_html}</blockquote></div>'
                elif reply_mode and original_sender and original_date:
                    full_html += f'<br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">On {original_date}, {html.escape(original_sender)} wrote:<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">...</blockquote></div>'

                alt_part.attach(MIMEText(full_html, 'html', 'utf-8'))
                msg.attach(alt_part)

                # --- Attach files ---
                for att in attachments:
                    filepath = att.get('filepath', '')
                    filename = att.get('filename', 'attachment')
                    if not filepath or not _os.path.exists(filepath):
                        continue
                    with open(filepath, 'rb') as f:
                        file_data = f.read()
                    mime_part = MIMEBase('application', 'octet-stream')
                    mime_part.set_payload(file_data)
                    encoders.encode_base64(mime_part)
                    mime_part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                    msg.attach(mime_part)
            else:
                # No attachments: use simple alternative structure
                msg.attach(MIMEText(full_plain_text, 'plain', 'utf-8'))

                new_response_html = html.escape(body).replace('\n', '<br>')
                full_html = f'<div dir="ltr">{new_response_html}</div>'

                if not reply_mode and original_html:
                    forward_header = f'<br><div style="border:none;border-top:solid #B5C4DF 1.0pt;padding:3.0pt 0in 0in 0in"><p><b>---------- Forwarded message ---------</b><br>From: <b>{html.escape(original_sender or "")}</b><br>Date: {original_date}<br>Subject: {subject}<br>To: {html.escape(self.config["email"]["address"])}</p></div><br>'
                    full_html += forward_header + original_html
                elif reply_mode and original_html:
                    full_html += f'<br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">On {original_date}, {html.escape(original_sender or "")} wrote:<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">{original_html}</blockquote></div>'
                elif reply_mode and original_sender and original_date:
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

    def get_drafts(self, max_drafts=50):
        """Get all drafts from the Drafts folder"""
        drafts = []

        if not self.imap:
            if not self.connect_imap():
                return drafts

        try:
            # Select the Drafts folder
            draft_folder = self.config['email']['draft_folder']
            status, messages = self.imap.select(draft_folder)
            if status != 'OK':
                self.logger.error(f"Failed to select drafts folder: {status}")
                return drafts

            # Get number of messages
            messages_count = int(messages[0])
            self.logger.info(f"Found {messages_count} messages in drafts")

            if messages_count == 0:
                return drafts

            # Search for all draft messages
            status, response = self.imap.search(None, 'ALL')
            if status != 'OK':
                self.logger.error(f"Failed to search drafts: {status}")
                return drafts

            email_ids = response[0].split()
            if not email_ids:
                return drafts

            # Limit the number of drafts to process
            email_ids = email_ids[-min(max_drafts, len(email_ids)):]

            # Fetch each draft
            for email_id in email_ids:
                if isinstance(email_id, bytes):
                    email_id_str = email_id.decode('utf-8')
                else:
                    email_id_str = str(email_id)

                status, msg_data = self.imap.fetch(email_id_str, '(RFC822)')
                if status != 'OK':
                    self.logger.error(f"Failed to fetch draft {email_id_str}: {status}")
                    continue

                # Parse the email
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        draft_data = self._parse_email(msg)
                        draft_data['id'] = email_id_str
                        # Mark this as a draft
                        draft_data['is_draft'] = True
                        drafts.append(draft_data)

            self.logger.info(f"Fetched {len(drafts)} drafts from mailbox")
            return drafts

        except Exception as e:
            self.logger.error(f"Error getting drafts: {e}")
            return drafts

    def delete_draft(self, email_id):
        """Delete a draft from the Drafts folder"""
        if not self.imap:
            if not self.connect_imap():
                return False

        try:
            draft_folder = self.config['email']['draft_folder']
            self.imap.select(draft_folder)

            # Ensure email_id is a string
            if isinstance(email_id, bytes):
                email_id = email_id.decode('utf-8')

            # Move to trash or permanently delete
            status = self.imap.store(email_id, '+FLAGS', '(\\Deleted)')
            if status[0] == 'OK':
                # Expunge to permanently delete
                self.imap.expunge()
                self.logger.info(f"Deleted draft {email_id}")
                return True
            else:
                self.logger.error(f"Failed to delete draft: {status}")
                return False

        except Exception as e:
            self.logger.error(f"Error deleting draft: {e}")
            return False

    def mark_as_read(self, email_id):
        """Mark an email as read"""
        if not self.imap:
            if not self.connect_imap():
                return False

        try:
            # Make sure folder is selected
            self.imap.select(self.config['email']['imap']['folder'])

            # Ensure email_id is a string
            if isinstance(email_id, bytes):
                email_id = email_id.decode('utf-8')

            # get_unread_emails stores IMAP UIDs in the database, so use UID
            # STORE here as well.
            status, _ = self.imap.uid('STORE', email_id, '+FLAGS', '(\\Seen)')
            if status == 'OK':
                self.logger.info(f"Marked email {email_id} as read")
                return True
            self.logger.error(f"Failed to mark email {email_id} as read: {status}")
            return False
        except Exception as e:
            self.logger.error(f"Error marking email {email_id} as read: {e}")
            return False

    def add_label(self, email_id, label):
        """Add a label (keyword/flag) to an email"""
        if not self.imap:
            if not self.connect_imap():
                return False

        try:
            # Make sure folder is selected
            self.imap.select(self.config['email']['imap']['folder'])
            # IMAP keywords often need to be supported by the server
            # Common ones are $Label1, $Label2, etc. or custom keywords
            # For simplicity, we try to add it as a flag.
            # Note: Many servers treat custom flags as keywords.
            status, _ = self.imap.uid('STORE', email_id, '+FLAGS', f'({label})')
            if status == 'OK':
                self.logger.info(f"Added label {label} to email {email_id}")
                return True
            self.logger.error(f"Failed to add label {label} to email {email_id}: {status}")
            return False
        except Exception as e:
            self.logger.error(f"Error adding label to email {email_id}: {e}")
            return False

    def send_email(self, recipient, subject, body, original_msg_id=None, original_html=None, original_sender=None, original_date=None):
        """Send an email via SMTP"""
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.header import Header
        import html

        try:
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
            full_plain_text = body
            if original_sender and original_date:
                 full_plain_text += f"\n\nOn {original_date}, {original_sender} wrote:\n> ..."
            
            msg.attach(MIMEText(full_plain_text, 'plain', 'utf-8'))
            
            # --- Construct HTML Body ---
            new_response_html = html.escape(body).replace('\n', '<br>')
            full_html = f'<div dir="ltr">{new_response_html}</div>'
            
            if original_html:
                full_html += f'<br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">On {original_date}, {html.escape(original_sender or "")} wrote:<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">{original_html}</blockquote></div>'
            elif original_sender and original_date:
                 full_html += f'<br><div class="gmail_quote"><div dir="ltr" class="gmail_attr">On {original_date}, {html.escape(original_sender)} wrote:<br></div><blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">...</blockquote></div>'

            msg.attach(MIMEText(full_html, 'html', 'utf-8'))
            
            # Connect to SMTP server
            smtp_config = self.config['email']['smtp']
            if smtp_config['ssl']:
                server = smtplib.SMTP_SSL(smtp_config['server'], smtp_config['port'])
            else:
                server = smtplib.SMTP(smtp_config['server'], smtp_config['port'])
                server.starttls()
            
            # Login
            server.login(self.config['email']['address'], self.config['email']['password'])
            
            # Send email
            server.send_message(msg)
            server.quit()
            
            self.logger.info(f"Email sent to {recipient}: {subject}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending email: {e}")
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
