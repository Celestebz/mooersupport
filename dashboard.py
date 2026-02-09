import streamlit as st
import pandas as pd
import os
import time
from database import DatabaseHandler
from datetime import datetime
import threading
import subprocess
import signal

# Page Config
st.set_page_config(
    page_title="Mooer Support Agent Dashboard",
    page_icon="🎸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Database
db = DatabaseHandler()

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

# Sidebar
with st.sidebar:
    st.title("🎸 Mooer Support")
    st.markdown("---")
    
    page = st.radio("Navigation", ["Inbox", "Skipped", "Knowledge Base", "Logs"])
    
    st.markdown("---")
    st.subheader("Bot Control")
    if st.button("🔄 Trigger Bot Now"):
        run_automation()
        
    st.markdown("---")
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

# Main Content
if page == "Inbox":
    st.header("📥 Inbox (Drafted Responses)")
    
    # Fetch drafted emails
    emails = db.get_emails(status='drafted')
    
    if not emails:
        st.info("No drafted emails waiting for review.")
    else:
        # Convert to DataFrame for easier display
        df = pd.DataFrame(emails)
        
        # Display list
        for index, row in df.iterrows():
            with st.expander(f"{row['subject']} ({row['sender']}) - {row['product_model'] or 'Unknown Model'}", expanded=False):
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    st.subheader("Original Email")
                    st.text_area("Body", row['body'], height=300, disabled=True, key=f"orig_{row['id']}")
                    
                    st.info(f"**AI Analysis**\n\nIntent: {row['ai_intent']}\nSentiment: {row['ai_sentiment']}")
                
                with col2:
                    st.subheader("AI Draft Response")
                    st.text_area("Draft", row['draft_body'], height=300, key=f"draft_{row['id']}")
                    
                    st.markdown("### Actions")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.button("✅ Approve & Send", key=f"send_{row['id']}", disabled=True, help="Sending feature coming soon")
                    with c2:
                        st.button("✏️ Edit Draft", key=f"edit_{row['id']}", disabled=True)
                    with c3:
                        st.button("🗑️ Reject", key=f"reject_{row['id']}", disabled=True)

elif page == "Skipped":
    st.header("🚫 Skipped Emails")
    
    emails = db.get_emails(status='skipped')
    
    if not emails:
        st.info("No skipped emails found.")
    else:
        for email in emails:
            with st.expander(f"[{email['ai_intent']}] {email['subject']} - {email['sender']}"):
                st.write(f"**Reasoning:** {email['ai_reasoning']}")
                st.text_area("Content", email['body'], height=150, disabled=True)
                st.button("Restore to Inbox", key=f"restore_{email['id']}", disabled=True)

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
        st.dataframe(df_logs, use_container_width=True)
    else:
        st.info("No logs available.")

# Footer
st.markdown("---")
st.caption("Mooer Support Agent v2.0 - Powered by LLM")
