# Information Needed for Automated Email System Setup

To configure the automated email processing system that will monitor support@mooeraudio.com and generate draft responses, we need the following information:

## 1. Email Server Configuration

### IMAP Server (for reading emails)
- **IMAP Server Address**: e.g., imap.example.com
- **IMAP Port**: e.g., 993 (for SSL/TLS)
- **IMAP SSL/TLS Setting**: Yes/No

### SMTP Server (for saving drafts, if needed)
- **SMTP Server Address**: e.g., smtp.example.com
- **SMTP Port**: e.g., 465 (for SSL/TLS) or 587 (for STARTTLS)
- **SMTP SSL/TLS Setting**: Yes/No

## 2. Email Account Credentials
- **Email Address**: support@mooeraudio.com
- **Password**: The password for the email account
  - Note: If using two-factor authentication, you'll need to generate an "app password" instead

## 3. System Configuration

### Processing Settings
- **Processing Interval**: How often the system should check for new emails (e.g., every 5 minutes)
- **Draft Folder Name**: The name of the folder where drafts should be saved (e.g., "Drafts")
- **Maximum Emails per Run**: How many emails to process in each run (e.g., 10)

### Logging Settings
- **Log File Path**: Where to save system logs (e.g., "logs/email_automation.log")
- **Log Level**: Amount of detail in logs (DEBUG/INFO/WARNING/ERROR)

## 4. Existing Resources

The system will use the following existing files and folders, so please ensure they are accessible:
- **Product Manuals**: `e:\My Docment\Celeste\客服\MOOER产品说明书\`
- **Email Templates**: `e:\My Docment\Celeste\客服\售后模板\Customer Service Email.txt`
- **PDF Reader Script**: `e:\My Docment\Celeste\客服\pdf_reader.py`

## 5. Additional Preferences

- **Language Preference**: English (fixed for support responses)
- **Response Format**: Plain text (no HTML)
- **Template Selection**: Based on email content analysis

Once you provide this information, we can configure and test the automated email system.