import streamlit as st
import pandas as pd
import os
import time
import html
import re
import json
from datetime import datetime
import threading
import subprocess
import signal
from imap_handler import IMAPHandler
from response_generator import ResponseGenerator
from content_extractor import ContentExtractor
from api.client import APIClient

# Page Config
st.set_page_config(
    page_title="MOOER 客服系统",
    page_icon="🎸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize API Client (replaces direct DB access)
API_BASE = os.environ.get("MOOER_API_URL", "http://127.0.0.1:8100")
api = APIClient(base_url=API_BASE)
health_api = APIClient(base_url=API_BASE, timeout=0.8)

# IMAP handler（用于实时读取邮箱草稿）
imap_handler = IMAPHandler()

# Initialize generators（模板已迁移至数据库）
pdf_reader_path = os.path.join(os.getcwd(), "pdf_reader.py")
product_manuals_path = os.path.join(os.getcwd(), "MOOER产品说明书")
response_generator = ResponseGenerator(None, pdf_reader_path, product_manuals_path)
content_extractor = ContentExtractor()

# ── API health check (auto-start if needed) ──
_venv_py = os.path.join(
    os.environ.get("VIRTUAL_ENV", "C:\\Users\\USER\\.workbuddy\\binaries\\python\\envs\\mooer-api"),
    "Scripts", "python.exe"
)

_api_ok = False

@st.cache_data(ttl=30, show_spinner=False)
def get_cached_api_health():
    return health_api.health()


try:
    _api_ok = get_cached_api_health()
except Exception:
    _api_ok = False

if not _api_ok:
    # Auto-start once per Streamlit session. Avoid blocking every rerun when the API is down.
    if not st.session_state.get("_api_autostart_attempted"):
        st.session_state["_api_autostart_attempted"] = True
        try:
            subprocess.Popen(
                [_venv_py, "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8100"],
                cwd=os.getcwd(),
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            time.sleep(1)
            get_cached_api_health.clear()
            _api_ok = get_cached_api_health()
        except Exception:
            pass

# 触发邮件自动处理
def trigger_bot_via_api():
    """通过 API 触发邮件处理；API 不可用时退回本地脚本。"""
    if _api_ok:
        try:
            result = api.trigger_automation()
            if result.get("success"):
                clear_dashboard_caches()
                st.toast(
                    f"邮件处理已触发：处理 {result.get('processed', 0)} 封，"
                    f"生成草稿 {result.get('drafted', 0)} 封，"
                    f"错误 {result.get('errors', 0)} 个",
                    icon="🚀"
                )
            else:
                st.error(f"邮件处理失败: {result.get('log_lines', ['未知错误'])[:3]}")
        except Exception as e:
            st.error(f"API 调用失败: {e}")
    else:
        # Fallback: direct subprocess with venv python
        try:
            venv_python = os.path.join(
                os.environ.get("VIRTUAL_ENV", "C:\\Users\\USER\\.workbuddy\\binaries\\python\\envs\\mooer-api"),
                "Scripts", "python.exe"
            )
            subprocess.Popen(
                [venv_python, "email_automation.py", "--once"],
                cwd=os.getcwd(),
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            st.toast("邮件处理已触发（本地模式）", icon="🚀")
        except Exception as e:
            st.error(f"邮件处理启动失败: {e}")

# 邮箱草稿数量
@st.cache_data(ttl=60, show_spinner=False)
def get_cached_mail_drafts(max_drafts=100):
    """Short-lived IMAP cache; Streamlit reruns on every widget interaction."""
    return imap_handler.get_drafts(max_drafts=max_drafts)


@st.cache_data(ttl=10, show_spinner=False)
def get_cached_schedule_status():
    return api.schedule_status()


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_emails(status=None, limit=100):
    return api.list_emails(status=status, limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_email_thread(email_id, limit=20):
    return api.get_email_thread(email_id, limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_issues(limit=200):
    return api.list_issues(limit=limit)


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_issue_candidates(issue_id, limit=500):
    return api.get_issue_candidates(issue_id, limit=limit)


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_issue_emails(issue_id, limit=500):
    return api.get_issue_emails(issue_id, limit=limit)


@st.cache_data(ttl=20, show_spinner=False)
def get_cached_prices():
    return api.list_prices()


@st.cache_data(ttl=20, show_spinner=False)
def get_cached_templates(limit=200):
    return api.list_templates(limit=limit)


@st.cache_data(ttl=20, show_spinner=False)
def get_cached_knowledge_summary():
    return api.knowledge_summary()


@st.cache_data(ttl=20, show_spinner=False)
def get_cached_knowledge_documents(knowledge_type=None, status=None, limit=500):
    return api.list_knowledge_documents(
        knowledge_type=knowledge_type,
        status=status,
        limit=limit,
    )


@st.cache_data(ttl=10, show_spinner=False)
def get_cached_logs(limit=50):
    return api.list_logs(limit=limit)


def clear_dashboard_caches():
    get_cached_api_health.clear()
    get_cached_mail_drafts.clear()
    get_cached_schedule_status.clear()
    get_cached_emails.clear()
    get_cached_email_thread.clear()
    get_cached_issues.clear()
    get_cached_issue_candidates.clear()
    get_cached_issue_emails.clear()
    get_cached_prices.clear()
    get_cached_templates.clear()
    get_cached_knowledge_summary.clear()
    get_cached_knowledge_documents.clear()
    get_cached_logs.clear()


def rerun_after_mutation(delay=0):
    if delay:
        time.sleep(delay)
    clear_dashboard_caches()
    st.rerun()


def get_mail_draft_count():
    """读取邮箱草稿数量。"""
    try:
        drafts = get_cached_mail_drafts(max_drafts=100)
        return len(drafts)
    except Exception as e:
        st.error(f"获取邮箱草稿失败: {e}")
        return 0

# 侧边栏
with st.sidebar:
    st.title("🎸 MOOER 客服系统")
    st.markdown("---")

    # 获取数量：数据库走 API，邮箱草稿走 IMAP
    drafted_count = get_mail_draft_count()

    if _api_ok:
        try:
            skipped_resp = get_cached_emails(status='skipped', limit=100)
            skipped_emails = skipped_resp.get("items", [])
            skipped_count = skipped_resp.get("total", len(skipped_emails))
            parse_failed_count = sum(1 for e in skipped_emails if e.get('label') == 'Parse Failed')
        except Exception:
            skipped_emails = []
            skipped_count = 0
            parse_failed_count = 0

        try:
            issue_resp = get_cached_issues(limit=200)
            issues_all = issue_resp.get("items", [])
            issue_count = sum(1 for i in issues_all if i.get("status") not in ("closed", "bulk_replied"))
            total_issue_count = len(issues_all)
        except Exception:
            issues_all = []
            issue_count = 0
            total_issue_count = 0
    else:
        skipped_emails = []
        skipped_count = 0
        parse_failed_count = 0
        issues_all = []
        issue_count = 0
        total_issue_count = 0
    nav_options = [f"邮件草稿 ({drafted_count})", f"问题队列 ({issue_count}/{total_issue_count})", f"跳过邮件 ({skipped_count})", "知识库", "配件价格", "回复模板", "系统日志"]
    page_selection = st.radio("导航", nav_options)
    page = page_selection.split(" (")[0]
    
    if parse_failed_count > 0:
        st.markdown("---")
        st.error(f"🚨 **需要处理**\n\n有 **{parse_failed_count}** 封邮件无法自动解析，请到「跳过邮件」页面人工处理。")
        
    st.markdown("---")
    st.subheader("邮件处理")

    # Scheduler status
    if _api_ok:
        try:
            sched = get_cached_schedule_status()
            status_icon = "🟢" if sched.get("running") else "🔴"
            status_text = "运行中" if sched.get("running") else "已暂停"
            interval_seconds = sched.get("interval_seconds") or 60
            next_run = sched.get("next_run", "")
            if next_run:
                try:
                    from datetime import datetime as _dt
                    nr = _dt.fromisoformat(next_run)
                    next_str = nr.strftime("%H:%M")
                except Exception:
                    next_str = "--:--"
            else:
                next_str = "--:--"
            st.caption(
                f"{status_icon} 自动轮询: {status_text} · "
                f"间隔 {interval_seconds} 秒 · "
                f"已跑 {sched.get('total_runs', 0)} 次 · "
                f"下次 {next_str}"
            )
        except Exception:
            pass

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 立即抓取", help="手动触发一次邮件抓取"):
            trigger_bot_via_api()
    with col2:
        if _api_ok:
            try:
                sched = get_cached_schedule_status()
                if sched.get("running"):
                    if st.button("⏸ 暂停轮询", help="暂停自动检查新邮件"):
                        api.schedule_toggle()
                        rerun_after_mutation()
                else:
                    if st.button("▶ 恢复轮询", help="恢复自动检查新邮件"):
                        api.schedule_toggle()
                        rerun_after_mutation()
            except Exception:
                pass

    if not _api_ok:
        st.markdown("---")
        st.warning("⚠️ API 未连接（已自动尝试启动，可能仍在初始化中）")
        if st.button("🔄 重试连接"):
            get_cached_api_health.clear()
            st.session_state["_api_autostart_attempted"] = False
            st.rerun()

    st.markdown("---")
    st.caption(f"最近更新：{datetime.now().strftime('%H:%M:%S')}")

# 邮箱草稿与数据库邮件匹配
def normalize_email_subject(value):
    value = re.sub(r'\s+', ' ', value or '').strip().lower()
    while True:
        new_value = re.sub(r'^(re|fw|fwd)\s*:\s*', '', value).strip()
        if new_value == value:
            return value
        value = new_value


def extract_email_addresses(text):
    return [
        item.lower()
        for item in re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text or "")
    ]


def extract_draft_match_clues(draft):
    body = draft.get("body") or ""
    refs = " ".join([
        draft.get("in_reply_to") or "",
        draft.get("references") or "",
    ]).strip()
    quote_header = ""
    quote_sender = ""
    quote_date = ""

    header_match = re.search(
        r'(?im)^\s*On\s+(.{5,180}?),\s*(.+?)\s+wrote\s*:',
        body,
    )
    if header_match:
        quote_date = re.sub(r'\s+', ' ', header_match.group(1)).strip()
        quote_header = re.sub(r'\s+', ' ', header_match.group(0)).strip()
        sender_part = header_match.group(2)
        emails = extract_email_addresses(sender_part)
        quote_sender = emails[0] if emails else sender_part.strip().lower()

    body_emails = [
        email for email in extract_email_addresses(body[:2500])
        if not email.endswith("@mooeraudio.com")
    ]
    if quote_sender and "@" in quote_sender and quote_sender not in body_emails:
        body_emails.insert(0, quote_sender)

    return {
        "subject": draft.get("subject") or "",
        "normalized_subject": normalize_email_subject(draft.get("subject") or ""),
        "refs": refs,
        "has_refs": bool(refs),
        "quote_header": quote_header,
        "quote_sender": quote_sender,
        "quote_date": quote_date,
        "body_emails": body_emails,
    }


def score_draft_email_match(draft, email, clues=None):
    clues = clues or extract_draft_match_clues(draft)
    score = 0
    reasons = []

    refs = clues.get("refs") or ""
    message_id = email.get("message_id") or ""
    if refs and message_id and message_id in refs:
        return 1000, ["Message-ID 精准命中"]

    draft_subject = clues.get("normalized_subject") or ""
    db_subject = normalize_email_subject(email.get("subject") or "")
    if draft_subject and db_subject:
        if draft_subject == db_subject:
            score += 160
            reasons.append("主题完全一致")
        elif draft_subject in db_subject or db_subject in draft_subject:
            score += 75
            reasons.append("主题高度相似")
        else:
            draft_tokens = {t for t in re.split(r'\W+', draft_subject) if len(t) >= 3}
            db_tokens = {t for t in re.split(r'\W+', db_subject) if len(t) >= 3}
            if draft_tokens and db_tokens:
                overlap = len(draft_tokens & db_tokens)
                ratio = overlap / max(len(draft_tokens), len(db_tokens))
                if ratio >= 0.45:
                    score += int(55 * ratio)
                    reasons.append("主题关键词重叠")

    sender_email = (
        email.get("sender_email")
        or _extract_sender_email(email.get("sender") or "")
    ).lower()
    clue_emails = set(clues.get("body_emails") or [])
    quote_sender = (clues.get("quote_sender") or "").lower()
    if sender_email:
        if sender_email in clue_emails:
            score += 130
            reasons.append("草稿引用中出现客户邮箱")
        elif quote_sender and sender_email == quote_sender:
            score += 130
            reasons.append("引用发件人与数据库发件人一致")

    received_at = str(email.get("received_at") or "")
    quote_date = clues.get("quote_date") or ""
    if quote_date and received_at:
        year_match = re.search(r'20\d{2}', quote_date)
        if year_match and year_match.group(0) in received_at:
            score += 15
            reasons.append("引用日期年份一致")

    return score, reasons


def find_draft_match_candidates(draft, db_emails, limit=5):
    clues = extract_draft_match_clues(draft)
    candidates = []
    for email in db_emails:
        score, reasons = score_draft_email_match(draft, email, clues)
        if score > 0:
            candidates.append({
                "email": email,
                "score": score,
                "reasons": reasons,
            })

    candidates.sort(
        key=lambda item: (
            item["score"],
            str(item["email"].get("received_at") or ""),
        ),
        reverse=True,
    )
    return candidates[:limit], clues


def match_draft_with_database(draft, db_emails):
    """按 Message-ID、引用客户邮箱、主题相似度匹配邮箱草稿对应的原始邮件。"""
    candidates, clues = find_draft_match_candidates(draft, db_emails, limit=1)
    if not candidates:
        return None

    best = candidates[0]
    reasons = best.get("reasons") or []
    has_strong_subject = any(reason in reasons for reason in ("主题完全一致", "主题高度相似"))
    has_sender = any("客户邮箱" in reason or "发件人一致" in reason for reason in reasons)

    # 精准引用命中直接返回；历史邮件没有 message_id 时，避免只凭同一客户邮箱错配到别的问题。
    if (
        best["score"] >= 1000
        or (has_strong_subject and best["score"] >= 150)
        or (has_sender and best["score"] >= 180)
    ):
        matched = dict(best["email"])
        matched["_match_score"] = best["score"]
        matched["_match_reasons"] = "；".join(best["reasons"])
        matched["_match_clues"] = clues
        return matched
    return None

def _extract_sender_email(sender):
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender or "")
    return match.group(0).lower() if match else ""

def _draft_issue_slug(value, fallback="unknown"):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value or fallback

def _draft_issue_text(draft, matched_email=None, limit=2500):
    parts = [
        draft.get("subject") or "",
        draft.get("body") or "",
    ]
    if matched_email:
        parts.extend([
            matched_email.get("subject") or "",
            matched_email.get("body") or "",
            matched_email.get("product_model") or "",
            matched_email.get("issue_category") or "",
            matched_email.get("issue_fingerprint") or "",
            matched_email.get("ai_intent") or "",
        ])
    return "\n".join(parts)[:limit].lower()

def _detect_draft_product(text, matched_email=None):
    db_product = (matched_email or {}).get("product_model") or ""
    if db_product and db_product.lower() not in {"unknown", "none"}:
        return db_product

    aliases = [
        ("GE1000", ("ge 1000", "ge1000li", "ge1000")),
        ("GE100 Pro Li", ("ge 100 pro li", "ge100 pro li", "ge100proli")),
        ("GE100 Pro", ("ge100 pro", "ge 100 pro")),
        ("GE150 Pro Li", ("ge150proli", "ge150 pro li")),
        ("GE150 Pro", ("ge150 pro", "ge-150 pro", "ge150pro")),
        ("GE150 Plus Li", ("ge150 plus li",)),
        ("GE150 Plus", ("ge150 plus",)),
        ("GE150 MAX", ("ge150 max", "ge 150 max")),
        ("GE150", ("ge150", "ge 150")),
        ("GE200", ("ge 200", "ge200")),
        ("GE300 Lite", ("ge300lite", "ge300 lite", "300lite", "300 lite")),
        ("GE300", ("ge300", "ge 300")),
        ("GS1000Li", ("gs1000li", "gs1000 li")),
        ("GS1000", ("gs1000", "gs 1000")),
        ("GL200", ("gl200",)),
        ("GL100", ("gl100",)),
        ("F15i Li", ("f15i li", "f15 li")),
        ("F15i", ("f15i",)),
        ("F40i", ("f40i",)),
        ("SD30i", ("sd30i",)),
        ("SD30", ("sd-30", "sd30")),
        ("SD75", ("sd-75", "sd75")),
        ("iAMP", ("iamp",)),
        ("GTRS W900", ("w900",)),
        ("GTRS P800", ("p800",)),
        ("Prime P1", ("prime p1",)),
        ("Prime P2", ("prime p2",)),
        ("Firefly M6", ("firefly m6",)),
        ("Tender Octaver", ("tender octaver",)),
        ("Red Truck", ("red truck",)),
        ("MOOER F4", ("mooer f4", " f4 ")),
    ]
    for product, markers in aliases:
        if any(marker in text for marker in markers):
            return product
    return "Unknown"

def _detect_draft_issue_type(text, product, matched_email=None):
    db_category = (matched_email or {}).get("issue_category") or ""
    subject_line = text.split("\n", 1)[0]

    if subject_line.startswith("[r&d forward]") or "forwarded to our r&d" in text or "technical team" in text:
        return {
            "label": "R&D pending / forwarded internally",
            "issue_category": db_category or "rnd_forward_pending",
            "priority": "High",
            "action": "Wait for R&D feedback, then reply together",
            "confidence": 0.88,
            "reason": "Subject/body indicates R&D forward or technical-team escalation",
        }
    if product in {"iAMP", "F15i", "F15i Li", "F40i", "SD30i"} and any(marker in text for marker in ("version too low", "too low", "app", "mobile app", "connect")):
        return {
            "label": "iAMP/app connection or version-too-low",
            "issue_category": "app_version_too_low_connection_failure",
            "priority": "P0",
            "action": "Good candidate for unified reply",
            "confidence": 0.9,
            "reason": "iAMP-family product plus app/connect/version-too-low keywords",
        }
    if "nam" in text or "neural amp modeler" in text:
        return {
            "label": "NAM/A2 import or compatibility",
            "issue_category": "nam_a2_import_compatibility",
            "priority": "High",
            "action": "Unify only after checking product differences",
            "confidence": 0.84,
            "reason": "NAM or Neural Amp Modeler keyword detected",
        }
    if any(marker in text for marker in ("firmware", "update", "equipment version", "version is too low", "re-flash", "rollback", "roll back")):
        failed = any(marker in text for marker in ("fail", "falling", "not update", "travou", "cannot start", "flash", "stuck", "too low", "won't start", "does not start"))
        return {
            "label": "Firmware update failed / device version too low" if failed else "Firmware/version question or rollback",
            "issue_category": db_category or ("firmware_update_failed" if failed else "firmware_version_question"),
            "priority": "High" if failed else "Medium",
            "action": "Check same model before unified reply" if failed else "Can reply with version guidance",
            "confidence": 0.78 if failed else 0.68,
            "reason": "Firmware/update/version keywords detected",
        }
    if any(marker in text for marker in ("studio", "editor", "software", "download", "driver", "macos", "unverified developer", "developer verification", "open anyway", "windows 11")):
        return {
            "label": "Software/editor/driver install or connection",
            "issue_category": db_category or "software_install_driver",
            "priority": "Medium",
            "action": "Use software troubleshooting template",
            "confidence": 0.72,
            "reason": "Studio/editor/software/driver/macOS keywords detected",
        }
    if any(marker in text for marker in ("warranty", "repair", "replacement", "part", "screen", "latch", "rubber feet", "charging", "returned", "return", "amazon", "purchase date", "order id")):
        return {
            "label": "Warranty/repair/parts/return",
            "issue_category": db_category or "warranty_repair_process",
            "priority": "Medium",
            "action": "Handle separately unless same part and same policy",
            "confidence": 0.7,
            "reason": "Warranty/repair/part/return keywords detected",
        }
    if any(marker in text for marker in ("footswitch", "exp pedal", "bank down", "midi", "looper", "preset")):
        return {
            "label": "Usage/MIDI/footswitch/preset",
            "issue_category": db_category or "usage_midi_looper_preset",
            "priority": "Medium",
            "action": "Review before grouping as one issue",
            "confidence": 0.65,
            "reason": "Footswitch/MIDI/looper/preset keywords detected",
        }
    if any(marker in text for marker in ("sound", "volume", "noise", "output", "headphone", "cut-out", "distortion", "cab block")):
        return {
            "label": "Audio output/volume/noise",
            "issue_category": db_category or "audio_output_issue",
            "priority": "Medium",
            "action": "Review symptoms individually",
            "confidence": 0.62,
            "reason": "Sound/volume/noise/output keywords detected",
        }
    if any(marker in text for marker in ("registration", "register", "cloud ai")):
        return {
            "label": "Account registration/cloud feature",
            "issue_category": db_category or "account_registration_cloud",
            "priority": "Low",
            "action": "Can usually handle individually",
            "confidence": 0.62,
            "reason": "Registration/register/cloud keywords detected",
        }
    return {
        "label": "Needs manual confirmation",
        "issue_category": db_category or "general_support_followup",
        "priority": "Low",
        "action": "Handle individually",
        "confidence": 0.35,
        "reason": "No high-confidence shared-issue keywords detected",
    }

def _issue_match_score(issue, product, issue_category, text):
    issue_product = (issue.get("product_model") or "").lower()
    issue_category_text = (issue.get("issue_category") or "").lower()
    issue_title = (issue.get("issue_title") or "").lower()
    product_text = (product or "").lower()
    category_text = (issue_category or "").lower()
    score = 0

    if product_text and product_text != "unknown":
        if product_text == issue_product:
            score += 4
        elif product_text in issue_product or issue_product in product_text:
            score += 3

    if category_text:
        if category_text == issue_category_text:
            score += 5
        elif category_text in issue_category_text or issue_category_text in category_text:
            score += 3

    for marker in ("iamp", "version too low", "ge1000", "firmware", "nam", "macos", "driver", "warranty", "repair"):
        if marker in text and marker in f"{issue_title} {issue_category_text}":
            score += 1

    return score

def _find_recommended_issue(product, issue_category, text, issues):
    best_issue = None
    best_score = 0
    for issue in issues or []:
        if issue.get("status") in {"closed", "bulk_replied", "merged"}:
            continue
        score = _issue_match_score(issue, product, issue_category, text)
        if score > best_score:
            best_issue = issue
            best_score = score
    if best_issue and best_score >= 5:
        return best_issue, best_score
    return None, best_score

def classify_draft_issue(draft, matched_email=None, issues=None):
    text = _draft_issue_text(draft, matched_email)
    product = _detect_draft_product(text, matched_email)
    issue_type = _detect_draft_issue_type(text, product, matched_email)
    issue_category = issue_type["issue_category"]
    recommended_issue, match_score = _find_recommended_issue(product, issue_category, text, issues or [])
    group_product = product
    if issue_category == "app_version_too_low_connection_failure" and product in {"iAMP", "F15i", "F15i Li", "F40i", "SD30i"}:
        group_product = "iAMP/F15i/F40i/SD30i"
    group_key = f"{_draft_issue_slug(group_product)}::{_draft_issue_slug(issue_category)}"
    issue_label = ""
    if recommended_issue:
        issue_label = "#{id} {title}".format(
            id=recommended_issue.get("id"),
            title=(recommended_issue.get("issue_title") or "")[:80],
        )
    return {
        "group_key": group_key,
        "group_label": f"{group_product} · {issue_type['label']}",
        "tag": f"{product}/{issue_type['priority']}",
        "product": product,
        "issue_label": issue_type["label"],
        "issue_category": issue_category,
        "priority": issue_type["priority"],
        "action": issue_type["action"],
        "confidence": issue_type["confidence"],
        "reason": issue_type["reason"],
        "recommended_issue": recommended_issue,
        "recommended_issue_label": issue_label,
        "recommended_issue_score": match_score,
    }

def build_draft_issue_groups(draft_entries):
    groups = {}
    for entry in draft_entries:
        classification = entry["classification"]
        key = classification["group_key"]
        if key not in groups:
            groups[key] = {
                "group_key": key,
                "group_label": classification["group_label"],
                "product": classification["product"],
                "issue_label": classification["issue_label"],
                "issue_category": classification["issue_category"],
                "priority": classification["priority"],
                "action": classification["action"],
                "recommended_issue_label": classification["recommended_issue_label"],
                "draft_ids": [],
                "subjects": [],
                "count": 0,
                "avg_confidence": 0.0,
            }
        group = groups[key]
        group["count"] += 1
        group["draft_ids"].append(str(entry["draft"].get("id") or ""))
        subject = entry["draft"].get("subject") or "No subject"
        if len(group["subjects"]) < 4:
            group["subjects"].append(subject)
        group["avg_confidence"] += classification["confidence"]

    for group in groups.values():
        if group["count"]:
            group["avg_confidence"] = round(group["avg_confidence"] / group["count"], 2)

    priority_order = {"P0": 0, "High": 1, "Medium": 2, "Low": 3}
    return sorted(
        groups.values(),
        key=lambda item: (priority_order.get(item["priority"], 9), -item["count"], item["group_label"]),
    )

def parse_attachment_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def render_attachment_list(raw, key_prefix):
    attachments = parse_attachment_list(raw)
    if not attachments:
        return

    st.markdown("**📎 附件**")
    for idx, att in enumerate(attachments, 1):
        filename = att.get("filename") or att.get("name") or f"附件 {idx}"
        size = att.get("size") or ""
        content_type = att.get("content_type") or att.get("type") or ""
        details = " · ".join(part for part in [size, content_type] if part)
        st.caption(f"{idx}. {filename}" + (f"（{details}）" if details else ""))


def render_email_thread_context(thread_context, key_prefix, current_email_id=None):
    if not thread_context:
        return

    st.markdown("#### 邮件往来摘要")

    conversation_summary = thread_context.get("conversation_summary") or thread_context.get("summary") or "暂无上下文摘要。"
    customer_need = thread_context.get("customer_need") or "暂未识别明确需求。"
    current_stage = thread_context.get("current_stage") or "暂未识别当前处理阶段。"
    latest_message_summary = thread_context.get("latest_message_summary") or ""

    st.info(conversation_summary)

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**用户需求**")
        st.write(customer_need)
    with cols[1]:
        st.markdown("**当前进展**")
        st.write(current_stage)

    if latest_message_summary:
        st.markdown("**最新邮件重点**")
        st.write(latest_message_summary)

    linked_issue = thread_context.get("linked_issue") or {}
    if linked_issue:
        issue_title = linked_issue.get("issue_title") or linked_issue.get("title") or ""
        st.caption(f"关联 Issue: #{linked_issue.get('id')} {issue_title}")

    timeline_summary = thread_context.get("timeline_summary") or []
    if timeline_summary:
        with st.expander(f"处理时间线摘要（{len(timeline_summary)} 条）", expanded=False):
            for idx, item in enumerate(timeline_summary, 1):
                received_at = str(item.get("received_at") or "")[:19]
                step_label = item.get("step_label") or item.get("status") or "状态未知"
                product = item.get("product_model") or "Unknown"
                intent = item.get("ai_intent") or "N/A"
                summary = item.get("summary") or ""
                st.markdown(f"**{idx}. {received_at}** · {step_label}")
                st.caption(f"产品: {product} | AI意图: {intent}")
                if summary:
                    st.write(summary)

    items = thread_context.get("items") or []
    if not items:
        return

    st.markdown(f"#### 邮件往来（{len(items)} 封）")
    for idx, item in enumerate(items, 1):
        item_id = str(item.get("id") or "")
        is_current = current_email_id is not None and item_id == str(current_email_id)
        received_at = str(item.get("received_at") or "")[:19]
        status = item.get("status") or ""
        subject = item.get("subject") or "无主题"
        sender = item.get("sender_email") or item.get("sender") or ""
        intent = item.get("ai_intent") or "N/A"
        product = item.get("product_model") or "Unknown"
        label = f"{idx}. {received_at or '时间未知'} · {sender or '未知发件人'}"
        if is_current:
            label += " · 当前邮件"

        with st.expander(label, expanded=is_current or len(items) == 1):
            st.markdown(f"**主题：** {subject}")
            st.caption(f"状态: {status or 'N/A'} | 产品: {product} | AI意图: {intent}")

            body = item.get("body_full") or item.get("body_snippet") or ""
            if body:
                height = 260 if is_current else 180
                st.text_area(
                    "邮件正文",
                    body,
                    height=height,
                    disabled=True,
                    key=f"thread_body_{key_prefix}_{item_id}",
                )
            else:
                st.info("这封邮件暂无正文内容。")

            render_attachment_list(item.get("attachments"), f"thread_att_{key_prefix}_{item_id}")

            draft_body = (item.get("draft_body") or "").strip()
            if draft_body:
                st.text_area(
                    "历史回复 / 草稿记录",
                    draft_body,
                    height=160,
                    disabled=True,
                    key=f"thread_draft_{key_prefix}_{item_id}",
                )

def parse_knowledge_citations(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def render_knowledge_citations(raw, key_prefix):
    citations = parse_knowledge_citations(raw)
    if not citations:
        st.info("本草稿暂无知识库引用记录。")
        return

    st.markdown("#### AI 使用来源")
    for idx, citation in enumerate(citations, 1):
        title = citation.get("title") or "未命名知识"
        knowledge_type = citation.get("knowledge_type") or ""
        source = citation.get("source") or ""
        section = citation.get("section") or ""
        chunk_id = citation.get("chunk_id")
        excerpt = citation.get("excerpt") or ""
        with st.expander(f"{idx}. {title}", expanded=False):
            st.caption(f"知识层: {knowledge_type} | 片段: {chunk_id or '-'}")
            if section:
                st.write(f"**章节/片段**: {section}")
            if source:
                st.write(f"**来源**: {source}")
            if excerpt:
                st.text_area(
                    "引用片段",
                    excerpt,
                    height=110,
                    disabled=True,
                    key=f"citation_{key_prefix}_{idx}",
                )


def _xml_cell(value):
    value = "" if value is None else str(value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return f"<Cell><Data ss:Type=\"String\">{html.escape(value)}</Data></Cell>"

def _xml_row(values):
    return "<Row>" + "".join(_xml_cell(value) for value in values) + "</Row>"

def _xml_sheet(name, headers, rows):
    safe_name = html.escape(str(name)[:31] or "Sheet")
    xml_rows = [_xml_row(headers)]
    xml_rows.extend(_xml_row(row) for row in rows)
    return f"""
    <Worksheet ss:Name="{safe_name}">
      <Table>
        {''.join(xml_rows)}
      </Table>
    </Worksheet>
    """

def build_issue_report_xls(issue, linked_emails):
    """Build an Excel-readable XML workbook without third-party dependencies."""
    users = sorted({
        _extract_sender_email(item.get("sender"))
        for item in linked_emails
        if _extract_sender_email(item.get("sender"))
    })
    summary_rows = [
        ["问题 ID", issue.get("id")],
        ["产品", issue.get("product_model")],
        ["问题标题", issue.get("issue_title")],
        ["Category", issue.get("issue_category")],
        ["Status", issue.get("status")],
        ["Priority", issue.get("priority")],
        ["研发状态", issue.get("rnd_status")],
        ["用户数", issue.get("user_count")],
        ["邮件数", issue.get("email_count")],
        ["首次出现", issue.get("first_seen_at")],
        ["最近出现", issue.get("last_seen_at")],
        ["研发备注", issue.get("rnd_notes")],
        ["解决方案摘要", issue.get("solution_summary")],
        ["最终回复模板", issue.get("final_reply_template")],
    ]
    email_rows = [
        [
            item.get("id"),
            _extract_sender_email(item.get("sender")),
            item.get("sender"),
            item.get("subject"),
            item.get("received_at"),
            item.get("status"),
            item.get("product_model"),
            item.get("ai_intent"),
            item.get("ai_sentiment"),
            item.get("matched_by"),
            (item.get("body") or "")[:3000],
        ]
        for item in linked_emails
    ]
    user_rows = [[email_address] for email_address in users]
    workbook = f"""<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  {_xml_sheet("问题摘要", ["字段", "值"], summary_rows)}
  {_xml_sheet("关联邮件", ["邮件 ID", "用户邮箱", "发件人", "主题", "收件时间", "状态", "产品", "意图", "情绪", "匹配方式", "正文预览"], email_rows)}
  {_xml_sheet("用户邮箱", ["用户邮箱"], user_rows)}
</Workbook>
"""
    return workbook.encode("utf-8")

def build_all_issues_xls(issues):
    rows = [
        [
            item.get("id"),
            item.get("product_model"),
            item.get("issue_title"),
            item.get("issue_category"),
            item.get("status"),
            item.get("priority"),
            item.get("user_count"),
            item.get("email_count"),
            item.get("rnd_status"),
            item.get("first_seen_at"),
            item.get("last_seen_at"),
            item.get("rnd_notes"),
            item.get("solution_summary"),
        ]
        for item in issues
    ]
    workbook = f"""<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  {_xml_sheet("全部问题", ["问题 ID", "产品", "问题标题", "分类", "状态", "优先级", "用户数", "邮件数", "研发状态", "首次出现", "最近出现", "研发备注", "解决方案摘要"], rows)}
</Workbook>
"""
    return workbook.encode("utf-8")

def build_issue_report_html(issue, linked_emails):
    """Generate a clean, readable HTML summary report for sharing with colleagues."""
    import json as _json

    users = {}
    for item in linked_emails:
        addr = _extract_sender_email(item.get("sender"))
        if addr:
            if addr not in users:
                users[addr] = {"name": item.get("sender", "").split("<")[0].strip().strip('"'), "emails": []}
            users[addr]["emails"].append(item)

    user_cards = ""
    for addr, u in users.items():
        first_date = u["emails"][-1].get("received_at", "")[:16] if u["emails"] else ""
        user_cards += f"""
        <div class="user-card">
          <div class="user-name">{html.escape(u['name'][:40])}</div>
          <div class="user-email">{html.escape(addr)}</div>
          <div class="user-stat">相关邮件: <span>{len(u['emails'])}</span> 封 &nbsp;|&nbsp; 首次报告: <span>{html.escape(str(first_date))}</span></div>
        </div>"""

    email_rows = ""
    for em in linked_emails:
        dt = str(em.get("received_at", ""))[:10]
        sender_name = _extract_sender_email(em.get("sender", ""))
        subject = html.escape(str(em.get("subject", "")[:60]))
        status = em.get("status", "")
        body_preview = html.escape(str(em.get("body", "")[:200]))
        tag_class = "tag-forwarded" if "forwarded" in status else "tag-drafted"
        status_label = status.replace("_", " ")
        email_rows += f"""
        <tr>
          <td>{html.escape(dt)}</td>
          <td>{html.escape(sender_name[:25])}</td>
          <td title="{subject}">{subject}</td>
          <td><span class="tag {tag_class}">{status_label}</span></td>
          <td class="body-preview">{body_preview}</td>
        </tr>"""

    first_seen = str(issue.get("first_seen_at", ""))[:10]
    last_seen = str(issue.get("last_seen_at", ""))[:10]
    days = "N/A"
    try:
        from datetime import datetime as _dt
        f = _dt.fromisoformat(first_seen) if first_seen else None
        l = _dt.fromisoformat(last_seen) if last_seen else None
        if f and l:
            days = str((l - f).days)
    except:
        pass

    report = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(issue.get('product_model', ''))} - {html.escape(issue.get('issue_title', '')[:50])} - 客户反馈汇总</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; background:#f0f2f5; color:#333; line-height:1.6; }}
.container {{ max-width:960px; margin:0 auto; padding:24px; }}
.header {{ background:linear-gradient(135deg, #1a1a2e, #16213e); color:#fff; padding:32px; border-radius:12px; margin-bottom:24px; }}
.header h1 {{ font-size:24px; margin-bottom:6px; }}
.header .subtitle {{ font-size:14px; opacity:0.75; }}
.header .meta {{ margin-top:12px; font-size:12px; opacity:0.6; }}
.stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:24px; }}
.stat {{ background:#fff; border-radius:10px; padding:24px 20px; text-align:center; box-shadow:0 1px 4px rgba(0,0,0,0.06); }}
.stat .num {{ font-size:40px; font-weight:800; }}
.stat .label {{ font-size:13px; color:#888; margin-top:4px; }}
.stat.red .num {{ color:#c62828; }}
.stat.amber .num {{ color:#e65100; }}
.stat.blue .num {{ color:#1565c0; }}
.stat.green .num {{ color:#2e7d32; }}
.section {{ background:#fff; border-radius:10px; padding:24px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }}
.section h2 {{ font-size:17px; color:#1a1a2e; margin-bottom:16px; padding-bottom:8px; border-bottom:2px solid #e8e8e8; }}
.info-table {{ width:100%; border-collapse:collapse; font-size:14px; }}
.info-table td {{ padding:8px 12px; border-bottom:1px solid #f0f0f0; }}
.info-table td:first-child {{ font-weight:600; color:#555; width:140px; }}
.user-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.user-card {{ border:1px solid #e8e8e8; border-radius:8px; padding:16px; }}
.user-card .user-name {{ font-size:15px; font-weight:700; margin-bottom:4px; }}
.user-card .user-email {{ font-size:13px; color:#1565c0; margin-bottom:10px; }}
.user-card .user-stat {{ font-size:13px; color:#666; }}
.user-card .user-stat span {{ font-weight:600; color:#333; }}
.email-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
.email-table th {{ background:#f6f6f6; padding:10px 10px; text-align:left; font-weight:600; color:#555; border-bottom:2px solid #e0e0e0; }}
.email-table td {{ padding:10px; border-bottom:1px solid #f0f0f0; vertical-align:top; }}
.email-table tr:hover td {{ background:#fafbff; }}
.tag {{ display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.tag-drafted {{ background:#e3f2fd; color:#1565c0; }}
.tag-forwarded {{ background:#fff3e0; color:#e65100; }}
.tag-high {{ background:#ffebee; color:#c62828; }}
.body-preview {{ max-width:400px; white-space:pre-wrap; font-size:12px; color:#666; line-height:1.5; max-height:80px; overflow:hidden; }}
.footer {{ text-align:center; color:#aaa; font-size:12px; padding:16px; }}
@media (max-width:640px) {{ .stats {{ grid-template-columns:1fr 1fr; }} .user-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>{html.escape(issue.get('product_model', ''))} · {html.escape(issue.get('issue_title', '')[:60])}</h1>
  <div class="subtitle">{html.escape(issue.get('issue_category', ''))}</div>
  <div class="meta">报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据来源: support@mooeraudio.com 邮件数据库</div>
</div>

<div class="stats">
  <div class="stat red"><div class="num">{issue.get('user_count', 0)}</div><div class="label">受影响用户</div></div>
  <div class="stat amber"><div class="num">{issue.get('email_count', 0)}</div><div class="label">相关邮件</div></div>
  <div class="stat blue"><div class="num">{issue.get('priority', '')}</div><div class="label">优先级</div></div>
  <div class="stat green"><div class="num">{days}天</div><div class="label">持续时长</div></div>
</div>

<div class="section">
  <h2>问题概览</h2>
  <table class="info-table">
    <tr><td>产品型号</td><td>{html.escape(issue.get('product_model', ''))}</td></tr>
    <tr><td>问题分类</td><td>{html.escape(issue.get('issue_category', ''))}</td></tr>
    <tr><td>当前状态</td><td><span class="tag tag-high">{html.escape(issue.get('status', ''))}</span></td></tr>
    <tr><td>研发状态</td><td>{html.escape(issue.get('rnd_status', ''))}</td></tr>
    <tr><td>发现时间</td><td>{html.escape(first_seen)} ~ {html.escape(last_seen)}</td></tr>
    <tr><td>研发备注</td><td>{html.escape(str(issue.get('rnd_notes', '') or '暂无'))}</td></tr>
  </table>
</div>

<div class="section">
  <h2>受影响用户 ({len(users)}人)</h2>
  <div class="user-grid">{user_cards}</div>
</div>

<div class="section">
  <h2>邮件详情 ({len(linked_emails)}封)</h2>
  <table class="email-table">
    <thead><tr><th style="width:80px">日期</th><th style="width:140px">用户</th><th>主题</th><th style="width:90px">状态</th><th style="width:300px">内容摘要</th></tr></thead>
    <tbody>{email_rows}</tbody>
  </table>
</div>

<div class="footer">MOOER Audio Support · 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</div>
</body>
</html>"""
    return report.encode("utf-8")


def build_issue_report_html(issue, linked_emails):
    """Build the R&D-style HTML report used by dashboard exports."""
    issue_id = issue.get("id")
    linked_ids = {str(item.get("id")) for item in linked_emails}

    def body_text(value):
        text = html.unescape(str(value or ""))
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|li|tr)>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    def collapsed_text(value, limit=280):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text[:limit] + ("..." if len(text) > limit else "")

    def evidence_terms(row):
        terms = []
        for value in (
            issue.get("product_model"),
            issue.get("issue_title"),
            issue.get("issue_category"),
            row.get("matched_keywords"),
        ):
            if not value:
                continue
            terms.extend(re.findall(r"[A-Za-z0-9][A-Za-z0-9_+-]{2,}", str(value)))
        terms.extend([
            "failed", "fails", "failure", "error", "stuck", "freeze", "frozen",
            "rainbow", "connect", "pairing", "noise", "output", "firmware",
            "update", "upgrade", "boot", "recognized", "detected",
        ])
        deduped = []
        seen = set()
        for term in terms:
            key = term.lower()
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            deduped.append(term)
        return deduped

    def evidence_excerpt(row, limit=1800):
        text = body_text(row.get("body"))
        if not text:
            text = body_text(row.get("evidence_snippet"))
        if not text:
            return ""
        lower = text.lower()
        hit_positions = [
            lower.find(term.lower())
            for term in evidence_terms(row)
            if term and lower.find(term.lower()) >= 0
        ]
        idx = min(hit_positions) if hit_positions else 0
        start = max(0, idx - 260)
        end = min(len(text), idx + limit)
        excerpt = text[start:end].strip()
        if start > 0:
            excerpt = "[...]\n" + excerpt
        if end < len(text):
            excerpt += "\n[...]"
        return excerpt

    def evidence_summary(row):
        excerpt = evidence_excerpt(row, limit=900)
        return collapsed_text(excerpt, limit=260)

    def evidence_cell(row):
        summary = html.escape(evidence_summary(row) or "暂无可提取证据")
        excerpt = html.escape(evidence_excerpt(row, limit=2200))
        if not excerpt:
            return f"<div class=\"evidence-summary\">{summary}</div>"
        return (
            f"<div class=\"evidence-summary\">{summary}</div>"
            "<details class=\"evidence-details\">"
            "<summary>查看原始证据片段</summary>"
            f"<pre>{excerpt}</pre>"
            "</details>"
        )

    users = {}
    for item in linked_emails:
        email_addr = _extract_sender_email(item.get("sender"))
        if not email_addr:
            continue
        users.setdefault(email_addr, []).append(item)

    reference_rows = []
    if issue_id:
        try:
            candidate_resp = get_cached_issue_candidates(issue_id, limit=500)
            for cand in candidate_resp.get("items", []):
                status = cand.get("candidate_status") or "pending"
                if str(cand.get("id")) in linked_ids or status == "excluded":
                    continue
                reference_rows.append(cand)
        except Exception:
            reference_rows = []

    user_rows = []
    for email_addr, rows in sorted(users.items()):
        first_seen = min(str(row.get("received_at") or "") for row in rows)
        last_seen = max(str(row.get("received_at") or "") for row in rows)
        subjects = "<br>".join(html.escape(str(row.get("subject") or "")[:90]) for row in rows[:4])
        user_rows.append(
            "<tr>"
            f"<td>{html.escape(email_addr)}</td>"
            f"<td>{len(rows)}</td>"
            f"<td>{html.escape(first_seen)}</td>"
            f"<td>{html.escape(last_seen)}</td>"
            f"<td>{subjects}</td>"
            "</tr>"
        )

    email_rows = []
    for row in linked_emails:
        email_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('id') or ''))}</td>"
            f"<td>{html.escape(_extract_sender_email(row.get('sender')))}</td>"
            f"<td>{html.escape(str(row.get('received_at') or ''))}</td>"
            f"<td>{html.escape(str(row.get('product_model') or ''))}</td>"
            f"<td>{html.escape(str(row.get('subject') or ''))}</td>"
            f"<td>{evidence_cell(row)}</td>"
            "</tr>"
        )

    reference_html_rows = []
    for row in reference_rows:
        reference_html_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('id') or ''))}</td>"
            f"<td>{html.escape(_extract_sender_email(row.get('sender')))}</td>"
            f"<td>{html.escape(str(row.get('candidate_status') or ''))}</td>"
            f"<td>{html.escape(str(row.get('subject') or ''))}</td>"
            f"<td>{evidence_cell(row)}</td>"
            "</tr>"
        )

    issue_title = html.escape(str(issue.get("issue_title") or ""))
    product_model = html.escape(str(issue.get("product_model") or ""))
    issue_category = html.escape(str(issue.get("issue_category") or ""))

    def issue_summary_text():
        raw_product = str(issue.get("product_model") or "该产品")
        raw_title = str(issue.get("issue_title") or "")
        raw_category = str(issue.get("issue_category") or "")
        text_key = f"{raw_title} {raw_category}".lower()

        if "poly_shift" in text_key or "poly shift" in text_key or "poly pitch" in text_key:
            return f"用户反馈 {raw_product} 的 Poly Shift / Poly Pitch 效果存在延迟或音准问题，需要研发确认效果算法或固件表现。"
        if ("preset" in text_key or "looper" in text_key or "stomp" in text_key) and ("freeze" in text_key or "unresponsive" in text_key):
            return f"用户反馈 {raw_product} 升级后在 preset/stomp 切换或 looper 使用过程中出现无响应、声音未切换或需要重启的问题，影响正常演出使用。"
        if "balance" in text_key and "output" in text_key:
            return f"用户反馈 {raw_product} 在固件更新后出现 balance output 输出异常，需要研发确认固件和输出链路。"
        if "firmware" in text_key and ("freeze" in text_key or "stuck" in text_key):
            return f"用户反馈 {raw_product} 固件升级后出现卡死、冻结或无法正常启动的问题，需要研发确认恢复方案。"
        if "firmware" in text_key and ("failed" in text_key or "update" in text_key):
            return f"用户反馈 {raw_product} 固件更新失败或更新后设备异常，需要研发确认升级流程和恢复方式。"
        if "pairing" in text_key or "connection" in text_key or "bluetooth" in text_key:
            return f"用户反馈 {raw_product} 存在配对或连接异常，需要研发确认连接流程、固件兼容性和复现条件。"
        if "audio" in text_key or "distortion" in text_key or "noise" in text_key:
            return f"用户反馈 {raw_product} 存在音频异常、失真、噪声或间歇性停止工作的问题，需要研发确认音频链路和固件表现。"
        return f"用户反馈 {raw_product} 出现「{raw_title or raw_category or '当前问题'}」相关问题，需要研发复核原因并提供处理方案。"

    issue_summary_html = (
        f"<p>{html.escape(issue_summary_text())}</p>"
        f"<p class=\"summary-scope\">影响范围：{len(users)} 位确认用户，{len(linked_emails)} 封确认邮件。</p>"
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    first_seen = html.escape(str(issue.get("first_seen_at") or ""))
    last_seen = html.escape(str(issue.get("last_seen_at") or ""))
    rnd_notes = html.escape(str(issue.get("rnd_notes") or "暂无"))

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{issue_title} - 研发报告</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif; margin: 0; background: #f5f7fb; color: #1f2937; }}
.container {{ max-width: 1120px; margin: 0 auto; padding: 28px; }}
.header {{ background: #172033; color: white; padding: 28px; border-radius: 10px; }}
.header h1 {{ margin: 0 0 8px; font-size: 24px; }}
.header p {{ margin: 4px 0; color: #d6dbe8; }}
.metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 18px 0; }}
.metric {{ background: white; border-radius: 8px; padding: 18px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
.metric b {{ display: block; font-size: 28px; margin-bottom: 4px; }}
.section {{ background: white; border-radius: 8px; padding: 22px; margin: 18px 0; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
h2 {{ font-size: 18px; margin: 0 0 14px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; padding: 10px; }}
th {{ background: #f8fafc; color: #374151; }}
.tag {{ display: inline-block; background: #eef2ff; color: #3730a3; padding: 3px 8px; border-radius: 999px; font-size: 12px; }}
.warn {{ background: #fff7ed; border-left: 4px solid #f97316; padding: 12px 14px; }}
.issue-summary p {{ line-height: 1.7; margin: 8px 0; }}
.issue-summary .summary-scope {{ color: #6b7280; font-size: 13px; }}
.evidence-summary {{ line-height: 1.55; color: #374151; }}
.evidence-details {{ margin-top: 8px; }}
.evidence-details summary {{ cursor: pointer; color: #2563eb; font-size: 12px; user-select: none; }}
.evidence-details pre {{ white-space: pre-wrap; word-break: break-word; background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px; max-height: 420px; overflow: auto; font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif; font-size: 12px; line-height: 1.55; color: #111827; }}
@media (max-width: 760px) {{ .metrics {{ grid-template-columns: 1fr 1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{issue_title}</h1>
    <p>Issue ID: #{html.escape(str(issue_id or ""))} | 产品范围: {product_model} | 分类: {issue_category}</p>
    <p>生成时间: {generated_at}</p>
  </div>

  <div class="metrics">
    <div class="metric"><b>{len(users)}</b>确认用户</div>
    <div class="metric"><b>{len(linked_emails)}</b>确认邮件</div>
    <div class="metric"><b>{len(reference_rows)}</b>参考线索</div>
    <div class="metric"><b>{html.escape(str(issue.get('priority') or ''))}</b>优先级</div>
  </div>

  <div class="section">
    <h2>问题摘要</h2>
    <div class="issue-summary">{issue_summary_html}</div>
    <p><span class="tag">时间范围</span> {first_seen} 至 {last_seen}</p>
    <div class="warn">研发备注: {rnd_notes}</div>
  </div>

  <div class="section">
    <h2>确认用户邮箱</h2>
    <table>
      <thead><tr><th>用户邮箱</th><th>邮件数</th><th>首次反馈</th><th>最近反馈</th><th>主题</th></tr></thead>
      <tbody>{''.join(user_rows)}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>确认相关邮件</h2>
    <table>
      <thead><tr><th>ID</th><th>用户邮箱</th><th>时间</th><th>系统识别产品</th><th>主题</th><th>证据摘要 / 原始片段</th></tr></thead>
      <tbody>{''.join(email_rows)}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>参考线索，不计入正式用户数</h2>
    <p>这里显示候选池中未确认或仅作为线索保留的邮件。需要人工确认后，才会进入正式统计。</p>
    <table>
      <thead><tr><th>ID</th><th>用户邮箱</th><th>状态</th><th>主题</th><th>证据摘要 / 原始片段</th></tr></thead>
      <tbody>{''.join(reference_html_rows)}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""
    return html_doc.encode("utf-8-sig")


def save_export_file(file_name, content):
    exports_dir = os.path.join(os.getcwd(), "exports")
    os.makedirs(exports_dir, exist_ok=True)
    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', file_name)
    path = os.path.abspath(os.path.join(exports_dir, safe_name))
    with open(path, "wb") as f:
        f.write(content)
    return path

# 主内容
if page == "邮件草稿":
    st.header("📥 邮件草稿")

    refresh_col, cache_col = st.columns([1, 4])
    with refresh_col:
        if st.button("刷新邮箱草稿", key="refresh_mail_drafts", use_container_width=True):
            get_cached_mail_drafts.clear()
            st.session_state["mail_drafts_last_refresh"] = datetime.now().strftime("%H:%M:%S")
            st.rerun()
    with cache_col:
        last_refresh = st.session_state.get("mail_drafts_last_refresh")
        cache_note = "邮箱草稿列表缓存 60 秒，手动刷新会立即重新读取邮箱。"
        if last_refresh:
            cache_note += f" 上次手动刷新：{last_refresh}"
        st.caption(cache_note)

    # 从邮箱读取草稿
    mail_drafts = get_cached_mail_drafts(max_drafts=100)

    # Fetch database emails for matching — include all statuses so older/newer
    # records can still rescue draft-to-original matching.
    try:
        match_statuses = [
            'drafted', 'forwarded_drafted', 'human_review', 'skipped',
            'sent', 'failed_retry', 'new', 'processing', 'no_reply_needed'
        ]
        all_db_emails = []
        seen_email_ids = set()
        for status in match_statuses:
            resp = get_cached_emails(status=status, limit=500)
            for email in resp.get("items", []):
                email_id = str(email.get("id") or "")
                if email_id and email_id not in seen_email_ids:
                    seen_email_ids.add(email_id)
                    all_db_emails.append(email)
    except Exception:
        all_db_emails = []

    if not mail_drafts:
        st.info("邮箱中暂无草稿。运行邮件处理后会自动生成草稿。")
    else:
        st.info(f"📬 邮箱中发现 {len(mail_drafts)} 封草稿，可在发送前编辑。")

        draft_entries = []
        for draft in mail_drafts:
            matched_email = match_draft_with_database(draft, all_db_emails)
            classification = classify_draft_issue(draft, matched_email, issues_all)
            draft_entries.append({
                "draft": draft,
                "matched_email": matched_email,
                "classification": classification,
            })

        draft_groups = build_draft_issue_groups(draft_entries)
        st.markdown("### 疑似同类问题分组（只读建议）")
        st.caption("这里仅根据当前邮箱草稿的主题、正文引用和已匹配数据库信息做分组建议，不会自动修改草稿或问题队列。")
        if draft_groups:
            group_rows = []
            for group in draft_groups:
                group_rows.append({
                    "分组": group["group_label"],
                    "数量": group["count"],
                    "优先级": group["priority"],
                    "平均置信度": group["avg_confidence"],
                    "建议动作": group["action"],
                    "推荐 Issue": group["recommended_issue_label"] or "未匹配",
                    "草稿 ID": ", ".join(group["draft_ids"]),
                    "代表主题": " | ".join(group["subjects"]),
                })
            st.dataframe(pd.DataFrame(group_rows), use_container_width=True, hide_index=True)

            group_options = {"全部草稿": ""}
            for group in draft_groups:
                label = f"{group['priority']} · {group['group_label']} · {group['count']}封"
                group_options[label] = group["group_key"]
            selected_group_label = st.selectbox(
                "按疑似分组筛选草稿",
                list(group_options.keys()),
                key="draft_issue_group_filter",
            )
            selected_group_key = group_options[selected_group_label]
        else:
            selected_group_key = ""

        visible_draft_entries = [
            entry for entry in draft_entries
            if not selected_group_key or entry["classification"]["group_key"] == selected_group_key
        ]
        st.caption(f"当前显示 {len(visible_draft_entries)} / {len(mail_drafts)} 封草稿。")

        # 按原始邮件展示草稿
        for draft_entry in visible_draft_entries:
            draft = draft_entry["draft"]
            matched_email = draft_entry["matched_email"]
            classification = draft_entry["classification"]
            thread_context = None
            if matched_email:
                try:
                    thread_context = get_cached_email_thread(matched_email.get("id"), limit=20)
                except Exception as e:
                    thread_context = None

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

            with st.expander(f"📧 [{classification['tag']}] [ID: {draft.get('id', 'N/A')}] {draft.get('subject', '无主题')}", expanded=False):
                rec_issue = classification.get("recommended_issue_label") or "未匹配现有问题队列"
                st.info(
                    f"**疑似分组**：{classification['group_label']}  \n"
                    f"**置信度**：{classification['confidence']:.0%}  \n"
                    f"**建议动作**：{classification['action']}  \n"
                    f"**推荐 Issue**：{rec_issue}  \n"
                    f"**判断依据**：{classification['reason']}"
                )
                col1, col2 = st.columns([1, 1])

                with col1:
                    st.subheader("邮件往来")
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
                        st.markdown(f"**当前匹配邮件：** #{matched_email.get('id')} · {received_time}")
                        match_reasons = matched_email.get("_match_reasons")
                        match_score = matched_email.get("_match_score")
                        if match_reasons:
                            st.caption(f"匹配依据：{match_reasons}（分数 {match_score}）")
                        st.info(f"**AI 分析**\n\n意图：{matched_email.get('ai_intent', 'N/A')}\n情绪：{matched_email.get('ai_sentiment', 'N/A')}\n产品：{matched_email.get('product_model', 'Unknown')}")
                        if thread_context:
                            render_email_thread_context(thread_context, draft.get('id'), matched_email.get('id'))
                        else:
                            st.warning("暂时无法读取邮件往来，已显示当前邮件全文。")
                            st.text_area(
                                "当前邮件正文",
                                matched_email.get('body', ''),
                                height=320,
                                disabled=True,
                                key=f"original_body_{draft.get('id')}",
                            )
                            render_attachment_list(
                                matched_email.get('attachments'),
                                f"matched_att_{draft.get('id')}_{matched_email.get('id')}",
                            )
                    else:
                        st.warning("⚠️ 数据库中未找到精确原始邮件")
                        candidates, clues = find_draft_match_candidates(draft, all_db_emails, limit=3)
                        reason_lines = []
                        if clues.get("has_refs"):
                            reason_lines.append("草稿有 In-Reply-To/References，但当前数据库历史邮件缺少可命中的 Message-ID。")
                        else:
                            reason_lines.append("草稿里没有可用的 In-Reply-To/References。")
                        if clues.get("body_emails"):
                            reason_lines.append(f"草稿引用邮箱：{', '.join(clues.get('body_emails')[:3])}")
                        if clues.get("quote_header"):
                            reason_lines.append(f"引用头：{clues.get('quote_header')}")
                        reason_lines.append("如果下面没有候选，通常说明原始邮件还没有入库，或草稿来自系统外/旧草稿。")
                        st.info("\n\n".join(reason_lines))

                        usable_candidates = [item for item in candidates if item.get("score", 0) >= 45]
                        if usable_candidates:
                            st.markdown("**可能相关的数据库邮件（需人工判断）**")
                            for idx, cand in enumerate(usable_candidates, 1):
                                email = cand["email"]
                                st.caption(
                                    f"{idx}. #{email.get('id')} · 分数 {cand.get('score')} · "
                                    f"{'；'.join(cand.get('reasons') or [])} · "
                                    f"{email.get('sender_email') or email.get('sender') or '未知发件人'} · "
                                    f"{email.get('subject') or '无主题'}"
                                )
                        if original_info:
                            st.text_area("引用邮件", original_info, height=150, disabled=True, key=f"quoted_email_{draft.get('id')}")

                with col2:
                    st.subheader("邮件回复草稿")
                    # 草稿编辑区
                    edited_draft = st.text_area("回复草稿（发送前可编辑）", draft_body, height=300, key=f"mail_draft_{draft.get('id')}")

                    if matched_email:
                        render_knowledge_citations(
                            matched_email.get("knowledge_citations"),
                            f"mail_{draft.get('id')}_{matched_email.get('id')}",
                        )

                    st.markdown("### 操作")
                    c1, c2, c3, c4, c5 = st.columns(5)
                    with c1:
                        if st.button("✅ 发送", key=f"send_mail_{draft.get('id')}", help="处理这封草稿"):
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
                                with st.spinner('正在发送邮件...'):
                                    # Use the edited draft content
                                    current_draft = st.session_state.get(f"mail_draft_{draft.get('id')}", draft_body)

                                    success = imap_handler.send_email(
                                        recipient=recipient,
                                        subject=draft.get('subject', ''),
                                        body=current_draft,
                                        original_sender=matched_email.get('sender', '') if matched_email else None,
                                        original_date=matched_email.get('received_at', '') if matched_email else None
                                    )

                                    if success:
                                        # 删除邮箱草稿
                                        imap_handler.delete_draft(draft.get('id'))
                                        # Update database if matched — via API
                                        if matched_email:
                                            api.update_email_status(matched_email['id'], status='sent', draft_body=current_draft)
                                        st.toast("邮件已发送", icon="✅")
                                        rerun_after_mutation(1)
                                    else:
                                        st.error("操作失败")
                            else:
                                st.error("未找到收件人邮箱")

                    with c2:
                        if st.button("🗑️ 删除", key=f"delete_mail_{draft.get('id')}", help="处理这封草稿"):
                            imap_handler.delete_draft(draft.get('id'))
                            if matched_email:
                                api.update_email_status(matched_email['id'], status='skipped', reasoning="邮箱草稿已删除")
                            st.toast("草稿已删除", icon="🗑️")
                            rerun_after_mutation(1)

                    with c3:
                        if st.button("🔄 重新生成", key=f"regenerate_mail_{draft.get('id')}", help="重新生成 AI 回复"):
                            if matched_email:
                                with st.spinner('正在重新生成 AI 回复...'):
                                    # Prepare email_info dict
                                    email_info = {
                                        'product_model': matched_email.get('product_model', 'Unknown'),
                                        'problem_category': matched_email.get('ai_intent', 'Technical Support'),
                                        'sentiment': matched_email.get('ai_sentiment', 'Neutral'),
                                        'language': matched_email.get('language', 'en'),
                                        'conversation_context': thread_context
                                    }
                                    email_content = matched_email.get('body', '')

                                    # Generate new response using AI
                                    new_response = response_generator.generate_response(email_info, email_content)

                                    if new_response:
                                        # 用新回复替换邮箱草稿
                                        # First get the current draft to preserve original email info
                                        current_draft_content = st.session_state.get(f"mail_draft_{draft.get('id')}", draft_body)

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
                                            api.update_email_status(
                                                matched_email['id'],
                                                status='drafted',
                                                draft_body=new_response,
                                                reasoning="Manual regenerate from dashboard",
                                                knowledge_citations=response_generator.last_knowledge_citations,
                                            )
                                            st.toast("回复已重新生成", icon="🔄")
                                            rerun_after_mutation(1)
                                    else:
                                        st.error("未找到收件人邮箱")
                            else:
                                st.warning("未匹配到原始邮件，无法重新生成。")

                    with c4:
                        if st.button("🔃 刷新", key=f"sync_mail_{draft.get('id')}", help="从邮箱刷新"):
                            st.toast("正在刷新...", icon="🔄")
                            rerun_after_mutation(0.5)

                    with c5:
                        if st.button("💾 存为模板", key=f"save_tpl_{draft.get('id')}", help="将当前回复保存为模板"):
                            current_draft = st.session_state.get(f"mail_draft_{draft.get('id')}", draft_body)
                            if not current_draft or not current_draft.strip():
                                st.error("草稿为空，无法保存为模板")
                            else:
                                # 推断分类
                                category = "Technical/Usage Question"
                                model = ""
                                if matched_email:
                                    model = matched_email.get('product_model', '')
                                    intent = matched_email.get('ai_intent', '')
                                    # 映射 intent 到 category
                                    intent_map = {
                                        "Technical Support": "Technical/Usage Question",
                                        "Firmware Update": "Firmware Update",
                                        "Warranty/Repair": "Repair/Warranty",
                                        "Sales/Stock": "Price/Stock Inquiry",
                                        "Parts/Accessories Purchase": "Parts/Accessories Purchase",
                                        "Complaint/Frustration": "Complaint/Frustration",
                                        "Feedback/Suggestion": "Feedback/Suggestion",
                                        "Registration Unbinding": "Registration Unbinding",
                                        "Software Installation": "Software Installation",
                                        "Amazon Purchase Issues": "Amazon Purchase Issues",
                                    }
                                    category = intent_map.get(intent, "Technical/Usage Question")

                                tpl_name = f"人工模板 - {model or '通用'} - {category}"
                                try:
                                    result = api.create_template(
                                        name=tpl_name,
                                        category=category,
                                        body=current_draft,
                                        product_model=model,
                                    )
                                    if result.get("ok"):
                                        clear_dashboard_caches()
                                        st.toast("模板已保存！下次同类邮件将优先使用", icon="💾")
                                    else:
                                        st.error("保存模板失败")
                                except Exception as e:
                                    st.error(f"保存模板失败: {e}")

        # 展示仅存在于数据库、邮箱中未找到的草稿
        db_only_draft_emails = [
            email for email in all_db_emails
            if email.get('status') in {'drafted', 'forwarded_drafted', 'failed_retry'}
        ]
        if db_only_draft_emails:
            st.markdown("---")
            st.subheader("⚠️ 仅数据库草稿（邮箱中未找到）")

            for email in db_only_draft_emails:
                # 检查邮箱中是否存在对应草稿
                matched = any(
                    (match_draft_with_database(draft, [email]) or {}).get('id') == email.get('id')
                    for draft in mail_drafts
                )

                if not matched:
                    with st.expander(f"⚠️ [仅数据库] {email['subject']}"):
                        st.warning("这封草稿只存在于数据库，邮箱中未找到。请重新运行邮件处理进行同步。")
                        st.text_area("草稿", email.get('draft_body', ''), height=200, disabled=True, key=f"db_draft_{email['id']}")
                        render_knowledge_citations(email.get("knowledge_citations"), f"db_{email['id']}")

elif page == "问题队列":
    st.header("🔍 问题队列")
    st.caption("智能聚合客户反馈，识别重复问题，便于研发跟进和批量回复。")

    # ── Fetch issues via API ──
    issues = issues_all

    # ── Stats overview ──
    active_count = sum(1 for i in issues if i.get("status") not in ("closed", "bulk_replied"))
    p0_count = sum(1 for i in issues if i.get("priority") == "P0")
    high_count = sum(1 for i in issues if i.get("priority") in ("P0", "High"))
    total_users = sum(i.get("user_count", 0) or 0 for i in issues)

    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
    with col_s1:
        st.metric("问题总数", len(issues))
    with col_s2:
        st.metric("活跃中", active_count, delta=f"紧急: {p0_count}" if p0_count else None)
    with col_s3:
        st.metric("高优先级", high_count)
    with col_s4:
        st.metric("受影响用户", total_users)
    with col_s5:
        st.metric("产品覆盖", len({i.get("product_model") for i in issues}))

    st.markdown("---")

    # ── Action buttons row ──
    col_a1, col_a2, col_a3, col_a4 = st.columns([1.2, 1.2, 1, 3])
    with col_a1:
        if st.button("🤖 自动检测问题", help="扫描最近邮件，自动识别问题集群", use_container_width=True):
            with st.spinner("正在扫描邮件数据库..."):
                try:
                    result = api.auto_detect_issues(days=30, min_users=2, auto_create=True)
                    cands = result.get("candidates", [])
                    created = result.get("created", [])
                    if created:
                        st.success(f"检测到 {len(cands)} 个候选问题，已创建 {len(created)} 个问题")
                    elif cands:
                        st.info(f"检测到 {len(cands)} 个候选问题（已存在未重复创建）")
                    else:
                        st.info(result.get("summary", "未发现新问题集群"))
                    rerun_after_mutation(1)
                except Exception as e:
                    st.error(f"自动检测失败: {e}")

    with col_a2:
        daily_report_path = os.path.join(os.getcwd(), "Daily Report", "today_db_issues.json")
        daily_report_exists = os.path.exists(daily_report_path)
        if st.button(
            "📋 同步日报问题",
            help="从今日日报 JSON 导入问题" if daily_report_exists else "今日日报文件不存在",
            disabled=not daily_report_exists,
            use_container_width=True,
        ):
            if daily_report_exists:
                with st.spinner("正在从日报同步..."):
                    try:
                        import subprocess as _sp
                        venv_py = os.path.join(
                            os.environ.get("VIRTUAL_ENV", "C:\\Users\\USER\\.workbuddy\\binaries\\python\\envs\\mooer-api"),
                            "Scripts", "python.exe"
                        )
                        result = _sp.run(
                            [venv_py, "issue_scanner.py", "sync-daily", daily_report_path],
                            capture_output=True, text=True, timeout=30, cwd=os.getcwd(),
                        )
                        if result.returncode == 0:
                            st.success("日报问题同步完成")
                            rerun_after_mutation(1)
                        else:
                            st.error(f"同步失败: {result.stderr[:300]}")
                    except Exception as e:
                        st.error(f"同步异常: {e}")

    with col_a3:
        with st.expander("🔧 自定义扫描"):
            scan_product = st.text_input("产品型号", placeholder="如 GS1000, Prime P2", key="scan_product")
            scan_title = st.text_input("问题描述", placeholder="如 balance output after update", key="scan_title")
            scan_keywords = st.text_input("关键词（逗号分隔）", placeholder="balance, firmware, XLR", key="scan_kw")
            scan_cat = st.selectbox("分类", ["问题反馈", "硬件故障", "固件/软件问题", "用户投诉", "使用咨询", "保修/退换", "其他"], key="scan_cat")
            scan_pri = st.selectbox(
                "优先级",
                ["P0", "High", "Medium", "Low"],
                index=2,
                key="scan_pri",
                format_func=lambda x: {
                    "P0": "紧急",
                    "High": "高",
                    "Medium": "中",
                    "Low": "低",
                }.get(x, x),
            )
            if st.button("执行扫描", key="do_scan"):
                if scan_product and scan_title:
                    with st.spinner("扫描中..."):
                        try:
                            kws = [k.strip() for k in scan_keywords.split(",") if k.strip()]
                            result = api.scan_issue(
                                product_model=scan_product.strip(),
                                issue_title=scan_title.strip(),
                                keywords=kws if kws else [scan_title.strip()],
                                category=scan_cat,
                            )
                            if result.get("ok"):
                                st.success(
                                    f"扫描完成: {result.get('matched_count', 0)} 封候选邮件, "
                                    f"{result.get('unique_user_count', 0)} 个用户。请在问题详情里复核候选邮件。"
                                )
                                rerun_after_mutation(1)
                            else:
                                st.info(result.get("message", "扫描完成，无匹配"))
                        except Exception as e:
                            st.error(f"扫描失败: {e}")
                else:
                    st.warning("请输入产品型号和问题描述")

    with col_a4:
        if issues:
            st.download_button(
                "⬇ 导出全部问题",
                build_all_issues_xls(issues),
                file_name=f"mooer_issues_{datetime.now().strftime('%Y%m%d_%H%M')}.xls",
                mime="application/vnd.ms-excel",
                help="下载 Excel 格式的全部问题概览",
            )

    st.markdown("---")

    if not issues:
        st.info("暂无问题。点击「自动检测问题」或「同步日报问题」开始使用。")
    else:
        status_labels = {
            "new_detected": "🆕 新发现",
            "acknowledged": "👀 已确认",
            "sent_to_rnd": "📤 已转研发",
            "rnd_investigating": "🔬 研发调查中",
            "solution_ready": "✅ 已有方案",
            "bulk_reply_drafted": "📝 批量回复草稿",
            "bulk_replied": "📨 已批量回复",
            "closed": "🏁 已关闭",
        }
        priority_labels = {
            "P0": "🔴 紧急",
            "High": "🟠 高",
            "Medium": "🟡 中",
            "Low": "🟢 低",
        }
        rnd_status_labels = {
            "not_sent": "未转研发",
            "needs_review": "待复核",
            "sent": "已发送研发",
            "investigating": "研发处理中",
            "fixed": "已修复",
            "wont_fix": "不修复",
        }

        # ── Filter bar ──
        filt_col1, filt_col2, filt_col3 = st.columns(3)
        with filt_col1:
            status_filter = st.multiselect(
                "状态筛选",
                ["new_detected", "acknowledged", "sent_to_rnd", "rnd_investigating", "solution_ready", "bulk_reply_drafted", "bulk_replied", "closed"],
                default=[],
                key="filter_status",
                help="留空 = 全部显示",
                format_func=lambda x: status_labels.get(x, x),
            )
        with filt_col2:
            priority_filter = st.multiselect(
                "优先级筛选",
                ["P0", "High", "Medium", "Low"],
                default=[],
                key="filter_priority",
                help="留空 = 全部显示",
                format_func=lambda x: priority_labels.get(x, x),
            )
        with filt_col3:
            all_products = sorted({i.get("product_model", "") for i in issues if i.get("product_model")})
            product_filter = st.multiselect(
                "产品筛选",
                all_products,
                default=[],
                key="filter_product",
                help="留空 = 全部显示",
            )

        # Apply filters
        filtered = issues
        if status_filter:
            filtered = [i for i in filtered if i.get("status") in status_filter]
        if priority_filter:
            filtered = [i for i in filtered if i.get("priority") in priority_filter]
        if product_filter:
            filtered = [i for i in filtered if i.get("product_model") in product_filter]

        st.caption(f"显示 {len(filtered)} / {len(issues)} 个问题")

        # ── 问题列表 ──
        import pandas as pd
        df_data = []
        for issue in filtered:
            df_data.append({
                "ID": issue.get("id"),
                "产品": issue.get("product_model", ""),
                "问题标题": issue.get("issue_title", "")[:50],
                "分类": issue.get("issue_category", ""),
                "状态": status_labels.get(issue.get("status", ""), issue.get("status", "")),
                "优先级": priority_labels.get(issue.get("priority", ""), issue.get("priority", "")),
                "用户数": issue.get("user_count", 0) or 0,
                "邮件数": issue.get("email_count", 0) or 0,
                "研发": rnd_status_labels.get(issue.get("rnd_status", ""), issue.get("rnd_status", "")),
                "最近更新": str(issue.get("last_seen_at", ""))[:10],
            })
        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True, column_config={
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "产品": st.column_config.TextColumn("产品", width="small"),
            "问题标题": st.column_config.TextColumn("问题标题", width="large"),
            "状态": st.column_config.TextColumn("状态", width="medium"),
        })

        st.markdown("---")

        # ── 问题详情 ──
        issue_options = {
            f"#{i['id']} | {i.get('product_model','')} | {i.get('issue_title','')[:40]} | {i.get('user_count',0) or 0}用户": i["id"]
            for i in filtered
        }
        if not issue_options:
            st.info("当前筛选条件下无问题。调整筛选器试试。")
        else:
            selected_label = st.selectbox("选择问题查看详情", list(issue_options.keys()))
            selected_issue_id = issue_options[selected_label]
            selected_issue = next((i for i in issues if i["id"] == selected_issue_id), None)

            if selected_issue:
                st.subheader(selected_issue.get("issue_title", ""))
                m1, m2, m3, m4, m5 = st.columns(5)
                with m1:
                    st.metric("受影响用户", selected_issue.get("user_count", 0) or 0)
                with m2:
                    st.metric("相关邮件", selected_issue.get("email_count", 0) or 0)
                with m3:
                    st.metric("优先级", priority_labels.get(selected_issue.get("priority", ""), selected_issue.get("priority", "")))
                with m4:
                    st.metric("状态", status_labels.get(selected_issue.get("status",""), selected_issue.get("status","")))
                with m5:
                    st.metric("研发", rnd_status_labels.get(selected_issue.get("rnd_status", "not_sent"), selected_issue.get("rnd_status", "not_sent")))

                detail_refresh_col, detail_cache_col = st.columns([1, 4])
                with detail_refresh_col:
                    if st.button("刷新当前问题明细", key=f"refresh_issue_detail_{selected_issue_id}", use_container_width=True):
                        get_cached_issue_candidates.clear()
                        get_cached_issue_emails.clear()
                        st.session_state[f"issue_detail_last_refresh_{selected_issue_id}"] = datetime.now().strftime("%H:%M:%S")
                        st.rerun()
                with detail_cache_col:
                    detail_last_refresh = st.session_state.get(f"issue_detail_last_refresh_{selected_issue_id}")
                    detail_note = "候选邮件和关联邮件缓存 60 秒，仅在选中问题后加载。"
                    if detail_last_refresh:
                        detail_note += f" 上次手动刷新：{detail_last_refresh}"
                    st.caption(detail_note)

                # Status management
                issue_statuses = [
                    "new_detected", "acknowledged", "sent_to_rnd",
                    "rnd_investigating", "solution_ready",
                    "bulk_reply_drafted", "bulk_replied", "closed",
                ]
                rnd_statuses = ["not_sent", "needs_review", "sent", "investigating", "fixed", "wont_fix"]

                c1, c2 = st.columns(2)
                with c1:
                    new_status = st.selectbox(
                        "问题状态",
                        issue_statuses,
                        index=issue_statuses.index(selected_issue.get("status")) if selected_issue.get("status") in issue_statuses else 0,
                        format_func=lambda x: status_labels.get(x, x),
                        key=f"issue_status_detail_{selected_issue_id}",
                    )
                with c2:
                    new_rnd_status = st.selectbox(
                        "研发状态",
                        rnd_statuses,
                        index=rnd_statuses.index(selected_issue.get("rnd_status")) if selected_issue.get("rnd_status") in rnd_statuses else 0,
                        format_func=lambda x: rnd_status_labels.get(x, x),
                        key=f"rnd_status_detail_{selected_issue_id}",
                    )

                rnd_notes = st.text_area(
                    "研发备注",
                    selected_issue.get("rnd_notes") or "",
                    height=80,
                    key=f"rnd_notes_detail_{selected_issue_id}",
                )
                solution_summary = st.text_area(
                    "解决方案摘要",
                    selected_issue.get("solution_summary") or "",
                    height=80,
                    key=f"solution_detail_{selected_issue_id}",
                )
                final_reply_template = st.text_area(
                    "最终回复模板",
                    selected_issue.get("final_reply_template") or "",
                    height=120,
                    key=f"template_detail_{selected_issue_id}",
                )

                col_save, col_export = st.columns([1, 3])
                with col_save:
                    if st.button("💾 保存问题状态", key=f"save_issue_detail_{selected_issue_id}", use_container_width=True):
                        ok = api.update_issue(
                            selected_issue_id,
                            status=new_status,
                            rnd_status=new_rnd_status,
                            rnd_notes=rnd_notes,
                            solution_summary=solution_summary,
                            final_reply_template=final_reply_template,
                        )
                        if ok:
                            st.success("问题已更新")
                            rerun_after_mutation(0.5)
                        else:
                            st.error("更新失败")

                # Candidate emails review
                candidate_emails = []
                candidate_counts = {}
                try:
                    candidate_resp = get_cached_issue_candidates(selected_issue_id, limit=500)
                    candidate_emails = candidate_resp.get("items", [])
                    for item in candidate_emails:
                        candidate_status = item.get("candidate_status", "pending")
                        candidate_counts[candidate_status] = candidate_counts.get(candidate_status, 0) + 1
                except Exception as e:
                    if "HTTP 404" in str(e):
                        st.info("候选邮件复核接口还没有加载，请重启 API 后刷新页面。")
                    else:
                        st.warning(f"候选邮件复核加载失败：{e}")

                if candidate_emails:
                    st.markdown("---")
                    st.markdown("### 🧭 候选邮件复核")
                    st.caption(
                        "扫描结果先进入候选区。只有点“确认相关”后，才会计入正式问题统计和研发报告正文。"
                    )
                    st.caption(
                        " / ".join([
                            f"待复核 {candidate_counts.get('pending', 0)}",
                            f"确认相关 {candidate_counts.get('confirmed', 0)}",
                            f"相关线索 {candidate_counts.get('weak_related', 0)}",
                            f"不确定 {candidate_counts.get('unsure', 0)}",
                            f"已排除 {candidate_counts.get('excluded', 0)}",
                        ])
                    )

                    status_display = {
                        "pending": "待复核",
                        "confirmed": "确认相关",
                        "weak_related": "相关线索",
                        "excluded": "已排除",
                        "unsure": "不确定",
                    }

                    for cand in candidate_emails[:80]:
                        cand_status = cand.get("candidate_status") or "pending"
                        prefix = status_display.get(cand_status, cand_status)
                        with st.expander(f"[{prefix}] {cand.get('subject','无主题')[:70]} — {cand.get('sender','')[:35]}", expanded=cand_status == "pending"):
                            st.caption(
                                f"邮箱: {_extract_sender_email(cand.get('sender'))}  |  "
                                f"时间: {cand.get('received_at','')}  |  "
                                f"产品: {cand.get('product_model','')}  |  "
                                f"命中: {cand.get('matched_keywords','')}"
                            )
                            if cand.get("evidence_snippet"):
                                st.markdown("**证据片段**")
                                st.text_area(
                                    "证据片段",
                                    cand.get("evidence_snippet", "")[:1200],
                                    height=110,
                                    disabled=True,
                                    key=f"candidate_evidence_{selected_issue_id}_{cand.get('id')}",
                                    label_visibility="collapsed",
                                )
                            st.markdown("**原文预览**")
                            st.text_area(
                                "原文预览",
                                (cand.get("body") or "")[:2000],
                                height=150,
                                disabled=True,
                                key=f"candidate_body_{selected_issue_id}_{cand.get('id')}",
                                label_visibility="collapsed",
                            )

                            note_key = f"candidate_note_{selected_issue_id}_{cand.get('id')}"
                            review_note = st.text_input("复核备注", value=cand.get("review_note", ""), key=note_key)
                            c_confirm, c_weak, c_unsure, c_exclude = st.columns(4)
                            with c_confirm:
                                if st.button("✅ 确认相关", key=f"candidate_confirm_{selected_issue_id}_{cand.get('id')}"):
                                    api.review_issue_candidate(selected_issue_id, cand.get("id"), "confirmed", review_note)
                                    st.toast("已确认相关，并加入正式关联邮件", icon="✅")
                                    rerun_after_mutation(0.3)
                            with c_weak:
                                if st.button("📎 相关线索", key=f"candidate_weak_{selected_issue_id}_{cand.get('id')}"):
                                    api.review_issue_candidate(selected_issue_id, cand.get("id"), "weak_related", review_note)
                                    st.toast("已标为相关线索", icon="📎")
                                    rerun_after_mutation(0.3)
                            with c_unsure:
                                if st.button("❔ 不确定", key=f"candidate_unsure_{selected_issue_id}_{cand.get('id')}"):
                                    api.review_issue_candidate(selected_issue_id, cand.get("id"), "unsure", review_note)
                                    st.toast("已标为不确定", icon="❔")
                                    rerun_after_mutation(0.3)
                            with c_exclude:
                                if st.button("🚫 排除", key=f"candidate_exclude_{selected_issue_id}_{cand.get('id')}"):
                                    api.review_issue_candidate(selected_issue_id, cand.get("id"), "excluded", review_note)
                                    st.toast("已排除，后续扫描不会覆盖该排除结果", icon="🚫")
                                    rerun_after_mutation(0.3)

                # Linked emails
                linked_resp = get_cached_issue_emails(selected_issue_id, limit=500)
                linked_emails = linked_resp.get("items", [])

                if linked_emails:
                    st.markdown("---")
                    st.markdown("### 📧 关联邮件")

                    # Export buttons
                    exp_col1, exp_col2, exp_col3 = st.columns(3)
                    with exp_col1:
                        xls_data = build_issue_report_xls(selected_issue, linked_emails)
                        st.download_button(
                            "⬇ 导出 Excel",
                            xls_data,
                            file_name=f"issue_{selected_issue_id}_{selected_issue.get('product_model','')}_report.xls",
                            mime="application/vnd.ms-excel",
                        )
                    with exp_col2:
                        html_data = build_issue_report_html(selected_issue, linked_emails)
                        st.download_button(
                            "⬇ 导出 HTML 报告",
                            html_data,
                            file_name=f"issue_{selected_issue_id}_{selected_issue.get('product_model','')}_report.html",
                            mime="text/html; charset=utf-8",
                        )
                    with exp_col3:
                        user_emails = sorted({_extract_sender_email(em.get("sender")) for em in linked_emails if _extract_sender_email(em.get("sender"))})
                        st.download_button(
                            "⬇ 用户邮箱列表",
                            "\n".join(user_emails),
                            file_name=f"issue_{selected_issue_id}_users.txt",
                            mime="text/plain",
                        )

                    # Email table
                    export_rows = []
                    for email in linked_emails:
                        export_rows.append({
                            "日期": str(email.get("received_at", ""))[:10],
                            "用户": email.get("sender", "")[:30],
                            "主题": email.get("subject", "")[:60],
                            "状态": email.get("status", ""),
                            "AI意图": email.get("ai_intent", ""),
                        })
                    st.dataframe(pd.DataFrame(export_rows), use_container_width=True, hide_index=True)

                    # Expandable detail
                    for email in linked_emails[:20]:
                        with st.expander(f"{email.get('subject','无主题')[:60]} — {email.get('sender','')[:30]}"):
                            st.caption(f"时间: {email.get('received_at','')}  |  状态: {email.get('status','')}  |  AI意图: {email.get('ai_intent','')}")
                            st.text_area("正文", (email.get("body") or "")[:3000], height=150, disabled=True, key=f"issue_body_{selected_issue_id}_{email.get('id')}")
                else:
                    st.info("此问题暂无关联邮件。")

elif page == "跳过邮件":
    st.header("🚫 跳过邮件")

    try:
        emails_resp = get_cached_emails(status='skipped', limit=100)
        emails = emails_resp.get("items", [])
    except Exception:
        emails = []

    if not emails:
        st.info("暂无跳过邮件。")
    else:
        for email in emails:
            # 显示标签（如果存在）
            label_display = f"🏷️ **{email['label']}**" if email.get('label') else ""
            with st.expander(f"[ID: {email['id']}] [{email['ai_intent']}] {email['subject']} - {email['sender']} {label_display}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**标签：** {email.get('label', 'N/A')}")
                with col2:
                    st.write(f"**意图：** {email['ai_intent']}")
                st.write(f"**判断依据：** {email['ai_reasoning']}")
                st.text_area("正文", email['body'], height=150, disabled=True, key=f"content_{email['id']}")
                
                # 显示附件
                if email['attachments']:
                    try:
                        import json
                        attachments = json.loads(email['attachments'])
                        if attachments:
                            st.markdown("#### 📎 附件")
                            for att in attachments:
                                st.markdown(f"- **{att['filename']}** ({att['size']})")
                    except Exception:
                        pass
                
                if st.button("恢复到邮件草稿", key=f"restore_{email['id']}"):
                    api.update_email_status(email['id'], status='drafted')
                    st.toast("已恢复到邮件草稿", icon="📥")
                    rerun_after_mutation(1)

elif page == "知识库":
    st.header("📚 知识库")

    layer_labels = {
        "product_manual": "产品说明书",
        "product_page_download": "产品页/说明书下载",
        "firmware_software_download": "固件/软件/驱动下载",
        "support_policy": "售后政策",
        "business_data": "业务数据",
        "issue_solution": "已解决问题/客服经验",
    }

    st.caption("把说明书、下载入口、售后政策、配件价格、经销商、回复模板和已解决 issue 分层管理。")

    col_sync, col_upload = st.columns([1, 2])
    with col_sync:
        if st.button("同步现有知识", use_container_width=True, disabled=not _api_ok):
            try:
                result = api.sync_knowledge()
                clear_dashboard_caches()
                st.success(
                    f"同步完成：更新 {result.get('documents', 0)} 个文档，"
                    f"{result.get('chunks', 0)} 个片段，跳过 {result.get('skipped', 0)} 个未变化文档。"
                )
                st.rerun()
            except Exception as e:
                st.error(f"同步失败: {e}")

    with col_upload:
        uploaded_file = st.file_uploader("上传产品说明书（PDF）", type="pdf")
        if uploaded_file:
            manuals_dir = "MOOER产品说明书"
            os.makedirs(manuals_dir, exist_ok=True)
            save_path = os.path.join(manuals_dir, uploaded_file.name)
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success(f"已保存 {uploaded_file.name}。请点击“同步现有知识”更新知识库索引。")

    if not _api_ok:
        st.warning("API 服务未连接，无法查看结构化知识库索引。")

    try:
        summary = get_cached_knowledge_summary() if _api_ok else {"totals": {}, "by_type": [], "by_source": []}
    except Exception as e:
        summary = {"totals": {}, "by_type": [], "by_source": []}
        st.error(f"读取知识库统计失败: {e}")

    totals = summary.get("totals", {})
    metric_cols = st.columns(3)
    metric_cols[0].metric("知识文档", totals.get("documents", 0))
    metric_cols[1].metric("内容片段", totals.get("chunks", 0))
    metric_cols[2].metric("知识层数", len({r.get("knowledge_type") for r in summary.get("by_type", [])}))

    st.markdown("### 分层总览")
    by_type_rows = []
    for row in summary.get("by_type", []):
        by_type_rows.append({
            "知识层": layer_labels.get(row.get("knowledge_type"), row.get("knowledge_type", "")),
            "状态": row.get("status", ""),
            "文档数": row.get("document_count", 0),
            "片段数": row.get("chunk_count", 0),
        })
    if by_type_rows:
        st.dataframe(pd.DataFrame(by_type_rows), use_container_width=True, hide_index=True)
    else:
        st.info("暂无结构化知识索引。点击“同步现有知识”开始整理。")

    with st.expander("来源统计", expanded=False):
        by_source_rows = [
            {"来源类型": r.get("source_kind", ""), "文档数": r.get("document_count", 0)}
            for r in summary.get("by_source", [])
        ]
        if by_source_rows:
            st.dataframe(pd.DataFrame(by_source_rows), use_container_width=True, hide_index=True)
        else:
            st.info("暂无来源统计。")

    st.markdown("### 知识文档")
    filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])
    with filter_col1:
        selected_layer_label = st.selectbox(
            "知识层",
            ["全部"] + [layer_labels[k] for k in layer_labels],
            key="kb_layer_filter",
        )
    with filter_col2:
        selected_status = st.selectbox("状态", ["全部", "active", "draft", "archived"], key="kb_status_filter")
    with filter_col3:
        doc_limit = st.number_input("显示数量", min_value=20, max_value=1000, value=200, step=20, key="kb_doc_limit")

    label_to_key = {v: k for k, v in layer_labels.items()}
    selected_layer = None if selected_layer_label == "全部" else label_to_key.get(selected_layer_label)
    status_filter = None if selected_status == "全部" else selected_status

    try:
        docs_resp = get_cached_knowledge_documents(selected_layer, status_filter, int(doc_limit)) if _api_ok else {"items": []}
        docs = docs_resp.get("items", [])
    except Exception as e:
        docs = []
        st.error(f"读取知识文档失败: {e}")

    if docs:
        doc_rows = []
        for doc in docs:
            doc_rows.append({
                "ID": doc.get("id"),
                "知识层": layer_labels.get(doc.get("knowledge_type"), doc.get("knowledge_type", "")),
                "状态": doc.get("status", ""),
                "产品": doc.get("product_model", ""),
                "标题": doc.get("title", ""),
                "来源": doc.get("source_kind", ""),
                "片段": doc.get("chunk_count", 0),
                "路径/URL": doc.get("source_url") or doc.get("source_path") or doc.get("source_table") or "",
            })
        st.dataframe(pd.DataFrame(doc_rows), use_container_width=True, hide_index=True)
    else:
        st.info("没有匹配的知识文档。")

elif page == "配件价格":
    st.header("💰 配件价格管理")
    st.caption("管理产品配件报价。修改后即时生效，AI 回复时将自动使用最新价格。")

    if not _api_ok:
        st.error("📡 **API 服务器未连接** — 配件价格功能需要 API 才能工作。请在左侧边栏点击「启动 API 服务器」或手动运行 `启动API.bat`。")

    try:
        prices_resp = get_cached_prices()
        prices = prices_resp.get("items", [])
    except Exception:
        prices = []

    # ── Add new price form ──
    with st.expander("➕ 添加新价格", expanded=False):
        col_a, col_b, col_c, col_d = st.columns([2, 2, 1, 1])
        with col_a:
            new_model = st.text_input("产品型号", placeholder="如 GE200 Pro Li", key="new_price_model",
                                      disabled=not _api_ok)
        with col_b:
            new_part = st.text_input("配件名称", placeholder="如 screen, battery", key="new_price_part",
                                     disabled=not _api_ok)
        with col_c:
            new_price = st.number_input("价格 (USD)", min_value=0.0, step=0.5, key="new_price_val",
                                        disabled=not _api_ok)
        with col_d:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("保存", key="save_new_price", use_container_width=True, disabled=not _api_ok):
                if new_model.strip() and new_part.strip() and new_price > 0:
                    try:
                        api.create_price(new_model.strip(), new_part.strip(), new_price)
                        st.toast("价格已添加", icon="✅")
                        rerun_after_mutation(0.5)
                    except Exception as e:
                        st.error(f"添加失败: {e}")
                else:
                    st.warning("请填写完整的型号、配件和价格")

    st.markdown("---")

    if not prices:
        st.info("暂无配件价格数据。点击上方「添加新价格」开始。")
    else:
        # Display as editable table
        for p in prices:
            col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
            with col1:
                new_model_val = st.text_input("型号", value=p["product_model"],
                                              key=f"pm_{p['id']}", label_visibility="collapsed")
            with col2:
                new_part_val = st.text_input("配件", value=p["part_name"],
                                             key=f"pn_{p['id']}", label_visibility="collapsed")
            with col3:
                new_price_val = st.number_input("价格", value=float(p["price"]),
                                                min_value=0.0, step=0.5,
                                                key=f"pr_{p['id']}", label_visibility="collapsed")
            with col4:
                st.caption(f"USD")
            with col5:
                c_save, c_del = st.columns(2)
                with c_save:
                    if st.button("💾", key=f"save_p_{p['id']}", help="保存修改", disabled=not _api_ok):
                        try:
                            api.update_price(p["id"],
                                             product_model=new_model_val.strip(),
                                             part_name=new_part_val.strip(),
                                             price=new_price_val)
                            st.toast("已更新", icon="✅")
                            rerun_after_mutation(0.5)
                        except Exception as e:
                            st.error(f"更新失败: {e}")
                with c_del:
                    if st.button("🗑", key=f"del_p_{p['id']}", help="删除", disabled=not _api_ok):
                        try:
                            api.delete_price(p["id"])
                            st.toast("已删除", icon="🗑️")
                            rerun_after_mutation(0.5)
                        except Exception as e:
                            st.error(f"删除失败: {e}")

elif page == "回复模板":
    st.header("📝 回复模板管理")
    st.caption("运营保存的优质回复模板。AI 生成回复时将优先匹配这些模板。")

    if not _api_ok:
        st.error("📡 **API 服务器未连接** — 回复模板功能需要 API 才能工作。请在左侧边栏点击「启动 API 服务器」或手动运行 `启动API.bat`。")

    try:
        tmpl_resp = get_cached_templates()
        templates = tmpl_resp.get("items", [])
    except Exception:
        templates = []

    # Stats
    active_count = sum(1 for t in templates if t.get("status") == "active")
    st.metric("活跃模板数", f"{active_count} / {len(templates)}")

    if not templates:
        st.info("暂无保存的回复模板。在「邮件草稿」页面编辑草稿后点击「💾 存为模板」即可创建。")
    else:
        for t in templates:
            status_icon = "🟢" if t.get("status") == "active" else "🔴"
            with st.expander(f"{status_icon} #{t['id']} | {t.get('category','')} | {t.get('product_model','')} | {t.get('name','')[:40]}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.caption(f"**分类**: {t.get('category', '')}")
                    st.caption(f"**产品**: {t.get('product_model', '') or '通用'}")
                    st.caption(f"**语言**: {t.get('language', 'en')}")
                    st.caption(f"**状态**: {t.get('status', 'active')}")
                    st.caption(f"**更新**: {str(t.get('updated_at', ''))[:16]}")
                with col2:
                    edited_body = st.text_area(
                        "模板内容",
                        value=t.get("body", ""),
                        height=200,
                        key=f"tpl_body_{t['id']}"
                    )
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("💾 保存修改", key=f"save_tpl_{t['id']}", disabled=not _api_ok):
                            try:
                                api.update_template(t["id"], body=edited_body)
                                st.toast("模板已更新", icon="✅")
                                rerun_after_mutation(0.5)
                            except Exception as e:
                                st.error(f"更新失败: {e}")
                    with c2:
                        new_status = "inactive" if t.get("status") == "active" else "active"
                        toggle_label = "⏸ 停用" if t.get("status") == "active" else "▶ 启用"
                        if st.button(toggle_label, key=f"toggle_tpl_{t['id']}", disabled=not _api_ok):
                            try:
                                api.update_template(t["id"], status=new_status)
                                st.toast(f"模板已{'停用' if new_status == 'inactive' else '启用'}", icon="🔄")
                                rerun_after_mutation(0.5)
                            except Exception as e:
                                st.error(f"操作失败: {e}")
                    with c3:
                        if st.button("🗑 删除", key=f"del_tpl_{t['id']}", disabled=not _api_ok):
                            try:
                                api.delete_template(t["id"])
                                st.toast("模板已删除", icon="🗑️")
                                rerun_after_mutation(0.5)
                            except Exception as e:
                                st.error(f"删除失败: {e}")

elif page == "系统日志":
    st.header("📝 系统日志")
    
    try:
        logs_resp = get_cached_logs(limit=50)
        logs = logs_resp.get("items", [])
    except Exception:
        logs = []
    if logs:
        df_logs = pd.DataFrame(logs)
        st.dataframe(df_logs, use_container_width=True, width='stretch')
    else:
        st.info("暂无跳过邮件。")

# Footer
st.markdown("---")
st.caption("MOOER 客服系统 v2.0 - AI 辅助")
