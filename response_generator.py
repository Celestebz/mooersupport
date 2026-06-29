import os
import logging
import re
import json
from datetime import datetime

# Import pdf_reader module directly
from pdf_reader import get_pdf_path, extract_text_from_pdf, search_keywords_in_pdf

# Import external data fetcher
from external_data_fetcher import ExternalDataFetcher

# Import AI Handler
from ai_handler import AIHandler
from issue_facts import extract_issue_facts

# Import part price database
from part_price_db import get_part_price, get_all_prices_for_model

# Define Tools Schema
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_product_manual",
            "description": "Search for specific technical information in the product manual PDF.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_model": {
                        "type": "string",
                        "description": "The specific model name of the MOOER product (e.g., 'GE150', 'Prime P1')."
                    },
                    "query": {
                        "type": "string",
                        "description": "The specific topic or keywords to search for in the manual (e.g., 'bluetooth connection', 'power supply', 'reset factory')."
                    }
                },
                "required": ["product_model", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_firmware_update_guide",
            "description": "Get specific instructions for updating the firmware of a product. Returns instructions for Mobile App or PC Studio based on the model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_model": {
                        "type": "string",
                        "description": "The product model name."
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["mobile", "pc", "auto"],
                        "description": "The preferred platform for update if applicable. Use 'auto' to let the system decide based on model capabilities."
                    }
                },
                "required": ["product_model"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_official_downloads",
            "description": "Get the official navigation path for owner's manuals or firmware/software packages. Use the correct download_type to avoid mixing manual downloads with firmware/software downloads.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_model": {
                        "type": "string",
                        "description": "The product model name."
                    },
                    "download_type": {
                        "type": "string",
                        "enum": ["auto", "owners_manual", "firmware_software"],
                        "description": "Use 'owners_manual' when the customer asks for a manual/user guide. Use 'firmware_software' for firmware, editor, driver, app, or installer packages. Use 'auto' only if the request is ambiguous."
                    }
                },
                "required": ["product_model"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Flag this email for manual review by a human agent. Use this when the user is very angry, the issue is complex/unusual, or it involves sensitive topics (refunds, legal).",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "The reason why this email needs human attention."
                    }
                },
                "required": ["reason"]
            }
        }
    }
]

class ResponseGenerator:
    """Generates email responses using templates and product manuals"""
    
    def __init__(self, templates_path, pdf_reader_path, product_manuals_path):
        """Initialize ResponseGenerator"""
        self.logger = logging.getLogger(__name__)
        self.pdf_reader_path = pdf_reader_path
        self.product_manuals_path = product_manuals_path
        
        # 初始化 AI Handler
        self.ai_handler = AIHandler()

        # PDF 文本缓存
        self.pdf_text_cache = {}
        self.last_knowledge_citations = []
        self.last_human_review_required = False
        self.last_human_review_reason = ""
        self.last_human_review_label = ""

        # intent → category 映射（用于数据库查询）
        self.intent_to_category = {
            "Technical Support": "Technical/Usage Question",
            "Firmware Update": "Firmware Update",
            "Warranty/Repair": "Repair/Warranty",
            "Sales/Stock": "Parts/Accessories Purchase",
            "Spam": None,
            "Gratitude": "Feedback/Suggestion",
            "Partnership/Collaboration": None,
            "Press/Media": None,
            "Dealer Inquiry": None,
            "Amazon Purchase Issues": "Amazon Purchase Issues",
            "Registration Unbinding": "Registration Unbinding",
            "Software Installation": "Software Installation",
            "Parts/Accessories Purchase": "Parts/Accessories Purchase",
            "Complaint/Frustration": "Complaint/Frustration",
            "Feedback/Suggestion": "Feedback/Suggestion",
            "Other": "Technical/Usage Question",
        }

        # category → issue_category 默认回退映射
        # 当数据库中 category 下有多条 issue_category 时，按此优先级选择
        self.category_issue_fallback = {
            "Repair/Warranty": "Dealer Referral",
            "Amazon Purchase Issues": "Within 30 Days",
            "Software Installation": "Driver Installation",
            "Firmware Update": "Generic Firmware",
            "Registration Unbinding": "Request Info",
            "Parts/Accessories Purchase": "Generic Part Purchase",
            "Complaint/Frustration": "General Complaint",
            "Feedback/Suggestion": "General Feedback",
            "Technical/Usage Question": "USB Connection",
        }
        
        # Initialize external data fetcher
        self.external_fetcher = ExternalDataFetcher()

        # Load warranty policy
        self.warranty_policy = self._load_warranty_policy()

        # Load distributor info
        self.distributor_info = self._load_distributor_info()

        # 官方产品清单（标准格式）- 用于标准化比对
        self.OFFICIAL_PRODUCTS = {
            # GE 系列
            "GE100", "GE100 Pro", "GE100 Pro Li",
            "GE150", "GE150 Pro", "GE150 Plus", "GE150 MAX",
            "GE200", "GE200 Pro", "GE200 Plus", "GE200 PLUS Li",
            "GE250", "GE300", "GE300 Lite", "GE1000",
            # Prime 系列
            "Prime P1", "Prime P2", "Prime M1", "Prime M2",
            # GL 系列
            "GL100", "GL200",
            # GS 系列
            "GS1000", "GS1000Li",
            # SD 系列
            "SD10i", "SD30i", "SD50A",
            # F 系列 (Li = 锂电池版本)
            "F15i", "F15i Li", "F40i", "F40i Li",
            # F 踏板
            "F4",
            # GTRS 系列
            "GTRS", "GTRS 800", "GTRS 900",
            # X 系列 (Drummer/Looper)
            "DRUMMER X2", "Groove Loop X2", "X2", "Loopation",
            # 效果器系列
            "Radar", "Red Truck", "Black Truck", "Preamp Live",
            "Ocean Machine", "Ocean Machine II",
            "TONE CAPTURE", "PE100", "Pitch Step", "Free Step",
            # 其他
            "C4 AirSwitch", "CAB X2", "HORNET 15i", "HORNET 30",
            "AIR P05", "Audiofile", "Harmonier",
            # 小型效果器
            "Baby Tuner", "Baby Bomb 30", "Micro Drummer II", "Micro Looper II",
            "Acoustikar", "Mod Factory", "Reverie Chorus", "e-Lady", "R7"
        }

        # 构建查找表：移除空格后的官方产品 -> 标准名称
        self._build_lookup_table()

    def _build_lookup_table(self):
        """构建查找表：key（无空格+大写）-> value（标准名称）"""
        self.product_lookup = {}
        for product in self.OFFICIAL_PRODUCTS:
            key = re.sub(r'\s+', '', product).upper()
            self.product_lookup[key] = product

    def _normalize_product_model(self, product_model):
        """
        标准化产品型号
        用户输入: "GE150Pro", "GE 100", "GE150 Pro"
        输出: "GE150 Pro", "GE100", "GE150 Pro"
        """
        if not product_model or product_model == "Unknown":
            return None

        # Step 1: 预处理 - 移除所有空格、转大写
        cleaned = re.sub(r'\s+', '', product_model).upper()

        # Step 2: 精确匹配查找表
        if cleaned in self.product_lookup:
            return self.product_lookup[cleaned]

        # Step 3: 常见错误纠正
        corrections = {
            # GE 系列常见错误
            'GE001': 'GE100',       # 打字错误
            'GE-100': 'GE100',
            'GE00100': 'GE100',
            'GE150PRO': 'GE150 Pro',
            'GE150PLUS': 'GE150 Plus',
            'GE150MAX': 'GE150 MAX',
            'GE200PRO': 'GE200 Pro',
            'GE200PLUSLI': 'GE200 PLUS Li',
            'GE200PLUS': 'GE200 Plus',
            'GE300LITE': 'GE300 Lite',
            # Prime 系列
            'PRIMEP1': 'Prime P1',
            'PRIMEP2': 'Prime P2',
            'PRIMEM1': 'Prime M1',
            'PRIMEM2': 'Prime M2',
            'P1PRIME': 'Prime P1',
            'P2PRIME': 'Prime P2',
            # P1/P2/M1/M2 缩略 → 全名（先查 official list 会匹配）
            'P1': 'Prime P1',
            'P2': 'Prime P2',
            'M1': 'Prime M1',
            'M2': 'Prime M2',
            'S1': 'Prime S1',
            # GS 系列
            'GS100': 'GS1000',      # 少写一个0
            # F 系列
            'F15I': 'F15i',
            'F15ILI': 'F15i Li',
            'F40I': 'F40i',
            'F40ILI': 'F40i Li',
            'F15LI': 'F15i Li',     # F15 Li -> F15i Li
            # GL 系列
            'GL001': 'GL100',
            # X2 系列
            'X2DRUMMER': 'DRUMMER X2',
            'DRUMMERMACHINE': 'DRUMMER X2',
            'DRUM/LOOPER': 'DRUMMER X2',
            # GTRS
            'GTRSS800': 'GTRS 800',
            'GTRSS900': 'GTRS 900',
            # Tone/Capture
            'TONECAPTUREGTR': 'TONE CAPTURE',
            # iAMP
            'IAMP': 'iAMP',
            'IAMPAI': 'iAMP',
            # Preamp
            'PREAMPMODELX': 'Preamp Live',
            'LIVEPREAMP': 'Preamp Live',
            # Micro
            'MICRODRUMMERII': 'Micro Drummer II',
            'MICROLOOPERII': 'Micro Looper II',
            # Baby
            'BABYTUNER': 'Baby Tuner',
            'BABYBOMB30': 'Baby Bomb 30',
            # Others
            'ACOUSTIKAR': 'Acoustikar',
            'MODFACTORY': 'Mod Factory',
            'REVERIECHORUS': 'Reverie Chorus',
            'E-LADY': 'e-Lady',
            # 特殊变体
            'PUREROCTAVE': 'Purer Octave',
            'X2DRUMLOOPER': 'DRUMMER X2',
            'F15ILIGOLD': 'F15i Li',
            'SD50AC4AIRS': None,    # 组合产品，无法标准化
            'DRUMMACHINE': 'DRUMMER X2',
            'DRUMMACHINEX2': 'DRUMMER X2',
            'MOOERSTUDIO': None,    # 软件，不是产品
            'F40LI': 'F40i Li',
            'F4WHITEPRIMEP1': None, # 组合产品，包含 F4 和 P1
        }

        if cleaned in corrections:
            return corrections[cleaned]

        # Step 4: 部分匹配（包含关系）
        # 例如 "GE150Pro Max" -> 需要提取主要产品
        for key, official in self.product_lookup.items():
            if key in cleaned or cleaned in key:
                # 避免过度匹配，比如 "GE150" 不应该匹配 "GE150 PRO"
                if len(key) >= len(cleaned) - 2:  # 允许少量差异
                    return official

        # Step 5: 无法识别
        self.logger.warning(f"无法标准化产品型号: {product_model}")
        return None

    def _load_warranty_policy(self):
        """加载 MOOER 保修政策知识文件"""
        policy_path = os.path.join(os.path.dirname(__file__), 'warranty_policy.txt')
        try:
            if os.path.exists(policy_path):
                with open(policy_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            self.logger.warning(f"Failed to load warranty policy: {e}")
        return ""

    def _load_distributor_info(self):
        """加载 MOOER 分销商信息"""
        dist_path = os.path.join(os.path.dirname(__file__), 'distributor_info.txt')
        try:
            if os.path.exists(dist_path):
                with open(dist_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            self.logger.warning(f"Failed to load distributor info: {e}")
        return ""

    def _get_db_template(self, category, product_model=None, preferred_issue_category=None):
        """查询 DB 中是否有匹配的回复模板。返回模板文本或 None。"""
        try:
            from database import DatabaseHandler
            db = DatabaseHandler()

            # 第一步：按 category + product_model 精确查询
            if product_model:
                exact_rows = db.get_reply_templates_by_category(
                    category, product_model=product_model, language='en'
                )
                if exact_rows:
                    self.logger.info(
                        f"Using DB template #{exact_rows[0]['id']} for {category}/{product_model}"
                    )
                    return exact_rows[0]['body']

            # 第二步：回退到仅按 category 查询（包含通用和产品专属模板）
            all_rows = db.get_reply_templates_by_category(
                category, product_model=None, language='en'
            )
            if all_rows:
                # 优先选通用模板（product_model 为空），按 issue_category 优先级
                generic = [r for r in all_rows if not (r.get('product_model') or '').strip()]
                if generic:
                    fallback_issue = preferred_issue_category or self.category_issue_fallback.get(category)
                    if fallback_issue:
                        preferred = [r for r in generic
                                     if (r.get('issue_category') or '').strip() == fallback_issue]
                        if preferred:
                            self.logger.info(
                                f"Using preferred DB template #{preferred[0]['id']} for {category} (issue={fallback_issue})"
                            )
                            return preferred[0]['body']
                    self.logger.info(
                        f"Using generic DB template #{generic[0]['id']} for {category}"
                    )
                    return generic[0]['body']
                # 无通用模板时取第一条
                self.logger.info(
                    f"Using DB template #{all_rows[0]['id']} for {category}"
                )
                return all_rows[0]['body']
        except Exception as e:
            self.logger.debug(f"DB template lookup skipped: {e}")
        return None

    def _amazon_purchase_template_issue(self, email_content, attachments=None):
        """Return the preferred Amazon template subtype when the email contains clear Amazon purchase evidence."""
        text = email_content or ""
        lower = text.lower()
        attachment_names = " ".join(
            str(item.get("filename", "")) if isinstance(item, dict) else str(item)
            for item in (attachments or [])
        ).lower()
        has_amazon_text = "amazon" in lower or "amazon" in attachment_names
        has_amazon_order_id = bool(re.search(r'\b\d{3}-\d{7}-\d{7}\b', text))

        # Do not treat generic files like "Order Details.pdf" as Amazon proof.
        # They only prove there is an order document, not which platform it came from.
        if not (has_amazon_text or has_amazon_order_id):
            return None

        has_purchase_date = bool(re.search(
            r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|'
            r'sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b',
            text,
            re.IGNORECASE,
        ))
        if not (has_amazon_order_id or has_purchase_date):
            return None

        purchase_date = None
        date_match = re.search(
            r'\b(?:purchased|ordered|bought|order(?:ed)?\s+on|purchase(?:d)?\s+on)?\s*'
            r'((?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|'
            r'sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b',
            text,
            re.IGNORECASE,
        )
        if date_match:
            raw_date = date_match.group(1).replace(',', '')
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    purchase_date = datetime.strptime(raw_date, fmt)
                    break
                except ValueError:
                    continue

        if purchase_date:
            days_since_purchase = (datetime.now() - purchase_date).days
            if days_since_purchase <= 30:
                return "Within 30 Days"
            if days_since_purchase <= 365:
                return "Out of Amazon Window"
            return "Out of Warranty"

        return "Out of Amazon Window"

    def _record_knowledge_citation(self, citation):
        """Record a knowledge source used while generating the current draft."""
        if not citation:
            return
        normalized = {
            "knowledge_type": citation.get("knowledge_type") or "",
            "title": citation.get("title") or "",
            "source": citation.get("source") or "",
            "section": citation.get("section") or "",
            "chunk_id": citation.get("chunk_id"),
            "excerpt": (citation.get("excerpt") or "").strip(),
        }
        key = (
            normalized["knowledge_type"],
            normalized["title"],
            normalized["source"],
            normalized["section"],
            normalized["chunk_id"],
        )
        for existing in self.last_knowledge_citations:
            existing_key = (
                existing.get("knowledge_type"),
                existing.get("title"),
                existing.get("source"),
                existing.get("section"),
                existing.get("chunk_id"),
            )
            if existing_key == key:
                return
        if len(self.last_knowledge_citations) >= 8:
            return
        self.last_knowledge_citations.append(normalized)
    
    def search_product_manual(self, product_model, query):
        """Tool: Search for information in product manual"""
        
        # Prepare keywords for search
        # Keep short words if they look like technical terms (uppercase, digits)
        keywords = []
        for w in query.split():
            clean_w = w.strip()
            # Keep if length > 2 OR if it's a short technical term like "PC", "9V", "EQ"
            if len(clean_w) > 2 or clean_w.isupper() or any(c.isdigit() for c in clean_w):
                keywords.append(clean_w)
        
        # If no valid keywords found, fall back to original query splitting
        if not keywords:
            keywords = query.split()
            
        self.logger.info(f"Tool called: search_product_manual for {product_model}, query: {query}")
        
        # Get information from manual
        manual_info = self._get_manual_info(product_model, keywords)
        
        if manual_info:
            return f"Found the following information in the {product_model} manual:\n\n{manual_info}"
        else:
            # Distinguish between "Manual not found" and "Keywords not found"
            # Check if manual exists at all
            if not get_pdf_path(product_model, self.product_manuals_path):
                 return (
                     f"KNOWLEDGE_NOT_FOUND: No manual was found for product '{product_model}'. "
                     "Do not answer from general knowledge. Route this email to human review."
                 )
            
            return (
                f"KNOWLEDGE_NOT_FOUND: I searched the {product_model} manual for keywords {keywords}, "
                "but found no confirmed answer. Do not answer from general knowledge. Route this email to human review."
            )

    def get_firmware_update_guide(self, product_model, platform="auto"):
        """Tool: Get firmware update instructions"""
        self.logger.info(f"Tool called: get_firmware_update_guide for {product_model}, platform: {platform}")
        
        # NOTE: This method is now primarily a wrapper that encourages using the manual search.
        # We removed the hard-coded logic to rely more on AI + Search Manual.
        # However, we keep some basic guidance for common platforms if the manual search fails.
        
        return (
            f"For {product_model}, please refer to the official manual for the exact update procedure. "
            f"{self.search_firmware_software_download(product_model)} "
            f"Owner's manuals are separate: they are found on each product's own page, "
            f"inside that product page's Download section."
        )


    def check_official_downloads(self, product_model, download_type="auto"):
        """Tool: Get official download path from the correct KB layer."""
        normalized_type = (download_type or "auto").strip().lower()
        self.logger.info(
            f"Tool called: check_official_downloads for {product_model}, download_type: {normalized_type}"
        )

        if normalized_type in {"owners_manual", "manual", "user_manual", "owner_manual"}:
            return self.search_product_page_download(product_model)
        if normalized_type in {"firmware_software", "firmware", "software", "driver", "editor", "installer"}:
            return self.search_firmware_software_download(product_model)

        return (
            "The download request is ambiguous, so keep these two official locations separate:\n\n"
            f"OWNER'S MANUAL DOWNLOAD\n{self.search_product_page_download(product_model)}\n\n"
            f"FIRMWARE / SOFTWARE / DRIVER DOWNLOAD\n{self.search_firmware_software_download(product_model)}"
        )

    def search_product_page_download(self, product_model):
        """Read the product_page_download layer for owner's manual download guidance."""
        info = self._get_download_layer_info(
            knowledge_type="product_page_download",
            keywords=["owner", "manual", "product page", "download"],
        )
        if not info:
            info = (
                "Owner's manuals are downloaded from each product's own page on the MOOER official website. "
                "Open the product page and use the Download section on that product page. "
                "Do not use a generic /pages/download URL as a direct owner's manual link."
            )
        return (
            f"For the {product_model} owner's manual: {info}"
        )

    def search_firmware_software_download(self, product_model):
        """Read the firmware_software_download layer for package download guidance."""
        info = self._get_download_layer_info(
            knowledge_type="firmware_software_download",
            keywords=["firmware", "software", "driver", "editor", "installer", "download"],
        )
        if not info:
            info = (
                "Firmware files, editors, drivers, and software installation packages are downloaded from "
                "https://www.mooeraudio.com/companyfile/Downloads-1. Select the package for the exact product model."
            )
        return (
            f"For {product_model} firmware, editor, driver, or software packages: {info}\n"
            "Do not use product-page owner's manual instructions for firmware/software package downloads."
        )

    def _get_download_layer_info(self, knowledge_type, keywords):
        """Fetch official download rules from the requested KB layer only."""
        try:
            from database import DatabaseHandler

            db = DatabaseHandler()
            matches = db.search_knowledge_chunks(
                knowledge_type=knowledge_type,
                keywords=keywords,
                source_kind="official_download_rule",
                limit=2,
            )
            if not matches:
                return ""
            parts = []
            for match in matches:
                content = (match.get("content") or "").strip()
                source_url = match.get("source_url") or ""
                if source_url and source_url not in content:
                    content = f"{content} Official URL: {source_url}"
                self._record_knowledge_citation({
                    "knowledge_type": knowledge_type,
                    "title": match.get("title") or "",
                    "source": source_url or match.get("source_path") or "",
                    "section": match.get("section_title") or "",
                    "chunk_id": match.get("id"),
                    "excerpt": content[:320],
                })
                parts.append(content)
            return "\n".join(parts).strip()
        except Exception as e:
            self.logger.debug(f"Download knowledge lookup skipped: {e}")
            return ""

    def escalate_to_human(self, reason):
        """Tool: Escalate to human agent"""
        self.logger.info(f"Escalating to human: {reason}")
        self.last_human_review_required = True
        self.last_human_review_reason = reason or "AI requested human review"
        self.last_human_review_label = "AI Escalation - Needs Human"
        return "ESCALATION_TRIGGERED: This email has been flagged for human review. Do not generate a reply."

    def search_web(self, product_model, query):
        """Tool: Search the web for additional information when manual doesn't have the answer"""
        self.logger.info(f"Tool called: search_web for {product_model}, query: {query}")

        try:
            results = []

            # Search MOOER official website
            website_info = self.external_fetcher.get_mooer_website_info(product_model)
            if website_info:
                results.append(f"MOOER Official Website:\n{website_info}")

            # Search YouTube
            youtube_results = self.external_fetcher.get_youtube_videos(f"{product_model} {query}", max_results=3)
            if youtube_results:
                yt_text = "YouTube Videos:\n"
                for vid in youtube_results:
                    yt_text += f"- {vid.get('title', 'N/A')}: {vid.get('url', 'N/A')}\n"
                results.append(yt_text)

            # Search Reddit
            reddit_results = self.external_fetcher.get_reddit_discussions(f"{product_model} {query}", max_results=3)
            if reddit_results:
                rd_text = "Reddit Discussions:\n"
                for post in reddit_results:
                    rd_text += f"- {post.get('title', 'N/A')}: {post.get('url', 'N/A')}\n"
                results.append(rd_text)

            if results:
                return "Search results from the web:\n\n" + "\n\n".join(results)
            else:
                return (
                    f"KNOWLEDGE_NOT_FOUND: No confirmed web results were found for {product_model} {query}. "
                    "Do not answer from general knowledge. Route this email to human review."
                )

        except Exception as e:
            self.logger.error(f"Error in search_web: {e}")
            return (
                f"KNOWLEDGE_NOT_FOUND: Web lookup failed: {str(e)}. "
                "Do not answer from general knowledge. Route this email to human review."
            )

    def _format_conversation_context(self, context):
        """Format lightweight thread context for the draft prompt."""
        if not context:
            return ""
        if isinstance(context, str):
            return context.strip()

        try:
            summary = context.get("summary") or ""
            conversation_summary = context.get("conversation_summary") or ""
            customer_need = context.get("customer_need") or ""
            current_stage = context.get("current_stage") or ""
            latest_message_summary = context.get("latest_message_summary") or ""
            customer = context.get("customer_email") or ""
            subject = context.get("normalized_subject") or ""
            linked_issue = context.get("linked_issue") or {}
            timeline_summary = context.get("timeline_summary") or []
            items = context.get("items") or []

            lines = []
            if conversation_summary:
                lines.append(f"Conversation summary: {conversation_summary}")
            if customer_need:
                lines.append(f"Customer current need: {customer_need}")
            if current_stage:
                lines.append(f"Current handling stage: {current_stage}")
            if latest_message_summary:
                lines.append(f"Latest customer message: {latest_message_summary}")
            if summary:
                lines.append(f"Summary: {summary}")
            if customer or subject:
                lines.append(f"Customer/thread: {customer} / {subject}")
            if linked_issue:
                issue_title = linked_issue.get("issue_title") or linked_issue.get("title") or ""
                lines.append(f"Linked issue: #{linked_issue.get('id')} {issue_title}".strip())
                final_template = linked_issue.get("final_reply_template") or ""
                if final_template:
                    lines.append(f"Final reply template for linked issue:\n{final_template[:1200]}")

            if timeline_summary:
                lines.append("Thread timeline summary:")
                for item in timeline_summary[-6:]:
                    lines.append(
                        "- {date} | {stage} | {product} | {intent} | {summary}".format(
                            date=str(item.get("received_at") or "")[:19],
                            stage=item.get("step_label") or item.get("status") or "",
                            product=item.get("product_model") or "",
                            intent=item.get("ai_intent") or "",
                            summary=re.sub(r'\s+', ' ', item.get("summary") or "").strip(),
                        )
                    )

            if items:
                lines.append("Timeline evidence:")
                for item in items[-10:]:
                    snippet = re.sub(r'\s+', ' ', item.get("body_snippet") or "").strip()
                    if len(snippet) > 260:
                        snippet = snippet[:260] + "..."
                    lines.append(
                        "- {date} | {status} | {sender} | {subject} | {intent} | {snippet}".format(
                            date=str(item.get("received_at") or "")[:19],
                            status=item.get("status") or "",
                            sender=item.get("sender_email") or item.get("sender") or "",
                            subject=item.get("subject") or "",
                            intent=item.get("ai_intent") or "",
                            snippet=snippet,
                        )
                    )
            return "\n".join(line for line in lines if line).strip()
        except Exception as e:
            self.logger.warning(f"Failed to format conversation context: {e}")
            return ""

    def _iamp_app_reinstall_template(self):
        return (
            "Dear customer,\n\n"
            "Regarding the iAMP connection, it was due to our oversea server data synchronization issue.\n"
            "If you're using an Android mobile phone, we suggest you DELETE the mobile app, and download it again from our official website:\n"
            "https://www.mooeraudio.com/Downloads_xq/8.html\n\n"
            "If you're an iPhone user, simply DELETE the iAMP mobile app, download and reinstall.\n"
            "Make sure you delete it, not remove it (tap and hold the app icon until the \"-\" appears).\n\n"
            "Sorry for the inconvenience. Have a nice day!"
        )

    def _is_iamp_app_version_connection_issue(self, email_info, email_content):
        if (email_info.get("issue_fingerprint") or "") == "app_version_too_low_connection_failure":
            return True
        subject = email_info.get("subject") or ""
        body = email_info.get("body") or email_content or ""
        facts = extract_issue_facts(subject, body, fallback_model=email_info.get("product_model"))
        return facts.get("issue_fingerprint") == "app_version_too_low_connection_failure"

    def _is_a2_nam_architecture_question(self, email_info, email_content):
        subject = email_info.get("subject") or ""
        body = email_info.get("body") or email_content or ""
        text = f"{subject}\n{body}".lower()
        has_a2 = bool(re.search(r'(?<![a-z0-9])a2(?![a-z0-9])', text))
        has_nam = "nam" in text or "neural amp modeler" in text
        has_architecture_or_compatibility_intent = any(
            marker in text
            for marker in (
                "support", "supported", "compatible", "compatibility",
                "convert", "conversion", "converter", "load", "loaded",
                "recognized", "recognised", "not recognize", "not recognised",
                "cannot open", "can't open", "a1", "legacy", "architecture",
                "tone3000", "capture", "captures", "profile", "profiles",
                "future update"
            )
        )
        return has_a2 and has_nam and has_architecture_or_compatibility_intent

    def generate_response(self, email_info, email_content):
        """Generate a response based on email information"""
        self.last_knowledge_citations = []
        self.last_human_review_required = False
        self.last_human_review_reason = ""
        self.last_human_review_label = ""
        try:
            # Map AI intent to template category
            ai_intent = email_info['problem_category']
            category = self.intent_to_category.get(ai_intent, "Technical/Usage Question")
            preferred_issue_category = None
            amazon_issue_category = self._amazon_purchase_template_issue(
                email_content,
                attachments=email_info.get("attachments") or [],
            )
            if amazon_issue_category and category in {"Repair/Warranty", "Technical/Usage Question", "Amazon Purchase Issues"}:
                self.logger.info(
                    "Amazon purchase evidence detected; using Amazon Purchase Issues template (%s)",
                    amazon_issue_category,
                )
                category = "Amazon Purchase Issues"
                preferred_issue_category = amazon_issue_category

            # Get product model and normalize to official naming
            raw_product_model = email_info.get('product_model', 'Unknown')
            product_model = self._normalize_product_model(raw_product_model)

            # Log if model was normalized
            if product_model != raw_product_model:
                self.logger.info(f"Product model normalized: '{raw_product_model}' -> '{product_model}'")

            if self._is_iamp_app_version_connection_issue(email_info, email_content):
                self.logger.info("Using fixed iAMP app reinstall template for version/connection issue")
                self._record_knowledge_citation({
                    "knowledge_type": "known_solution_reply",
                    "title": "iAMP app version/connection issue",
                    "source": "response_generator.py",
                    "section": "iAMP fixed reply template",
                    "chunk_id": None,
                    "excerpt": "iAMP app reinstall guidance for overseas server data synchronization issue.",
                })
                return self._iamp_app_reinstall_template()

            if self._is_a2_nam_architecture_question(email_info, email_content):
                template_content = self._get_db_template(
                    "Technical/Usage Question",
                    product_model=None,
                    preferred_issue_category="A2 NAM Architecture Compatibility",
                )
                if template_content:
                    self.logger.info("Using DB template for A2 NAM architecture compatibility question")
                    self._record_knowledge_citation({
                        "knowledge_type": "known_solution_reply",
                        "title": "A2 NAM architecture compatibility template",
                        "source": "reply_templates",
                        "section": "A2 NAM Architecture Compatibility",
                        "chunk_id": None,
                        "excerpt": "A2 is the newer Neural Amp Modeler architecture; use A1 Legacy if current MOOER tools only support A1.",
                    })
                    return template_content

            # Prepare context for AI — 统一从数据库查询模板
            template_content = ""
            if category:
                template_content = self._get_db_template(
                    category,
                    product_model,
                    preferred_issue_category=preferred_issue_category,
                ) or ""
            
            # --- 查询配件价格 ---
            part_price_info = None
            # 检测是否在询问配件价格 (Sales/Stock intent 或包含价格关键词)
            is_price_inquiry = False
            part_name = None
            keywords = email_info.get("keywords", [])
            email_text = email_content.lower() if email_content else ""

            price_keywords = ["price", "cost", "报价", "价格", "buy", "purchase", "order",
                            "how much", "dollar", "usd", "欧元", "英镑", "替换", "配件",
                            "spare", "part", "replacement", "accessory", "screen", "屏幕",
                            "repair", "维修", "lcd", "backlight", "背光", "display", "battery",
                            "电池", "broken", "坏了", "damaged", "损坏"]

            # 硬件配件词（不依赖价格关键词，Technical Support 也触发）
            hardware_part_keywords = ["screen", "屏幕", "lcd", "backlight", "背光", "display",
                                      "battery", "电池", "adapter", "电源", "充电"]

            if ai_intent == "Sales/Stock" or any(kw.lower() in email_text for kw in price_keywords):
                is_price_inquiry = True
                # 尝试获取产品型号和配件名称
                # 先从 keywords 提取
                for kw in keywords:
                    if any(p in kw.lower() for p in ["adapter", "电源", "cable", "线", "switch", "开关",
                                                      "foot", "脚踏", "case", "壳", "保护", "USB", "数据线",
                                                      "screen", "屏幕", "lcd", "backlight", "背光", "display",
                                                      "battery", "电池"]):
                        part_name = kw
                        break

                # 如果 keywords 没找到，从邮件正文中扫描硬件配件词
                if not part_name:
                    for hw_kw in hardware_part_keywords:
                        if hw_kw in email_text:
                            part_name = hw_kw
                            break

                if product_model and product_model != "Unknown" and part_name:
                    part_price_info = get_part_price(product_model, part_name)

                # 如果没有从 keywords 找到配件，尝试获取该型号所有配件价格作为参考
                if not part_price_info and product_model and product_model != "Unknown":
                    all_prices = get_all_prices_for_model(product_model)
                    if all_prices:
                        part_price_info = {
                            "all_prices": all_prices,
                            "product_model": product_model,
                            "currency": "USD"
                        }

            # --- AI Generation with Tools ---
            if self.ai_handler.enabled:
                # Debug: log email content length
                content_length = len(email_content) if email_content else 0
                self.logger.info(f"Email content length: {content_length} chars, first 200 chars: {email_content[:200] if email_content else 'EMPTY'}")

                # Fallback: if email_content is too short after cleaning, use original body
                if content_length < 50 and email_info.get('body'):
                    original_body = email_info.get('body', '')
                    self.logger.warning(f"Cleaned content too short ({content_length}), using original body ({len(original_body)} chars)")
                    email_content = f"Subject: {email_info.get('subject', 'No Subject')}\n\n{original_body}"

                conversation_context = self._format_conversation_context(
                    email_info.get("conversation_context") or email_info.get("thread_context")
                )

                ai_context = {
                    "customer_email": email_content,
                    "conversation_context": conversation_context,
                    "product_model": product_model,
                    "issue_category": category,
                    "template_content": template_content,
                    "warranty_info": self.warranty_policy,
                    "distributor_info": self.distributor_info,
                    # Pass additional context from extraction
                    "urgency": email_info.get("urgency", "Medium"),
                    "key_issues": email_info.get("keywords", []),
                    # Pass part price information if available
                    "part_price_info": part_price_info,
                    "is_price_inquiry": is_price_inquiry,
                    "part_name": part_name
                }
                
                # Define tool map
                tool_map = {
                    "search_product_manual": self.search_product_manual,
                    "get_firmware_update_guide": self.get_firmware_update_guide,
                    "check_official_downloads": self.check_official_downloads,
                    "escalate_to_human": self.escalate_to_human,
                }
                
                ai_response = self.ai_handler.generate_email_draft(
                    ai_context, 
                    tools=TOOLS_SCHEMA, 
                    tool_map=tool_map
                )
                
                if ai_response:
                    if self.ai_handler.last_requires_human_review:
                        self.last_human_review_required = True
                        self.last_human_review_reason = (
                            self.ai_handler.last_human_review_reason
                            or "Knowledge base did not contain a confirmed answer"
                        )
                        self.last_human_review_label = (
                            self.ai_handler.last_human_review_label
                            or "Knowledge Gap - Needs Human"
                        )

                    # DEBUG: Log AI response length for troubleshooting
                    self.logger.info(f"AI response length: {len(ai_response)} chars")

                    # DEBUG: Detect product models mentioned in AI response
                    expected_model = product_model
                    detected_models = self._detect_product_models(ai_response)
                    if detected_models:
                        self.logger.info(f"Product models in AI response: {detected_models}")
                        if expected_model and expected_model != "Unknown":
                            # Check if expected model is mentioned (looser matching)
                            expected_mentioned = False
                            expected_upper = expected_model.upper().replace(" ", "").replace("-", "")
                            for m in detected_models:
                                m_upper = m.upper().replace(" ", "").replace("-", "")
                                # Check if either contains the other (e.g., GE150 matches GE150 Plus)
                                if expected_upper in m_upper or m_upper in expected_upper:
                                    expected_mentioned = True
                                    break
                            if not expected_mentioned:
                                self.logger.warning(f"PRODUCT MISMATCH! Expected: {expected_model}, Found in response: {detected_models}")
                                self.logger.warning("This means AI is talking about the WRONG product!")
                    else:
                        self.logger.debug("No product models detected in AI response")

                    # DEBUG: Check for generic "need more info" responses
                    need_info_patterns = [
                        "provide more detail",
                        "provide more information",
                        "need more detail",
                        "need more information",
                        "could you please provide",
                        "please let me know",
                        "need additional information"
                    ]
                    content_lower = ai_response.lower()
                    for pattern in need_info_patterns:
                        if pattern in content_lower:
                            self.logger.warning(f"DETECTED GENERIC RESPONSE from AI - asked for more info (pattern: '{pattern}')")
                            self.logger.warning(f"Full AI response: {ai_response[:300]}...")
                            break

                    if "ESCALATION_TRIGGERED" in ai_response:
                        self.last_human_review_required = True
                        self.last_human_review_reason = self.last_human_review_reason or "AI requested human review"
                        self.last_human_review_label = self.last_human_review_label or "AI Escalation - Needs Human"
                        self.logger.info("Response generation skipped due to escalation.")
                        return None # Or handle escalation logic here

                    self.logger.info("Using AI generated response with tools")
                    return ai_response
            # -----------------------------

            # Return None when AI fails - let email stay unread for retry
            self.logger.warning("AI disabled or failed, returning None to keep email unread for retry")
            self.logger.warning(f"  - AI enabled: {self.ai_handler.enabled}")
            self.logger.warning(f"  - product_model: {product_model}, category: {category}")
            return None

        except Exception as e:
            self.logger.error(f"Error generating response: {e}", exc_info=True)
            self.logger.error(f"  - email subject: {email_info.get('subject', 'Unknown')}")
            self.logger.error(f"  - product_model: {email_info.get('product_model', 'Unknown')}")
            self.logger.error(f"  - problem_category: {email_info.get('problem_category', 'Unknown')}")
            # Return None to keep email unread for retry
            return None
            
    # REMOVED: _customize_template
    # REMOVED: _generate_technical_response_with_info
    # REMOVED: _generate_technical_response
    # (These were the legacy string-concatenation methods that caused the weird formatting)
    
    def _generate_default_response(self, product_model, category):
        """Generate a default response when no specific template matches"""
        # DEBUG: Log when default response is used
        self.logger.warning(f"GENERATING DEFAULT RESPONSE - product_model: {product_model}, category: {category}")
        self.logger.warning("This means AI failed to generate a proper response!")

        # ... (Keep existing default response for safety) ...
        response = "Dear customer,\n\nThank you for contacting MOOER Support.\n\n"
        if product_model:
            response += f"Regarding your inquiry about the {product_model}, "
        else:
            response += "Regarding your inquiry, "
        response += "we have received your message. A support agent will review your case and reply shortly.\n\nBest regards,\nMOOER Support Team"
        return response

    def _detect_product_models(self, text):
        """Detect product models mentioned in text"""
        if not text:
            return []

        # Common Mooer product models (comprehensive list)
        models = [
            # GE series
            "GE150", "GE200", "GE250", "GE300", "GE1000", "GE100",
            "GE150 Plus", "GE150 PRO", "GE150 MAX",
            "GE200 PLUS", "GE200 PLUS Li",
            # Prime series
            "Prime P1", "Prime P2", "Prime M1", "Prime M2",
            "P1", "P2", "M1", "M2",
            # SD series
            "SD10i", "SD30i", "SD50A", "SD50B", "SD75",
            # GTRS
            "GTRS", "GTRS 900", "GTRS 800",
            # Others
            "GWF4", "F15i", "F15", "F40i", "GL100", "GL200",
            "GS1000", "GS1000i", "GS1000li",
            "Hornet", "Groove Loop", "Drummer X2", "Loopation",
            "Preamp Live", "Radar", "Ocean Machine", "Red Truck", "Black Truck",
            "M1", "C4", "AirSwitch", "TONE CAPTURE", "PE100", "PE 100",
            "PCL6 MKII"
        ]

        found_models = []
        text_upper = text.upper()

        for model in models:
            # Check for exact match (word boundary)
            # Handle models with spaces (e.g., "Prime P2")
            model_parts = model.split()
            if len(model_parts) > 1:
                # For multi-word models, check if all parts appear together or separately
                if model.upper() in text_upper:
                    found_models.append(model)
            else:
                # For single-word models, use word boundary
                pattern = r'\b' + re.escape(model) + r'\b'
                if re.search(pattern, text, re.IGNORECASE):
                    found_models.append(model)

        return found_models

    def _get_manual_info(self, product_model, keywords):
        """Get information from product manual using structured KB, with PDF cache fallback."""
        try:
            # Get PDF path using the product model
            pdf_path = get_pdf_path(product_model, self.product_manuals_path)
            if not pdf_path:
                self.logger.warning(f"No manual found for {product_model}")
                return None

            kb_info = self._get_manual_info_from_knowledge_base(
                product_model=product_model,
                pdf_path=pdf_path,
                keywords=keywords,
            )
            if kb_info:
                return kb_info
            
            # Check cache
            if pdf_path in self.pdf_text_cache:
                pdf_text = self.pdf_text_cache[pdf_path]
            else:
                # Extract and cache
                pdf_text = extract_text_from_pdf(pdf_path)
                self.pdf_text_cache[pdf_path] = pdf_text
                
                # Log only on first attempt if failed
                if not pdf_text:
                    self.logger.warning(f"Failed to extract text from {pdf_path}")

            if not pdf_text:
                return None
            
            manual_info = ""
            
            if keywords:
                # Use first 5 keywords for search (increased from 3)
                search_keywords = keywords[:5]
                # Search keywords in the PDF text with larger context
                results = search_keywords_in_pdf(pdf_text, search_keywords, context_lines=15) # Increased context lines
                
                if results:
                    # Extract relevant information from search results
                    for keyword, matches in results.items():
                        for match in matches[:4]:  # Increased matches per keyword from 2 to 4
                            # Filter out any remaining special characters but KEEP SPACES
                            filtered_context = ''.join(char for char in match['context'] if char.isprintable() or char in '\n\t\r\f ')
                            manual_info += f"Regarding '{keyword}':\n{filtered_context.strip()}\n\n"
                    # Limit to 2000 characters (Increased from 500)
                    return manual_info.strip()[:2000]
            else:
                # If no keywords, return the first 2000 characters of extracted text
                # Filter out any remaining special characters but KEEP SPACES
                filtered_pdf_text = ''.join(char for char in pdf_text if char.isprintable() or char in '\n\t\r\f ')
                return filtered_pdf_text[:2000]
            
            self.logger.info(f"No relevant information found for {product_model} with keywords {keywords}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting manual info: {e}")
            return None

    def _get_manual_info_from_knowledge_base(self, product_model, pdf_path, keywords):
        """Search pre-indexed knowledge_chunks for the exact manual file."""
        try:
            from database import DatabaseHandler

            db = DatabaseHandler()
            rel_path = os.path.relpath(pdf_path, os.getcwd())
            matches = db.search_manual_chunks(
                source_path=rel_path,
                product_model=product_model,
                keywords=keywords[:5] if keywords else [],
                limit=4,
            )
            if not matches:
                return None

            parts = []
            for match in matches:
                content = self._manual_keyword_excerpt(match.get('content') or '', keywords)
                content = ''.join(
                    char for char in content
                    if char.isprintable() or char in '\n\t\r\f '
                ).strip()
                source = match.get('source_path') or rel_path
                section = match.get('section_title') or f"Chunk {match.get('id')}"
                self._record_knowledge_citation({
                    "knowledge_type": "product_manual",
                    "title": match.get("title") or f"{product_model} owner's manual",
                    "source": source,
                    "section": section,
                    "chunk_id": match.get("id"),
                    "excerpt": content[:320],
                })
                parts.append(
                    f"Source: {source}\nSection: {section}\n{content}"
                )

            return "\n\n".join(parts).strip()[:2400]
        except Exception as e:
            self.logger.debug(f"Knowledge base manual search skipped: {e}")
            return None

    def _manual_keyword_excerpt(self, content, keywords, max_chars=900):
        """Return a compact excerpt around the first matching keyword."""
        text = content or ""
        if not text:
            return ""

        lowered = text.lower()
        hit = -1
        for keyword in keywords or []:
            key = str(keyword).strip().lower()
            if not key:
                continue
            pos = lowered.find(key)
            if pos >= 0 and (hit < 0 or pos < hit):
                hit = pos

        if hit < 0:
            return text[:max_chars].rstrip() + ("..." if len(text) > max_chars else "")

        start = max(0, hit - max_chars // 2)
        end = min(len(text), hit + max_chars // 2)

        # Prefer paragraph/line boundaries when they are close enough.
        boundary_start = text.rfind("\n\n", 0, hit)
        if boundary_start >= 0 and hit - boundary_start < max_chars // 2:
            start = boundary_start + 2
        boundary_end = text.find("\n\n", hit)
        if boundary_end >= 0 and boundary_end - hit < max_chars // 2:
            end = boundary_end

        if end - start < min(500, max_chars) and end < len(text):
            end = min(len(text), start + max_chars)

        excerpt = text[start:end].strip()
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(text):
            excerpt = excerpt + "..."
        return excerpt
    
    def _generate_price_inquiry_response(self, product_model):
        """Generate a response for price inquiries"""
        response = f"""Dear customer,

Thank you for your interest in our products! Regarding pricing information for the {product_model or 'requested item'}, please contact your local authorized MOOER dealer or check our official website for the most up-to-date pricing.

Alternatively, you can find our products on major online retailers such as Amazon, where pricing is readily available.

If you're looking for replacement parts or accessories, please provide the specific part name or number, and we'll be happy to assist you with pricing and availability.

Thank you and have a nice day!"""
        
        return response
    
    def _generate_default_response(self, product_model, category):
        """Generate a default response when no specific template matches"""
        response = """Dear customer,

Thank you for choosing our products - we truly appreciate your support!

"""
        
        if product_model:
            response += f"Regarding your inquiry about the {product_model}, "
        else:
            response += "Regarding your inquiry, "
        
        response += "we're here to help. Please provide more detailed information about your issue, and we'll be happy to assist you further."
        
        response += "\n\nThank you and have a nice day!"
        
        return response
    
    def format_response(self, recipient, subject, response_body, original_email=None):
        """Format the response as a complete email with original email quoted"""
        # Filter special characters from response body
        filtered_response = ''.join(char for char in response_body if char.isprintable() or char in '\n\t\r\f')
        formatted = filtered_response
        
        # Add quoted original email if provided
        if original_email:
            formatted += "\n\n------------------------------\n\n"
            
            # Add original email headers
            if 'from' in original_email:
                formatted += f"From: {original_email['from']}\n"
            if 'date' in original_email:
                formatted += f"Date: {original_email['date']}\n"
            if 'to' in original_email:
                formatted += f"To: {original_email['to']}\n"
            if 'subject' in original_email:
                formatted += f"Subject: {original_email['subject']}\n"
            
            formatted += "\n"
            
            # Add original email body with quoting
            if 'body' in original_email:
                for line in original_email['body'].split('\n'):
                    if line.strip():
                        # Filter special characters from original email body line
                        filtered_line = ''.join(char for char in line if char.isprintable() or char in '\n\t\r\f')
                        formatted += f"> {filtered_line}\n"
                    else:
                        formatted += f">\n"
        
        return formatted

if __name__ == "__main__":
    # Test the ResponseGenerator
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Set up paths using raw strings to avoid escaping issues
    templates_path = None  # 已迁移至数据库，不再使用文件模板
    pdf_reader_path = r"e:\My Docment\Celeste\客服\pdf_reader.py"
    product_manuals_path = r"e:\My Docment\Celeste\客服\MOOER产品说明书"
    
    # Create ResponseGenerator instance
    generator = ResponseGenerator(templates_path, pdf_reader_path, product_manuals_path)
    
    # Test email info
    test_email_info = {
        "product_model": "GE150",
        "problem_category": "Firmware Update",
        "sentiment": "neutral",
        "keywords": ["firmware", "update", "USB"],
        "subject": "GE150 Firmware Update Issue",
        "body": "I'm having trouble updating the firmware on my GE150. My computer won't recognize it when I connect it via USB."
    }
    
    # Generate response
    response = generator.generate_response(test_email_info, test_email_info["body"])
    
    print("\n=== Generated Response ===")
    print(response)
    
    # Test with technical question
    test_email_info2 = {
        "product_model": "GE1000",
        "problem_category": "Technical/Usage Question",
        "sentiment": "neutral",
        "keywords": ["loop", "station", "delay"],
        "subject": "GE1000 Loop Station Delay",
        "body": "I'm experiencing delay issues with the loop station on my GE1000. When I record a loop, there's a noticeable delay that makes it hard to create tight grooves."
    }
    
    response2 = generator.generate_response(test_email_info2, test_email_info2["body"])
    
    print("\n=== Generated Technical Response ===")
    print(response2)
