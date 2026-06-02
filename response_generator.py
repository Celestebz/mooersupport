import os
import logging
import re
import json

# Import pdf_reader module directly
from pdf_reader import get_pdf_path, extract_text_from_pdf, search_keywords_in_pdf

# Import external data fetcher
from external_data_fetcher import ExternalDataFetcher

# Import AI Handler
from ai_handler import AIHandler

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
            "description": "Get the official URL and navigation path for downloading software, drivers, or firmware.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_model": {
                        "type": "string",
                        "description": "The product model name."
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
        self.templates_path = templates_path
        self.pdf_reader_path = pdf_reader_path
        self.product_manuals_path = product_manuals_path
        
        # Initialize AI Handler
        self.ai_handler = AIHandler()
        
        # Cache for PDF text
        self.pdf_text_cache = {}
        
        # Load email templates
        self.templates = self._load_templates()


        # Map AI intent to template category
        self.intent_to_category = {
            "Technical Support": "Technical/Usage Question",
            "Firmware Update": "Firmware Update",
            "Warranty/Repair": "Repair/Warranty",
            "Sales/Stock": "Price/Stock Inquiry",
            "Spam": "Spam",
            "Gratitude": "Feedback/Suggestion",
            "Partnership/Collaboration": "Other",
            "Press/Media": "Other",
            "Dealer Inquiry": "Other",
            "Amazon Purchase Issues": "Amazon Purchase Issues",
            "Registration Unbinding": "Registration Unbinding",
            "Software Installation": "Software Installation",
            "Parts/Accessories Purchase": "Parts/Accessories Purchase",
            "Complaint/Frustration": "Complaint/Frustration",
            "Feedback/Suggestion": "Feedback/Suggestion",
            "Other": "Technical/Usage Question",
        }

        # Map problem categories to template indices
        self.category_to_template = {
            "Repair/Warranty": 1,  # 客户就产品问题直接联系经销商
            "Amazon Purchase Issues": 2,  # 亚马逊买了东西发现有问题
            "Software Installation": 0,  # 客户一直无法安装软件
            "Firmware Update": 10,  # 固件更新
            "Registration Unbinding": 7,  # 需要解绑 (未提供产品型号 + 序列号/流水号)
            "Technical/Usage Question": None,  # 需要产品手册信息
            "Parts/Accessories Purchase": 6,  # 客户需要购买替换零件
            "Complaint/Frustration": 12,  # 回答顾客投诉
            "Price/Stock Inquiry": 19,  # 配件报价并询问收货信息
            "Feedback/Suggestion": 11,  # 感谢顾客的反馈
            "Spam": None,  # Spam 不需要模板
            "Other": None,  # 其他情况让 AI 智能生成
        }
        
        # Initialize external data fetcher
        self.external_fetcher = ExternalDataFetcher()

        # 官方产品清单（标准格式）- 用于标准化比对
        self.OFFICIAL_PRODUCTS = {
            # GE 系列
            "GE100", "GE150", "GE150 Plus", "GE150 PRO", "GE150 MAX",
            "GE200", "GE200 Pro", "GE200 Plus", "GE200 PLUS Li",
            "GE250", "GE300", "GE300 Lite", "GE1000",
            # Prime 系列
            "P1", "P2", "M1", "M2", "S1",
            # GL 系列
            "GL100", "GL200",
            # GS 系列
            "GS1000",
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
            'GE150PRO': 'GE150 PRO',
            'GE150PLUS': 'GE150 Plus',
            'GE150MAX': 'GE150 MAX',
            'GE200PRO': 'GE200 Pro',
            'GE200PLUSLI': 'GE200 PLUS Li',
            'GE200PLUS': 'GE200 Plus',
            'GE300LITE': 'GE300 Lite',
            # Prime 系列
            'PRIMEP1': 'P1',
            'PRIMEP2': 'P2',
            'PRIMEM1': 'M1',
            'PRIMEM2': 'M2',
            'P1PRIME': 'P1',
            'P2PRIME': 'P2',
            'PRIMES1': 'S1',
            # GS 系列
            'GS100': 'GS1000',      # 少写一个0
            'GS1000LI': 'GS1000',
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

    def _load_templates(self):
        """Load email templates from file"""
        templates = []
        
        try:
            with open(self.templates_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Split templates by the separator
            template_sections = content.split('-------------------------------------------------------------------------')
            
            for section in template_sections:
                if section.strip():
                    # Extract template content
                    lines = section.strip().split('\n')
                    if len(lines) > 1:
                        # The first line is the Chinese description, the rest is the template
                        template = '\n'.join(lines[1:]).strip()
                        if template:
                            templates.append(template)
            
            self.logger.info(f"Loaded {len(templates)} email templates")
            return templates
            
        except Exception as e:
            self.logger.error(f"Failed to load templates: {e}")
            return []
    
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
            if not self.pdf_reader.get_pdf_path(product_model):
                 return f"Error: No manual found for product '{product_model}'. I cannot search for information. Please use general knowledge or escalate."
            
            return f"I searched the {product_model} manual for keywords {keywords}, but found no specific matches. Try using different keywords or synonyms."

    def get_firmware_update_guide(self, product_model, platform="auto"):
        """Tool: Get firmware update instructions"""
        self.logger.info(f"Tool called: get_firmware_update_guide for {product_model}, platform: {platform}")
        
        # NOTE: This method is now primarily a wrapper that encourages using the manual search.
        # We removed the hard-coded logic to rely more on AI + Search Manual.
        # However, we keep some basic guidance for common platforms if the manual search fails.
        
        return f"For {product_model}, please refer to the official manual for specific update instructions. Generally, MOOER products are updated via the MOOER Studio software (PC/Mac) or the Prime/iAMP App (Mobile). Please ensure you have downloaded the correct software version for your specific model from www.mooeraudio.com."


    def check_official_downloads(self, product_model):
        """Tool: Get official download path"""
        return f"Official software and firmware for {product_model} can be downloaded from: www.mooeraudio.com > Support > Downloads. Select 'Computer Audio' or 'Guitar Effects' depending on your product category."

    def escalate_to_human(self, reason):
        """Tool: Escalate to human agent"""
        self.logger.info(f"Escalating to human: {reason}")
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
                return f"No web search results found for {product_model} {query}. Try using the general MOOER knowledge or escalate to human if needed."

        except Exception as e:
            self.logger.error(f"Error in search_web: {e}")
            return f"Web search failed: {str(e)}. Please use general knowledge or escalate to human."

    def generate_response(self, email_info, email_content):
        """Generate a response based on email information"""
        try:
            # Map AI intent to template category
            ai_intent = email_info['problem_category']
            category = self.intent_to_category.get(ai_intent, "Technical/Usage Question")

            # Get template index based on category
            template_index = self.category_to_template.get(category)
            
            # Get product model and normalize to official naming
            raw_product_model = email_info.get('product_model', 'Unknown')
            product_model = self._normalize_product_model(raw_product_model)

            # Log if model was normalized
            if product_model != raw_product_model:
                self.logger.info(f"Product model normalized: '{raw_product_model}' -> '{product_model}'")
            
            # Prepare context for AI
            template_content = ""
            if template_index is not None and 0 <= template_index < len(self.templates):
                template_content = self.templates[template_index]
            
            # --- 查询配件价格 ---
            part_price_info = None
            # 检测是否在询问配件价格 (Sales/Stock intent 或包含价格关键词)
            is_price_inquiry = False
            part_name = None
            keywords = email_info.get("keywords", [])
            email_text = email_content.lower() if email_content else ""

            price_keywords = ["price", "cost", "报价", "价格", "buy", "purchase", "order",
                            "how much", "dollar", "usd", "欧元", "英镑", "替换", "配件",
                            "spare", "part", "replacement", "accessory", "screen", "屏幕"]

            if ai_intent == "Sales/Stock" or any(kw.lower() in email_text for kw in price_keywords):
                is_price_inquiry = True
                # 尝试获取产品型号和配件名称
                # 从 keywords 中提取配件名称
                for kw in keywords:
                    if any(p in kw.lower() for p in ["adapter", "电源", "cable", "线", "switch", "开关",
                                                      "foot", "脚踏", "case", "壳", "保护", "USB", "数据线",
                                                      "screen", "屏幕"]):
                        part_name = kw
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

                ai_context = {
                    "customer_email": email_content,
                    "product_model": product_model,
                    "issue_category": category,
                    "template_content": template_content,
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
        """Get information from product manual using pdf_reader module"""
        try:
            # Get PDF path using the product model
            pdf_path = get_pdf_path(product_model, self.product_manuals_path)
            if not pdf_path:
                self.logger.warning(f"No manual found for {product_model}")
                return None
            
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
    templates_path = r"e:\My Docment\Celeste\客服\售后模板\Customer Service Email.txt"
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
