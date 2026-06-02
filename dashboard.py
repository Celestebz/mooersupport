import streamlit as st
import pandas as pd
import os
import time
from database import DatabaseHandler
from datetime import datetime
import threading
import subprocess
import signal
from imap_handler import IMAPHandler
from response_generator import ResponseGenerator
from content_extractor import ContentExtractor

# Page Config
st.set_page_config(
    page_title="Mooer Support Agent Dashboard",
    page_icon="🎸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Database
db = DatabaseHandler()
imap_handler = IMAPHandler()

# Initialize generators (lazy load if possible, but here we init for simplicity)
templates_path = os.path.join(os.getcwd(), "售后模板", "Customer Service Email.txt")
pdf_reader_path = os.path.join(os.getcwd(), "pdf_reader.py")
product_manuals_path = os.path.join(os.getcwd(), "MOOER产品说明书")
response_generator = ResponseGenerator(templates_path, pdf_reader_path, product_manuals_path)
content_extractor = ContentExtractor()

# Helper function to run automation script
def run_automation():
    """Run the email automation script in a separate process"""
    # This is a simplified way to trigger the bot. In production, use a proper task queue.
    try:
        subprocess.Popen(["python", "email_automation.py", "--once"], 
                         cwd=os.getcwd(),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        st.toast("Bot triggered successfully!", icon="🚀")
    except Exception as e:
        st.error(f"Failed to start bot: {e}")

# Helper function to get Gmail draft count
def get_gmail_draft_count():
    """Get draft count from Gmail"""
    try:
        drafts = imap_handler.get_drafts(max_drafts=100)
        return len(drafts)
    except Exception as e:
        st.error(f"Failed to fetch Gmail drafts: {e}")
        return 0

# Sidebar
with st.sidebar:
    st.title("🎸 Mooer Support")
    st.markdown("---")

    # Fetch counts from Gmail for drafts, database for others
    drafted_count = get_gmail_draft_count()
    skipped_emails = db.get_emails(status='skipped')
    skipped_count = len(skipped_emails)
    parse_failed_count = sum(1 for e in skipped_emails if e.get('label') == 'Parse Failed')

    nav_options = [f"Inbox ({drafted_count})", f"Skipped ({skipped_count})", "Knowledge Base", "Logs"]
    page_selection = st.radio("Navigation", nav_options)
    page = page_selection.split(" (")[0]
    
    if parse_failed_count > 0:
        st.markdown("---")
        st.error(f"🚨 **Action Required!**\n\nThere are **{parse_failed_count}** emails that couldn't be parsed automatically. Please check the **Skipped** tab to reply manually.")
        
    st.markdown("---")
    st.subheader("Bot Control")
    if st.button("🔄 Trigger Bot Now"):
        run_automation()
        
    st.markdown("---")
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

# Helper function to match Gmail draft with database email
def match_draft_with_database(draft, db_emails):
    """Match a Gmail draft with a database email by subject"""
    # Remove "Re: " prefix from draft subject
    draft_subject = draft.get('subject', '')
    if draft_subject.lower().startswith('re:'):
        draft_subject = draft_subject[3:].strip()

    # Also try to extract original sender from draft body (quoted email)
    # The draft body contains the original email info after "On [date], [sender] wrote:"

    for email in db_emails:
        db_subject = email.get('subject', '')
        # Check if subjects match (fuzzy match)
        if db_subject.lower() == draft_subject.lower():
            return email

    return None

# Main Content
if page == "Inbox":
    st.header("📥 Inbox (Gmail Drafts)")

    # Fetch drafts from Gmail
    gmail_drafts = imap_handler.get_drafts(max_drafts=50)

    # Fetch all drafted emails from database for matching
    db_drafted_emails = db.get_emails(status='drafted')
    db_skipped_emails = db.get_emails(status='skipped')
    all_db_emails = db_drafted_emails + db_skipped_emails

    if not gmail_drafts:
        st.info("No drafts found in Gmail. Run the bot to generate drafts.")
    else:
        st.info(f"📬 Found {len(gmail_drafts)} drafts in Gmail. Synced with your edits in real-time.")

        # Show drafts grouped by original email
        for draft in gmail_drafts:
            # Try to match with database
            matched_email = match_draft_with_database(draft, all_db_emails)

            # Get draft body (the AI generated response)
            draft_body = draft.get('body', '')

            # Extract quoted original email if present
            original_info = ""
            if 'On ' in draft_body and ' wrote:' in draft_body:
                try:
                    # Extract the quoted part
                    quote_start = draft_body.find('On ')
                    quote_text = draft_body[quote_start:]
                    original_info = quote_text[:500]  # Limit length
                    # Remove quoted part from display
                    draft_body = draft_body[:quote_start].strip()
                except:
                    pass

            with st.expander(f"📧 [ID: {draft.get('id', 'N/A')}] {draft.get('subject', 'No Subject')}", expanded=False):
                col1, col2 = st.columns([1, 1])

                with col1:
                    st.subheader("Original Email")
                    if matched_email:
                        # Show matched database info
                        received_time = matched_email.get('received_at', 'N/A')
                        if received_time and received_time != 'N/A':
                            try:
                                if isinstance(received_time, str):
                                    dt = datetime.fromisoformat(received_time.replace('Z', '+00:00'))
                                    received_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                            except:
                                pass
                        st.markdown(f"**📅 Received:** {received_time}")
                        st.text_area("Original Body", matched_email.get('body', '')[:2000], height=200, disabled=True, key=f"original_body_{draft.get('id')}")

                        # Display Attachments
                        if matched_email.get('attachments'):
                            try:
                                import json
                                attachments = json.loads(matched_email['attachments'])
                                if attachments:
                                    st.markdown("#### 📎 Attachments")
                                    for att in attachments:
                                        st.markdown(f"- **{att['filename']}** ({att['size']})")
                            except Exception:
                                pass

                        st.info(f"**AI Analysis**\n\nIntent: {matched_email.get('ai_intent', 'N/A')}\nSentiment: {matched_email.get('ai_sentiment', 'N/A')}\nProduct: {matched_email.get('product_model', 'Unknown')}")
                    else:
                        st.warning("⚠️ Original email not found in database")
                        if original_info:
                            st.text_area("Quoted Email", original_info, height=150, disabled=True, key=f"quoted_email_{draft.get('id')}")

                with col2:
                    st.subheader("Gmail Draft Response")
                    # Text area for editing draft - this shows current Gmail draft content
                    edited_draft = st.text_area("Draft (edits sync with Gmail)", draft_body, height=300, key=f"gmail_draft_{draft.get('id')}")

                    st.markdown("### Actions")
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        if st.button("✅ Send", key=f"send_gmail_{draft.get('id')}", help="Send this email"):
                            # Extract recipient from draft
                            import re
                            recipient = None
                            # Try to get from matched email first
                            if matched_email:
                                sender = matched_email.get('sender', '')
                                match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender)
                                if match:
                                    recipient = match.group()

                            if not recipient:
                                # Try from original_info
                                if original_info:
                                    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', original_info)
                                    if match:
                                        recipient = match.group()

                            if recipient:
                                with st.spinner('Sending email...'):
                                    # Use the edited draft content
                                    current_draft = st.session_state.get(f"gmail_draft_{draft.get('id')}", draft_body)

                                    success = imap_handler.send_email(
                                        recipient=recipient,
                                        subject=draft.get('subject', ''),
                                        body=current_draft,
                                        original_sender=matched_email.get('sender', '') if matched_email else None,
                                        original_date=matched_email.get('received_at', '') if matched_email else None
                                    )

                                    if success:
                                        # Delete draft from Gmail
                                        imap_handler.delete_draft(draft.get('id'))
                                        # Update database if matched
                                        if matched_email:
                                            db.update_email_status(matched_email['id'], 'sent', draft_body=current_draft)
                                        st.toast("Email sent successfully!", icon="✅")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error("Failed to send email.")
                            else:
                                st.error("Could not find recipient email.")

                    with c2:
                        if st.button("🗑️ Delete", key=f"delete_gmail_{draft.get('id')}", help="Delete this draft"):
                            imap_handler.delete_draft(draft.get('id'))
                            if matched_email:
                                db.update_email_status(matched_email['id'], 'skipped', reasoning="Draft deleted from Gmail")
                            st.toast("Draft deleted", icon="🗑️")
                            time.sleep(1)
                            st.rerun()

                    with c3:
                        if st.button("🔄 Regenerate", key=f"regenerate_gmail_{draft.get('id')}", help="Regenerate AI response"):
                            if matched_email:
                                with st.spinner('Regenerating AI response...'):
                                    # Prepare email_info dict
                                    email_info = {
                                        'product_model': matched_email.get('product_model', 'Unknown'),
                                        'problem_category': matched_email.get('ai_intent', 'Technical Support'),
                                        'sentiment': matched_email.get('ai_sentiment', 'Neutral'),
                                        'language': matched_email.get('language', 'en')
                                    }
                                    email_content = matched_email.get('body', '')

                                    # Generate new response using AI
                                    new_response = response_generator.generate_response(email_info, email_content)

                                    if new_response:
                                        # Update the Gmail draft with new response
                                        # First get the current draft to preserve original email info
                                        current_draft_content = st.session_state.get(f"gmail_draft_{draft.get('id')}", draft_body)

                                        # Extract quoted original if present
                                        original_email_text = ""
                                        if 'On ' in current_draft_content and ' wrote:' in current_draft_content:
                                            quote_idx = current_draft_content.find('On ')
                                            original_email_text = current_draft_content[quote_idx:]

                                        # Create new draft body
                                        new_draft_body = new_response
                                        if original_email_text:
                                            new_draft_body += f"\n\n{original_email_text}"

                                        # Delete old draft and create new one
                                        imap_handler.delete_draft(draft.get('id'))

                                        # Get recipient
                                        import re
                                        recipient = None
                                        sender = matched_email.get('sender', '')
                                        match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender)
                                        if match:
                                            recipient = match.group()

                                        if recipient:
                                            imap_handler.save_draft(
                                                recipient=recipient,
                                                subject=draft.get('subject', ''),
                                                body=new_draft_body
                                            )
                                            st.toast("Response regenerated!", icon="🔄")
                                            time.sleep(1)
                                            st.rerun()
                                    else:
                                        st.error("Failed to generate new response.")
                            else:
                                st.warning("No matched email found. Cannot regenerate.")

                    with c4:
                        if st.button("🔃 Sync", key=f"sync_gmail_{draft.get('id')}", help="Refresh from Gmail"):
                            st.toast("Syncing...", icon="🔄")
                            time.sleep(0.5)
                            st.rerun()

        # Also show any database drafts that don't have corresponding Gmail drafts
        if db_drafted_emails:
            st.markdown("---")
            st.subheader("⚠️ Database-only Drafts (not in Gmail)")

            for email in db_drafted_emails:
                # Check if this email has a corresponding Gmail draft
                matched = False
                for draft in gmail_drafts:
                    draft_subject = draft.get('subject', '')
                    if draft_subject.lower().startswith('re:'):
                        draft_subject = draft_subject[3:].strip()
                    if draft_subject.lower() == email.get('subject', '').lower():
                        matched = True
                        break

                if not matched:
                    with st.expander(f"⚠️ [DB Only] {email['subject']}"):
                        st.warning("This draft exists in database but not in Gmail. Run the bot to sync.")
                        st.text_area("Draft", email.get('draft_body', ''), height=200, disabled=True, key=f"db_draft_{email['id']}")

elif page == "Skipped":
    st.header("🚫 Skipped Emails")

    emails = db.get_emails(status='skipped')

    if not emails:
        st.info("No skipped emails found.")
    else:
        for email in emails:
            # 显示标签（如果存在）
            label_display = f"🏷️ **{email['label']}**" if email.get('label') else ""
            with st.expander(f"[ID: {email['id']}] [{email['ai_intent']}] {email['subject']} - {email['sender']} {label_display}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Label:** {email.get('label', 'N/A')}")
                with col2:
                    st.write(f"**Intent:** {email['ai_intent']}")
                st.write(f"**Reasoning:** {email['ai_reasoning']}")
                st.text_area("Content", email['body'], height=150, disabled=True, key=f"content_{email['id']}")
                
                # Display Attachments
                if email['attachments']:
                    try:
                        import json
                        attachments = json.loads(email['attachments'])
                        if attachments:
                            st.markdown("#### 📎 Attachments")
                            for att in attachments:
                                st.markdown(f"- **{att['filename']}** ({att['size']})")
                    except Exception:
                        pass
                
                if st.button("Restore to Inbox", key=f"restore_{email['id']}"):
                    db.update_email_status(email['id'], 'drafted')
                    st.toast("Restored to Inbox!", icon="📥")
                    time.sleep(1)
                    st.rerun()

elif page == "Knowledge Base":
    st.header("📚 Knowledge Base")
    
    # File Uploader
    uploaded_file = st.file_uploader("Upload Product Manual (PDF)", type="pdf")
    
    if uploaded_file:
        save_path = os.path.join("MOOER产品说明书", uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"Saved {uploaded_file.name} to Knowledge Base!")
    
    # List existing files
    st.subheader("Existing Manuals")
    manuals_dir = "MOOER产品说明书"
    if os.path.exists(manuals_dir):
        files = os.listdir(manuals_dir)
        pdf_files = [f for f in files if f.endswith('.pdf')]
        
        for f in pdf_files:
            st.text(f"📄 {f}")
    else:
        st.warning("Manuals directory not found!")

elif page == "Logs":
    st.header("📝 System Logs")
    
    logs = db.get_logs(limit=50)
    if logs:
        df_logs = pd.DataFrame(logs)
        st.dataframe(df_logs, use_container_width=True, width='stretch')
    else:
        st.info("No logs available.")

# Footer
st.markdown("---")
st.caption("Mooer Support Agent v2.0 - Powered by LLM")
