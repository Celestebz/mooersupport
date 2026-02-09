---
name: mooer-support
description: "Mooer Audio Customer Support Automation. Use this skill when you need to: (1) Check for new customer emails and generate draft responses, (2) Analyze customer inquiries about specific products (e.g., GE150, Prime P1), or (3) Run the automated email processing workflow."
---

# Mooer Audio Customer Support Automation

## Overview

This skill allows you to operate the Mooer Audio automated support system. The system fetches unread emails, analyzes their content (product model, issue category, sentiment), retrieves relevant technical info from manuals, and generates professional English responses using either rule-based templates or Generative AI.

## Workflows

### 1. Process New Emails (One-Off Check)
Use this workflow to manually trigger a single pass of email checking and processing. This will fetch unread emails, generate drafts, and mark them as read.

**Command:**
```bash
python email_automation.py --once
```

### 2. Start Continuous Automation
Use this workflow to start the background service that checks for emails every 5 minutes.

**Command:**
```bash
python email_automation.py --interval 5
```

### 3. Generate Response for Specific Inquiry
(Note: Currently the system is designed to read from IMAP. To generate a response for a specific text, you would typically use the `ai_handler.py` or `response_generator.py` modules directly if you were writing a script, but for general operation, use the email automation workflow).

## File Structure

- `email_automation.py`: Main entry point. Handles IMAP connection and orchestrates the workflow.
- `content_extractor.py`: Analyzes email text to extract product models and intent.
- `response_generator.py`: Generates the response body using templates or AI.
- `ai_handler.py`: Interface to the LLM (if enabled in .env).
- `pdf_reader.py`: Extracts technical specs from product manuals.

## Configuration

Ensure the `.env` file is configured with:
- Email credentials (IMAP/SMTP)
- LLM API keys (if AI features are desired)
