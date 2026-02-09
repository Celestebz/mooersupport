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
            "Price/Stock Inquiry": None,  # 需要 manual fill-in
            "Feedback/Suggestion": 11,  # 感谢顾客的反馈
        }
        
        # Initialize external data fetcher
        self.external_fetcher = ExternalDataFetcher()
    
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
        self.logger.info(f"Tool called: search_product_manual for {product_model}, query: {query}")
        # Convert query string to list of keywords
        keywords = [w.strip() for w in query.split() if len(w.strip()) > 2]
        
        # Primary Search
        info = self._get_manual_info(product_model, keywords)
        
        # Fallback Search if primary search returns nothing or very little
        if not info or len(info) < 50:
             self.logger.info(f"Primary search failed. Trying fallback search for broader terms.")
             fallback_keywords = []
             if "update" in query.lower() or "firmware" in query.lower():
                 fallback_keywords = ["firmware", "update", "upgrade"]
             elif "reset" in query.lower():
                 fallback_keywords = ["reset", "factory"]
             
             if fallback_keywords:
                 info = self._get_manual_info(product_model, fallback_keywords)

        if info:
            return info
        return f"No specific information found in manual for '{query}'. Try different keywords."

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

    def generate_response(self, email_info, email_content):
        """Generate a response based on email information"""
        try:
            # Determine template index based on category
            category = email_info['problem_category']
            template_index = self.category_to_template.get(category)
            
            # Get product model
            product_model = email_info['product_model']
            
            # Prepare context for AI
            template_content = ""
            if template_index is not None and 0 <= template_index < len(self.templates):
                template_content = self.templates[template_index]
            
            # --- AI Generation with Tools ---
            if self.ai_handler.enabled:
                ai_context = {
                    "customer_email": email_content,
                    "product_model": product_model,
                    "issue_category": category,
                    "template_content": template_content,
                    # Pass additional context from extraction
                    "urgency": email_info.get("urgency", "Medium"),
                    "key_issues": email_info.get("keywords", [])
                }
                
                # Define tool map
                tool_map = {
                    "search_product_manual": self.search_product_manual,
                    "get_firmware_update_guide": self.get_firmware_update_guide,
                    "check_official_downloads": self.check_official_downloads,
                    "escalate_to_human": self.escalate_to_human
                }
                
                ai_response = self.ai_handler.generate_email_draft(
                    ai_context, 
                    tools=TOOLS_SCHEMA, 
                    tool_map=tool_map
                )
                
                if ai_response:
                    if "ESCALATION_TRIGGERED" in ai_response:
                        self.logger.info("Response generation skipped due to escalation.")
                        return None # Or handle escalation logic here
                        
                    self.logger.info("Using AI generated response with tools")
                    return ai_response
            # -----------------------------
            
            # Fallback to legacy logic if AI is disabled or fails
            self.logger.info("AI disabled or failed, falling back to legacy generation")
            
            # ... Legacy fallback logic below (simplified for brevity) ...
            return self._generate_default_response(product_model, category)
            
        except Exception as e:
            self.logger.error(f"Error generating response: {e}", exc_info=True)
            return self._generate_default_response(email_info.get('product_model'), email_info.get('problem_category'))
            
    # REMOVED: _customize_template
    # REMOVED: _generate_technical_response_with_info
    # REMOVED: _generate_technical_response
    # (These were the legacy string-concatenation methods that caused the weird formatting)
    
    def _generate_default_response(self, product_model, category):
        """Generate a default response when no specific template matches"""
        # ... (Keep existing default response for safety) ...
        response = "Dear customer,\n\nThank you for contacting MOOER Support.\n\n"
        if product_model:
            response += f"Regarding your inquiry about the {product_model}, "
        else:
            response += "Regarding your inquiry, "
        response += "we have received your message. A support agent will review your case and reply shortly.\n\nBest regards,\nMOOER Support Team"
        return response
    
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
