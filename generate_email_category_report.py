import html
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


DB_PATH = Path("mooer_support.db")
OUT_DIR = Path("Daily Report")
OUT_DIR.mkdir(exist_ok=True)
OUT_PATH = OUT_DIR / f"email_category_report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"


def u(text):
    return text.encode("utf-8").decode("unicode_escape")


ZH = {
    "title": "MOOER 售后邮件分类、问题分类与回复模板报告",
    "generated": "生成时间",
    "database": "数据库",
    "overview": "概览",
    "mail_type": "邮件类型",
    "issue_type": "问题类型",
    "templates": "回复模板",
    "linked_issues": "已归并问题",
    "examples": "用户邮箱案例",
    "email_total": "邮件总数",
    "email_users": "可识别用户邮箱",
    "issue_pool": "售后问题池",
    "active_templates": "活跃回复模板",
    "note_title": "报告说明",
    "note": "邮件一级分类主要参考数据库字段 ai_intent，并通过规则纠偏（商务/合作类邮件如内容明显为技术问题则自动纠正）。产品问题分类基于主题和正文关键词规则归类，用于内部汇总和复核。案例表含「原始AI理由」列，方便审核误判。",
    "category": "分类",
    "count": "数量",
    "ratio": "占比",
    "product": "产品",
    "template_group": "模板大类",
    "subtype": "细分类",
    "user_email": "用户邮箱",
    "time": "时间",
    "subject": "主题",
    "classification": "分类结果",
    "mail_reason": "邮件类型依据",
    "issue_reason": "问题分类依据",
    "evidence": "证据片段",
    "reason": "AI判断理由",
    "unknown_product": "未识别",
    "inferred": "补识别",
    "general": "通用",
    "none": "无",
    "merged": "合并",
    "ids": "原问题ID",
    "unknown_reason": "产品未识别原因分析",
    "unknown_reason_note": "产品未识别不等于没有产品。它主要来自三类：1）合作、垃圾邮件等确实没有产品；2）旧邮件或重复邮件没有重新跑产品识别；3）用户写法不标准，例如 GE150Pro、Prime 2、GS1000Li、SD 75，现有识别规则漏掉了。",
    "empty_product_by_intent": "未识别产品按邮件类型分布",
    "empty_product_mentions": "未识别邮件中仍然出现的产品名",
    "product_issue_distribution": "产品问题分类分布",
    "reply_method_distribution": "建议回复方式分类",
    "existing_templates": "数据库现有模板",
    "mail_examples": "按邮件类型举例",
    "issue_examples": "按产品问题举例",
    "status": "状态",
    "priority": "优先级",
    "users": "用户数",
    "emails": "邮件数",
    "correction_title": "AI 误判纠正统计",
    "correction_note": "以下邮件在数据库中被 AI 标为商务/合作/售前类，但邮件内容明确是技术支持问题，报告中已自动纠正。",
    "original_ai": "原始AI意图",
    "corrected_to": "纠正为",
    "original_reason": "原始AI理由",
}


MAIL_CATEGORY = {
    "Technical Support": "technical_support / 技术支持",
    "Firmware Update": "firmware_update / 固件升级",
    "Warranty/Repair": "warranty_repair / 保修维修",
    "Gratitude": "customer_followup_ack / 用户跟进或确认",
    "Partnership/Collaboration": "business_media / 商务合作",
    "Sales/Stock": "sales_stock / 售前库存",
    "Press/Media": "business_media / 媒体评测",
    "Dealer Inquiry": "business_media / 经销商咨询",
    "Spam": "spam_irrelevant / 垃圾无关",
    "Other": "human_review_or_other / 其他复核",
    None: "unclassified / 未分类",
    "": "unclassified / 未分类",
}

# 需要纠偏的 intent 集合
BUSINESS_INTENTS = {"Partnership/Collaboration", "Press/Media", "Dealer Inquiry", "Sales/Stock"}

STABLE_MAIL_CATEGORY = {
    "technical_support": MAIL_CATEGORY["Technical Support"],
    "firmware_update": MAIL_CATEGORY["Firmware Update"],
    "warranty_repair": MAIL_CATEGORY["Warranty/Repair"],
    "customer_followup_ack": MAIL_CATEGORY["Gratitude"],
    "business_media": "business_media / 商务媒体",
    "sales_stock": MAIL_CATEGORY["Sales/Stock"],
    "spam_irrelevant": MAIL_CATEGORY["Spam"],
    "system_notification": "system_notification / 系统通知",
    "unclassified": MAIL_CATEGORY[None],
}


ISSUE_RULES = [
    ("firmware_update_failed / 固件升级失败", ["firmware", "update", "upgrade", "select button", "bootloader"]),
    ("app_usb_bluetooth_connection / App/USB/蓝牙连接问题", ["connect", "connection", "usb", "bluetooth", "app", "ios", "android", "driver", "recognize", "pair", "response timeout"]),
    ("power_boot_freeze / 无法开机、卡Logo、死机", ["turn on", "doesnt turn on", "doesn't turn on", "not turn on", "boot logo", "stuck", "freeze", "frozen", "brick"]),
    ("audio_output_noise / 音频输出、噪声、平衡输出", ["sound", "audio", "output", "noise", "hum", "balance", "balanced", "xlr", "volume", "signal"]),
    ("screen_led_hardware / 屏幕、LED、按键、硬件", ["screen", "display", "lcd", "led", "backlight", "button", "knob", "battery", "power board", "broken"]),
    ("software_install_driver / 软件安装、驱动、Mac问题", ["install", "installation", "mac", "gatekeeper", "studio", "parse", "mr file", "software"]),
    ("registration_account / 注册、解绑、账号、序列号", ["register", "registration", "unbind", "serial number", "account", "country code"]),
    ("parts_quote_shipping / 配件、报价、运费", ["spare part", "replacement", "part", "price", "quote", "shipping"]),
    ("usage_midi_looper_preset / 功能使用、MIDI、Looper、预设", ["midi", "looper", "preset", "tone", "drum", "clock", "expression", "footswitch", "manual"]),
    ("business_sales_media / 商务、媒体、购买渠道", ["collaboration", "partnership", "youtube", "review", "dealer", "distributor", "purchase", "buy", "stock"]),
]

PRODUCT_ALIASES = [
    ("GE150 Pro", ["GE150 Pro", "GE 150 Pro", "GE150Pro", "GE 150Pro"]),
    ("GE100 Pro Li", ["GE100 Pro Li", "GE 100 Pro Li", "GE100ProLi", "GE 100 ProLi"]),
    ("GE100 Pro", ["GE100 Pro", "GE 100 Pro", "GE100Pro"]),
    ("GE150 MAX", ["GE150 MAX", "GE 150 MAX", "GE150 MaxLi", "GE 150 MaxLi", "GE150_max"]),
    ("GS1000Li", ["GS1000Li", "GS1000 Li", "GS 1000 Li"]),
    ("GS1000", ["GS1000", "GS 1000", "Gs1000"]),
    ("GE1000", ["GE1000", "GE 1000"]),
    ("GE300", ["GE300", "GE 300", "GE300Lite", "GE 300 Lite"]),
    ("GE250", ["GE250", "GE 250", "gente 250"]),
    ("GE200", ["GE200", "GE 200"]),
    ("GE150", ["GE150", "GE 150"]),
    ("GE100", ["GE100", "GE 100"]),
    ("Prime P2", ["Prime P2", "Prime 2", "Mooer P2", "P2", "RIME P2", "Rime P2"]),
    ("Prime M2", ["Prime M2", "Mooer M2"]),
    ("Prime P1", ["Prime P1", "Mooer P1"]),
    ("Prime M1", ["Prime M1", "M1 Prime"]),
    ("F15i Li", ["F15i Li", "F15iLi"]),
    ("F15i", ["F15i", "F15 i"]),
    ("F40i", ["F40i", "F40 i"]),
    ("GL200", ["GL200", "GL 200"]),
    ("GL100", ["GL100", "GL 100"]),
    ("PE100", ["PE100", "PE 100"]),
    ("LoFi Machine", ["LoFi Machine", "Lo-Fi Machine"]),
    ("SD75", ["SD75", "SD 75"]),
    ("SD30i", ["SD30i", "SD 30i"]),
    ("SD10i", ["SD10i", "SD 10i"]),
    ("SD50A", ["SD50A", "SD 50A"]),
    ("Free Step", ["Free Step", "FreeStep"]),
    ("Drummer X2", ["Drummer X2", "DrummerX2"]),
    ("Radar", ["Radar"]),
]


def esc(value):
    return html.escape("" if value is None else str(value))


def extract_email(sender):
    if not sender:
        return ""
    match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", sender)
    return match.group(0) if match else sender.strip()


def clean_text(value, limit=None):
    value = value or ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if limit and len(value) > limit:
        return value[:limit].rstrip() + "..."
    return value


def current_message(body):
    body = body or ""
    return re.split(
        r"\nOn .{0,120}wrote:|\r\nOn .{0,120}wrote:|-----Original Message-----|_{5,}|From:",
        body,
        maxsplit=1,
        flags=re.I | re.S,
    )[0][:1200]


def normalize_for_match(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def infer_product(row):
    db_product = (row["product_model"] if "product_model" in row.keys() else None) or ""
    db_product = str(db_product).strip()
    if db_product:
        return db_product, False

    text = (row["subject"] or "") + " " + current_message(row["body"] or "")
    compact = normalize_for_match(text)
    for official, aliases in PRODUCT_ALIASES:
        for alias in aliases:
            if normalize_for_match(alias) in compact:
                return official, True
    return ZH["unknown_product"], False


def classify_issue(row):
    subject = row["subject"] or ""
    body = current_message(row["body"] or "")
    text = (subject + " " + body).lower()
    hits = []
    for name, keywords in ISSUE_RULES:
        score = sum(1 for keyword in keywords if keyword in text)
        if score:
            hits.append((score, name, keywords))
    if not hits:
        return "unknown_issue / 未明确问题", "", "未找到明显问题关键词"
    hits.sort(reverse=True, key=lambda item: item[0])
    name = hits[0][1]
    evidence = clean_text(subject + " " + body, 520)
    lower = evidence.lower()
    keyword_hit = ""
    pos = -1
    for keyword in hits[0][2]:
        pos = lower.find(keyword)
        if pos >= 0:
            keyword_hit = keyword
            break
    if pos >= 0:
        snippet = evidence[max(0, pos - 90): min(len(evidence), pos + 180)]
    else:
        snippet = evidence[:260]
    reason = "命中关键词：" + (keyword_hit or "n/a") + "；根据主题/当前正文归入 " + name
    return name, snippet, reason


def refine_mail_category(row, issue_category, display_product):
    """对数据库 ai_intent 进行纠偏，返回 (最终分类, 判断理由)。"""
    stable_mail = row["mail_category"] if "mail_category" in row.keys() else None
    if stable_mail:
        return STABLE_MAIL_CATEGORY.get(stable_mail, stable_mail), f"from database mail_category={stable_mail}"

    raw_intent = row["ai_intent"] if "ai_intent" in row.keys() else None
    base = MAIL_CATEGORY.get(raw_intent, raw_intent or MAIL_CATEGORY[None])
    subject = row["subject"] or ""
    body = current_message(row["body"] or "")
    text = (subject + " " + body).lower()

    issue_known = not issue_category.startswith("unknown_issue")
    technical_terms = [
        "connect", "connection", "usb", "bluetooth", "app", "firmware", "update",
        "upgrade", "problem", "issue", "not working", "failed", "error", "sound",
        "screen", "display", "stuck", "frozen", "loading 0", "no output",
    ]

    if raw_intent == "Spam":
        return base, "来自数据库 ai_intent=Spam，作为垃圾/无关邮件处理"

    # 核心纠偏：商务/售前/媒体 intent 中内容明显是技术问题的
    if raw_intent in BUSINESS_INTENTS:
        if issue_known and any(term in text for term in technical_terms):
            # 优先按 issue_category 判断（比关键词更精准）
            if issue_category.startswith("firmware_update"):
                return (MAIL_CATEGORY["Firmware Update"],
                        f"数据库 ai_intent={raw_intent}，但邮件内容明确是固件/升级问题，报告纠正为固件升级")
            # "update" 关键词太泛（连接邮件也可能含 "app update"），
            # 需要同时有 firmware/upgrade/select/bootloader 才判定为固件类
            has_firmware_kw = any(kw in text for kw in ["firmware", "upgrade", "select button", "bootloader"])
            if "update" in text and has_firmware_kw:
                return (MAIL_CATEGORY["Firmware Update"],
                        f"数据库 ai_intent={raw_intent}，但邮件内容明确是固件/升级问题，报告纠正为固件升级")
            return (MAIL_CATEGORY["Technical Support"],
                    f"数据库 ai_intent={raw_intent}，但邮件内容明确是技术问题，报告纠正为技术支持")

    if raw_intent == "Gratitude":
        if issue_known:
            return base, "数据库 ai_intent=Gratitude，但当前邮件/引用中仍有可追踪问题，作为用户跟进或确认处理"
        return base, "数据库 ai_intent=Gratitude，未发现明确新问题，作为用户跟进或确认处理"

    if raw_intent:
        return base, f"来自数据库 ai_intent={raw_intent}"
    return base, "数据库 ai_intent 为空，作为未分类邮件处理"


def infer_reply_category(mail_category, issue_category):
    text = (mail_category + " " + issue_category).lower()
    if "firmware" in text:
        return "firmware_instruction / 固件升级指导"
    if "parts" in text or "screen_led_hardware" in text:
        return "parts_quote_or_request_evidence / 配件报价或请求视频证据"
    if "registration" in text:
        return "registration_request_or_reset / 注册解绑处理"
    if "software" in text or "connection" in text:
        return "troubleshooting_steps / 技术排查步骤"
    if "warranty" in text:
        return "dealer_referral_or_repair / 经销商或维修处理"
    if "spam" in text:
        return "spam_no_reply / 垃圾无关不回复"
    if "business" in text or "sales" in text:
        return "escalate_to_sales_media / 转销售媒体团队"
    return "manual_human_reply / 人工回复"


# ---- 邮件类型配色方案 ----
MAIL_COLORS = {
    "technical_support": "#2563eb",   # 蓝色
    "firmware_update": "#7c3aed",    # 紫色
    "warranty_repair": "#dc2626",    # 红色
    "customer_followup_ack": "#059669",  # 绿色
    "human_review_or_other": "#6b7280",   # 灰色
    "spam_irrelevant": "#9ca3af",    # 浅灰
    "business_media": "#d97706",     # 橙色
    "sales_stock": "#ea580c",       # 深橙
    "unclassified": "#94a3b8",       # 石板灰
}

ISSUE_COLORS = {
    "app_usb_bluetooth_connection": "#2563eb",
    "firmware_update_failed": "#7c3aed",
    "audio_output_noise": "#dc2626",
    "screen_led_hardware": "#ea580c",
    "software_install_driver": "#0891b2",
    "power_boot_freeze": "#be123c",
    "usage_midi_looper_preset": "#4f46e5",
    "business_sales_media": "#d97706",
    "parts_quote_shipping": "#059669",
    "registration_account": "#0d9488",
    "unknown_issue": "#94a3b8",
}


def get_mail_color_key(category_name):
    for key in MAIL_COLORS:
        if category_name.startswith(key):
            return key
    return "unclassified"


def get_issue_color_key(category_name):
    for key in ISSUE_COLORS:
        if category_name.startswith(key):
            return key
    return "unknown_issue"


def count_table(counter, title, total, limit=30):
    rows = []
    for key, value in sorted_counter_items(counter, limit):
        color_key = get_mail_color_key(key) if " / " in key else "unclassified"
        color = MAIL_COLORS.get(color_key, "#6b7280")
        pct = value / total * 100
        bar_width = min(pct, 100)
        rows.append(
            f'<tr>'
            f'<td><span style="color:{color};font-weight:600;">●</span> {esc(key)}</td>'
            f'<td class="nowrap" style="font-weight:600;">{value}</td>'
            f'<td style="width:30%;">'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<div style="flex:1;background:#e5e7eb;border-radius:4px;height:16px;overflow:hidden;">'
            f'<div style="width:{bar_width}%;background:{color};height:100%;border-radius:4px;"></div>'
            f'</div>'
            f'<span class="small" style="min-width:40px;text-align:right;">{value / total:.1%}</span>'
            f'</div>'
            f'</td></tr>'
        )
    return (
        f"<h3>{esc(title)}</h3>"
        f'<table><thead><tr><th>{esc(ZH["category"])}</th>'
        f'<th>{esc(ZH["count"])}</th><th>{esc(ZH["ratio"])}</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def sorted_counter_items(counter, limit=None):
    def sort_key(item):
        key, value = item
        key_lower = str(key).lower()
        is_unclassified = "unclassified" in key_lower or "未分类" in key_lower
        return (1 if is_unclassified else 0, -value, key_lower)
    items = sorted(counter.items(), key=sort_key)
    return items[:limit] if limit else items


def example_table(items, show_ai_reason=False):
    rows = []
    for item in items:
        product_label = item["display_product"]
        if item.get("product_inferred"):
            product_label = f"{product_label} ({ZH['inferred']})"
        # 邮件类型标签颜色
        mc_key = get_mail_color_key(item["mail_category"])
        mc_color = MAIL_COLORS.get(mc_key, "#6b7280")
        ic_key = get_issue_color_key(item["issue_category"])
        ic_color = ISSUE_COLORS.get(ic_key, "#6b7280")

        ai_reason_col = ""
        if show_ai_reason:
            raw_ai = item.get("ai_reasoning") or ""
            ai_reason_col = f'<td class="small" style="max-width:200px;color:#be123c;">{esc(clean_text(raw_ai, 120))}</td>'

        rows.append(
            "<tr>"
            f'<td class="mono">{esc(item["sender_email"])}</td>'
            f'<td>{esc(clean_text(item.get("received_at"), 50))}</td>'
            f'<td style="max-width:180px;">{esc(clean_text(item.get("subject"), 100))}</td>'
            f"<td>{esc(product_label)}</td>"
            f'<td><span class="tag" style="border-color:{mc_color}33;background:{mc_color}11;color:{mc_color};">{esc(item["mail_category"])}</span><br>'
            f'<span class="tag" style="border-color:{ic_color}33;background:{ic_color}11;color:{ic_color};">{esc(item["issue_category"])}</span><br>'
            f'<span class="tag">{esc(item["reply_template_category"])}</span></td>'
            f'<td class="evidence" style="max-width:240px;">{esc(clean_text(item["evidence"], 200))}</td>'
            f'<td class="small" style="max-width:220px;">{esc(item["mail_reason"])}</td>'
            f"{ai_reason_col}"
            "</tr>"
        )
    ai_reason_header = f'<th style="color:#be123c;">{esc(ZH["reason"])}</th>' if show_ai_reason else ""
    header = (
        f'<thead><tr><th>{esc(ZH["user_email"])}</th><th>{esc(ZH["time"])}</th>'
        f'<th>{esc(ZH["subject"])}</th><th>{esc(ZH["product"])}</th>'
        f'<th>{esc(ZH["classification"])}</th><th>{esc(ZH["evidence"])}</th>'
        f'<th>{esc(ZH["mail_reason"])}</th>{ai_reason_header}</tr></thead>'
    )
    return f"<table>{header}<tbody>{''.join(rows)}</tbody></table>"


def examples_for(classified, key, value, limit=4):
    items = []
    seen = set()
    for item in classified:
        email = item["sender_email"]
        if item[key] == value and email and email not in seen:
            items.append(item)
            seen.add(email)
        if len(items) >= limit:
            break
    return items


def canonical_issue_key(issue):
    product = (issue["product_model"] or "").lower().replace(" ", "")
    title = (issue["issue_title"] or "").lower()
    category = (issue["issue_category"] or "").lower()
    signature = (issue["issue_signature"] or "").lower()
    text = " ".join([title, category, signature])
    if product in {"gs1000", "gs1000li"} and "balance" in text and "output" in text:
        return "gs1000_balance_output"
    return f"issue_{issue['id']}"


def canonical_issue_title(group):
    if any(canonical_issue_key(issue) == "gs1000_balance_output" for issue in group):
        return "GS1000 - balance output issue"
    return group[0]["issue_title"]


def detect_model_mentions(rows):
    model_aliases = [
        "GS1000", "GS1000Li", "GE300", "GE1000", "GE150 Pro", "GE150Pro", "GE150 MAX",
        "GE150", "GE200", "GE250", "GE100", "Prime P2", "Prime 2", "P2", "Prime M2",
        "Prime P1", "F15i Li", "F15i", "F40i", "GL200", "GL100", "PE100", "LoFi Machine",
        "SD 75", "SD75",
    ]
    counts = Counter()
    for row in rows:
        text = ((row["subject"] or "") + " " + (row["body"] or "")[:700]).lower().replace("-", " ")
        for model in model_aliases:
            pattern = re.escape(model.lower()).replace(r"\ ", r"\s*")
            if re.search(pattern, text):
                counts[model] += 1
    return counts


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    emails = cur.execute("SELECT * FROM emails ORDER BY received_at DESC").fetchall()

    classified = []
    corrections = []  # 记录被纠正的邮件
    for row in emails:
        item = dict(row)
        item["sender_email"] = extract_email(item.get("sender"))
        display_product, product_inferred = infer_product(row)
        item["display_product"] = display_product
        item["product_inferred"] = product_inferred
        db_issue_category = row["issue_category"] if "issue_category" in row.keys() else None
        if db_issue_category:
            issue_category = db_issue_category
            evidence = row["classification_evidence"] if "classification_evidence" in row.keys() else ""
            reason = f"from database issue_category={db_issue_category}"
        else:
            issue_category, evidence, reason = classify_issue(row)
        item["issue_category"] = issue_category
        item["evidence"] = evidence
        item["issue_reason"] = reason
        mail_category, mail_reason = refine_mail_category(row, issue_category, display_product)
        item["mail_category"] = mail_category
        item["mail_reason"] = mail_reason
        db_reply_category = row["reply_template_category"] if "reply_template_category" in row.keys() else None
        item["reply_template_category"] = db_reply_category or infer_reply_category(item["mail_category"], item["issue_category"])
        classified.append(item)

        # 记录纠偏
        raw_intent = item.get("ai_intent")
        if raw_intent in BUSINESS_INTENTS and mail_category != MAIL_CATEGORY.get(raw_intent):
            corrections.append(item)

    total = len(classified)
    mail_counts = Counter(item["mail_category"] for item in classified)
    issue_counts = Counter(item["issue_category"] for item in classified)
    reply_counts = Counter(item["reply_template_category"] for item in classified)
    product_counts = Counter(item["display_product"] for item in classified)

    support_issues = cur.execute("SELECT * FROM support_issues ORDER BY email_count DESC, id").fetchall()
    empty_product_rows = [
        row for row in emails
        if row["product_model"] is None or not str(row["product_model"]).strip()
    ]
    empty_product_intents = Counter(row["ai_intent"] or "(null)" for row in empty_product_rows)
    empty_product_mentions = detect_model_mentions(empty_product_rows)
    templates = cur.execute(
        "SELECT category, COALESCE(NULLIF(product_model,''), ?) product_model, issue_category, COUNT(*) c "
        "FROM reply_templates WHERE status='active' "
        "GROUP BY category, product_model, issue_category ORDER BY category, c DESC",
        (ZH["general"],),
    ).fetchall()

    template_rows = "".join(
        f"<tr><td>{esc(row['category'])}</td><td>{esc(row['product_model'])}</td>"
        f"<td>{esc(row['issue_category'])}</td><td>{row['c']}</td></tr>"
        for row in templates
    )

    issue_groups = {}
    for issue in support_issues:
        issue_groups.setdefault(canonical_issue_key(issue), []).append(issue)

    issue_sections = []
    for _, group in sorted(
        issue_groups.items(),
        key=lambda item: (-sum(issue["email_count"] or 0 for issue in item[1]), min(issue["id"] for issue in item[1])),
    ):
        if not sum(issue["email_count"] or 0 for issue in group):
            continue
        issue_ids = [issue["id"] for issue in group]
        placeholders = ",".join("?" for _ in issue_ids)
        linked = cur.execute(
            f"SELECT DISTINCT e.* FROM email_issue_links l JOIN emails e ON e.id=l.email_id "
            f"WHERE l.issue_id IN ({placeholders}) ORDER BY e.received_at DESC LIMIT 12",
            issue_ids,
        ).fetchall()
        linked_all = cur.execute(
            f"SELECT DISTINCT e.id, e.sender FROM email_issue_links l JOIN emails e ON e.id=l.email_id "
            f"WHERE l.issue_id IN ({placeholders})",
            issue_ids,
        ).fetchall()
        unique_users = {extract_email(row["sender"]) for row in linked_all if extract_email(row["sender"])}
        unique_emails = {row["id"] for row in linked_all}
        title = canonical_issue_title(group)
        product = group[0]["product_model"]
        category = " / ".join(sorted({issue["issue_category"] for issue in group if issue["issue_category"]}))
        statuses = " / ".join(sorted({issue["status"] for issue in group if issue["status"]}))
        priorities = " / ".join(sorted({issue["priority"] for issue in group if issue["priority"]}))
        original_ids = ", ".join(f"#{issue_id}" for issue_id in issue_ids)
        rows = []
        for email_row in linked:
            _, evidence, _ = classify_issue(email_row)
            display_product, product_inferred = infer_product(email_row)
            product_label = f"{display_product} ({ZH['inferred']})" if product_inferred else display_product
            rows.append(
                f"<tr><td class=\"mono\">{esc(extract_email(email_row['sender']))}</td>"
                f"<td>{esc(clean_text(email_row['received_at'], 60))}</td>"
                f"<td>{esc(clean_text(email_row['subject'], 130))}</td>"
                f"<td>{esc(product_label)}</td>"
                f"<td>{esc(clean_text(evidence, 260))}</td></tr>"
            )
        issue_sections.append(
            f'<div class="section"><h3>{esc(title)} '
            f'<span class="small">({esc(ZH["ids"])}: {esc(original_ids)})</span></h3>'
            f'<p><b>{esc(ZH["product"])}:</b> {esc(product)} &nbsp; '
            f'<b>{esc(ZH["issue_type"])}:</b> {esc(category)} &nbsp; '
            f'<b>{esc(ZH["emails"])}:</b> {len(unique_emails)} &nbsp; '
            f'<b>{esc(ZH["users"])}:</b> {len(unique_users)} &nbsp; '
            f'<b>{esc(ZH["status"])}:</b> {esc(statuses)} &nbsp; '
            f'<b>{esc(ZH["priority"])}:</b> {esc(priorities)}</p>'
            f'<table><thead><tr><th>{esc(ZH["user_email"])}</th><th>{esc(ZH["time"])}</th>'
            f'<th>{esc(ZH["subject"])}</th><th>{esc(ZH["product"])}</th>'
            f'<th>{esc(ZH["evidence"])}</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )

    mail_examples = []
    for category, _ in sorted_counter_items(mail_counts, 8):
        mail_examples.append(
            f'<h3>{esc(category)}</h3>'
            f'{example_table(examples_for(classified, "mail_category", category), show_ai_reason=True)}'
        )

    issue_examples = []
    for category, _ in sorted_counter_items(issue_counts, 8):
        issue_examples.append(
            f'<h3>{esc(category)}</h3>'
            f'{example_table(examples_for(classified, "issue_category", category), show_ai_reason=True)}'
        )

    empty_intent_rows = "".join(
        f"<tr><td>{esc(key)}</td><td>{value}</td><td>{value / len(empty_product_rows):.1%}</td></tr>"
        for key, value in sorted_counter_items(empty_product_intents)
    )
    empty_mention_rows = "".join(
        f"<tr><td>{esc(key)}</td><td>{value}</td><td>{value / len(empty_product_rows):.1%}</td></tr>"
        for key, value in empty_product_mentions.most_common(20)
    )
    unknown_reason_section = (
        f'<section id="unknown-product"><h2>{esc(ZH["unknown_reason"])}</h2>'
        f'<div class="note">{esc(ZH["unknown_reason_note"])}</div>'
        f'<div class="two"><div><h3>{esc(ZH["empty_product_by_intent"])}</h3>'
        f'<table><thead><tr><th>{esc(ZH["mail_type"])}</th><th>{esc(ZH["count"])}</th><th>{esc(ZH["ratio"])}</th></tr></thead>'
        f"<tbody>{empty_intent_rows}</tbody></table></div>"
        f'<div><h3>{esc(ZH["empty_product_mentions"])}</h3>'
        f'<table><thead><tr><th>{esc(ZH["product"])}</th><th>{esc(ZH["count"])}</th><th>{esc(ZH["ratio"])}</th></tr></thead>'
        f"<tbody>{empty_mention_rows}</tbody></table></div></div></section>"
    )

    # 纠正统计
    correction_by_original = Counter(item["ai_intent"] for item in corrections)
    correction_by_corrected = Counter(item["mail_category"] for item in corrections)
    correction_table = ""
    if corrections:
        rows_html = ""
        seen_users = set()
        for item in corrections:
            if item["sender_email"] in seen_users:
                continue
            seen_users.add(item["sender_email"])
            raw_ai = (item.get("ai_reasoning") or "")[:150]
            rows_html += (
                f"<tr>"
                f'<td class="mono">{esc(item["sender_email"])}</td>'
                f'<td>{esc(clean_text(item.get("subject"), 100))}</td>'
                f'<td>{esc(item["display_product"])}</td>'
                f'<td><span class="tag tag-warn">{esc(item.get("ai_intent") or "N/A")}</span></td>'
                f'<td><span class="tag tag-ok">{esc(item["mail_category"])}</span></td>'
                f'<td class="small" style="color:#be123c;max-width:200px;">{esc(raw_ai)}</td>'
                f"</tr>"
            )
        correction_table = (
            f'<section id="corrections"><h2>{esc(ZH["correction_title"])}</h2>'
            f'<div class="note"><b>{esc(ZH["correction_note"])}</b> '
            f'共纠正 <b style="color:#dc2626;">{len(corrections)}</b> 封邮件。</div>'
            f'<div class="grid" style="grid-template-columns:1fr 1fr;">'
            f'<div class="metric" style="border-left:4px solid #dc2626;"><b>{len(corrections)}</b><span>纠正邮件数</span></div>'
            f'<div class="metric" style="border-left:4px solid #d97706;"><b>{len(set(i["sender_email"] for i in corrections))}</b><span>涉及用户数</span></div>'
            f'</div>'
            f'<table><thead><tr>'
            f'<th>{esc(ZH["user_email"])}</th><th>{esc(ZH["subject"])}</th><th>{esc(ZH["product"])}</th>'
            f'<th>{esc(ZH["original_ai"])}</th><th>{esc(ZH["corrected_to"])}</th><th style="color:#be123c;">{esc(ZH["original_reason"])}</th>'
            f'</tr></thead><tbody>{rows_html}</tbody></table></section>'
        )

    # Chart.js 数据
    mail_chart_data = []
    for key, value in sorted_counter_items(mail_counts, 8):
        ck = get_mail_color_key(key)
        mail_chart_data.append({"label": key.split(" / ")[-1], "value": value, "color": MAIL_COLORS.get(ck, "#6b7280")})

    issue_chart_data = []
    for key, value in sorted_counter_items(issue_counts, 8):
        ck = get_issue_color_key(key)
        issue_chart_data.append({"label": key.split(" / ")[-1], "value": value, "color": ISSUE_COLORS.get(ck, "#94a3b8")})

    css = """
:root {
    --bg: #f0f4f8;
    --ink: #1a202c;
    --muted: #718096;
    --line: #e2e8f0;
    --card: #ffffff;
    --head: #0f766e;
    --accent: #2563eb;
    --warn: #dc2626;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--ink); font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "Microsoft YaHei", sans-serif; }

header {
    background: linear-gradient(135deg, #0f4c5c 0%, #1a202c 100%);
    color: white; padding: 32px 40px;
    position: relative; overflow: hidden;
}
header::after {
    content: ''; position: absolute; right: -60px; top: -60px;
    width: 200px; height: 200px; border-radius: 50%;
    background: rgba(255,255,255,0.05);
}
header h1 { font-size: 28px; font-weight: 700; margin-bottom: 6px; }
header .meta { color: rgba(255,255,255,0.7); font-size: 13px; }

h2 { font-size: 22px; margin: 36px 0 16px; color: #0f4c5c; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }
h3 { font-size: 16px; margin: 20px 0 10px; color: #2d3748; }

.wrap { max-width: 1400px; margin: 0 auto; padding: 24px 32px 60px; }
.toc { padding: 14px 0; }
.toc a {
    display: inline-block; margin-right: 16px; padding: 6px 14px;
    background: white; border: 1px solid var(--line); border-radius: 20px;
    color: var(--head); text-decoration: none; font-size: 13px; font-weight: 500;
    transition: all 0.2s;
}
.toc a:hover { background: var(--head); color: white; }

.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.three { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }

.metric {
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 18px 20px; transition: transform 0.2s;
}
.metric:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.metric b { display: block; font-size: 32px; font-weight: 800; color: var(--head); }
.metric span { color: var(--muted); font-size: 13px; }

table {
    width: 100%; border-collapse: collapse; background: white;
    border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
    margin: 10px 0 20px; font-size: 13px;
}
th, td { border-bottom: 1px solid var(--line); padding: 9px 12px; text-align: left; vertical-align: top; }
th { background: #f7fafc; color: #2d3748; font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
tr:last-child td { border-bottom: 0; }
tr:hover { background: #f7fafc; }

.small { font-size: 11px; color: var(--muted); line-height: 1.4; }
.mono { font-family: "SF Mono", Consolas, Monaco, monospace; font-size: 12px; }
.nowrap { white-space: nowrap; }

.tag {
    display: inline-block; border: 1px solid var(--line); border-radius: 6px;
    padding: 2px 8px; background: #f8fafc; margin: 1px 2px 1px 0;
    font-size: 11px; line-height: 1.5;
}
.tag-warn { border-color: #fca5a5; background: #fef2f2; color: #dc2626; }
.tag-ok { border-color: #86efac; background: #f0fdf4; color: #16a34a; }

.section { background: white; border: 1px solid var(--line); border-radius: 10px; padding: 20px; margin: 16px 0; }
.evidence { color: #243b53; font-size: 12px; }
.note {
    background: linear-gradient(135deg, #fffbeb 0%, #fff7ed 100%);
    border: 1px solid #fde68a; border-radius: 10px; padding: 14px 18px;
    margin: 16px 0; font-size: 13px; line-height: 1.6;
}

/* Chart containers */
.chart-box {
    background: white; border: 1px solid var(--line); border-radius: 10px;
    padding: 20px; margin: 10px 0;
}
.chart-box canvas { max-height: 300px; }

@media (max-width: 900px) {
    .grid, .two, .three { grid-template-columns: 1fr; }
    header { padding: 24px; }
    .wrap { padding: 16px; }
}
"""

    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{esc(ZH['title'])}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>{css}</style></head>
<body>
<header>
    <h1>{esc(ZH['title'])}</h1>
    <div class="meta">{esc(ZH['generated'])}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {esc(ZH['database'])}: {esc(DB_PATH.resolve())}</div>
</header>
<div class="wrap">
<div class="toc">
    <a href="#summary">{esc(ZH['overview'])}</a>
    <a href="#corrections">{esc(ZH['correction_title'])}</a>
    <a href="#mail">{esc(ZH['mail_type'])}</a>
    <a href="#issue">{esc(ZH['issue_type'])}</a>
    <a href="#templates">{esc(ZH['templates'])}</a>
    <a href="#unknown-product">{esc(ZH['unknown_reason'])}</a>
    <a href="#linked">{esc(ZH['linked_issues'])}</a>
    <a href="#examples">{esc(ZH['examples'])}</a>
</div>

<section id="summary"><h2>{esc(ZH['overview'])}</h2>
<div class="grid">
    <div class="metric"><b>{total}</b><span>{esc(ZH['email_total'])}</span></div>
    <div class="metric"><b>{len(set(item['sender_email'] for item in classified if item['sender_email']))}</b><span>{esc(ZH['email_users'])}</span></div>
    <div class="metric"><b>{len(support_issues)}</b><span>{esc(ZH['issue_pool'])}</span></div>
    <div class="metric"><b>{sum(1 for _ in templates)}</b><span>{esc(ZH['active_templates'])}</span></div>
</div>
<div class="note"><b>{esc(ZH['note_title'])}:</b> {esc(ZH['note'])}</div>

<div class="three">
    <div class="chart-box"><canvas id="mailChart"></canvas></div>
    <div class="chart-box"><canvas id="issueChart"></canvas></div>
    <div class="chart-box"><canvas id="replyChart"></canvas></div>
</div>
</section>

{correction_table}

<section id="mail"><h2>{esc(ZH['mail_type'])}</h2>{count_table(mail_counts, ZH['mail_type'], total, 20)}</section>
<section id="issue"><h2>{esc(ZH['issue_type'])}</h2>{count_table(issue_counts, ZH['product_issue_distribution'], total, 20)}</section>

<section id="templates"><h2>{esc(ZH['templates'])}</h2>
{count_table(reply_counts, ZH['reply_method_distribution'], total, 20)}
<h3>{esc(ZH['existing_templates'])}</h3>
<table><thead><tr><th>{esc(ZH['template_group'])}</th><th>{esc(ZH['product'])}</th><th>{esc(ZH['subtype'])}</th><th>{esc(ZH['count'])}</th></tr></thead><tbody>{template_rows}</tbody></table>
</section>

{unknown_reason_section}

<section id="linked"><h2>{esc(ZH['linked_issues'])}</h2>{''.join(issue_sections) or esc(ZH['none'])}</section>

<section id="examples"><h2>{esc(ZH['examples'])}</h2>
<h3>{esc(ZH['mail_examples'])}</h3>{''.join(mail_examples)}
<h3>{esc(ZH['issue_examples'])}</h3>{''.join(issue_examples)}
</section>
</div>

<script>
// 邮件类型饼图
new Chart(document.getElementById('mailChart'), {{
    type: 'doughnut',
    data: {{
        labels: {json.dumps([d['label'] for d in mail_chart_data])},
        datasets: [{{
            data: {json.dumps([d['value'] for d in mail_chart_data])},
            backgroundColor: {json.dumps([d['color'] for d in mail_chart_data])},
            borderWidth: 2, borderColor: '#fff'
        }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: true,
        plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }} }}
    }}
}});

// 问题类型饼图
new Chart(document.getElementById('issueChart'), {{
    type: 'doughnut',
    data: {{
        labels: {json.dumps([d['label'] for d in issue_chart_data])},
        datasets: [{{
            data: {json.dumps([d['value'] for d in issue_chart_data])},
            backgroundColor: {json.dumps([d['color'] for d in issue_chart_data])},
            borderWidth: 2, borderColor: '#fff'
        }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: true,
        plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }} }}
    }}
}});

// 回复方式饼图
var replyLabels = {json.dumps([d[0].split(' / ')[-1] for d in sorted_counter_items(reply_counts, 8)])};
var replyValues = {json.dumps([d[1] for d in sorted_counter_items(reply_counts, 8)])};
var replyColors = ['#2563eb','#718096','#7c3aed','#059669','#d97706','#0891b2','#dc2626','#9ca3af'];
new Chart(document.getElementById('replyChart'), {{
    type: 'doughnut',
    data: {{
        labels: replyLabels,
        datasets: [{{
            data: replyValues,
            backgroundColor: replyColors.slice(0, replyLabels.length),
            borderWidth: 2, borderColor: '#fff'
        }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: true,
        plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, boxWidth: 12 }} }} }}
    }}
}});
</script>
</body></html>"""

    OUT_PATH.write_text(html_doc, encoding="utf-8")
    conn.close()
    print(f"Generated: {OUT_PATH.resolve()}")
    print(f"Total: {total} emails, {len(corrections)} corrections")


if __name__ == "__main__":
    main()
