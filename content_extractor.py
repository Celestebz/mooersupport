import re
import logging
import os
from ai_handler import AIHandler
from issue_facts import extract_issue_facts

class ContentExtractor:
    """Extracts relevant information from email content using AI"""
    
    def __init__(self):
        """Initialize ContentExtractor"""
        self.logger = logging.getLogger(__name__)
        self.ai_handler = AIHandler()
    
    def extract_info(self, email_content, cc_list=None, sender_email=None):
        """Extract relevant information from email content using AI

        Args:
            email_content: The email content (subject + body)
            cc_list: List of CC email addresses (optional)
            sender_email: Sender's email address (optional)
        """
        # Split subject and body roughly for analysis
        lines = email_content.split('\n')
        subject = ""
        body = email_content

        for i, line in enumerate(lines):
            if line.strip().lower().startswith("subject:"):
                subject = line.strip()[8:].strip()
                body = '\n'.join(lines[i+1:])
                break

        # Use AI to analyze content
        if self.ai_handler.enabled:
            analysis = self.ai_handler.analyze_email_content(subject, body, cc_list, sender_email)

            # Normalize AI response keys (LLM sometimes returns camelCase like "Product Model")
            normalized = {}
            for k, v in analysis.items():
                normalized[k.lower().replace(" ", "_")] = v
            analysis = normalized

            # Map AI output to legacy structure for compatibility
            info = {
                "product_model": analysis.get("product_model"),
                "problem_category": analysis.get("intent", "Technical Support"),
                "sentiment": analysis.get("sentiment", "Neutral").lower(),
                "keywords": analysis.get("key_issues", []),
                "subject": subject,
                "body": body,
                # New fields
                "urgency": analysis.get("urgency"),
                "language": analysis.get("language"),
                "mail_category": analysis.get("mail_category"),
                "issue_category": analysis.get("issue_category"),
                "reply_template_category": analysis.get("reply_template_category"),
                "classification_confidence": analysis.get("classification_confidence"),
                "classification_reason": analysis.get("classification_reason"),
                "classification_evidence": analysis.get("evidence", []),
                "needs_human_review": analysis.get("needs_human_review", False),
                "issue_facts": analysis.get("issue_facts") or analysis.get("issue_fact"),
                "issue_fingerprint": analysis.get("issue_fingerprint"),
            }

            intent_to_mail_category = {
                "Technical Support": "technical_support",
                "Firmware Update": "firmware_update",
                "Warranty/Repair": "warranty_repair",
                "Sales/Stock": "sales_stock",
                "Spam": "spam_irrelevant",
                "System Notification": "system_notification",
                "Gratitude": "customer_followup_ack",
                "Partnership/Collaboration": "business_media",
                "Press/Media": "business_media",
                "Dealer Inquiry": "business_media",
                "Other": "unclassified",
            }
            if not info["mail_category"]:
                info["mail_category"] = intent_to_mail_category.get(info["problem_category"], "unclassified")
                info["needs_human_review"] = True
            if not info["issue_category"]:
                info["issue_category"] = "unknown_issue"
                info["needs_human_review"] = True
            if not info["reply_template_category"]:
                info["reply_template_category"] = "manual_human_reply"
                info["needs_human_review"] = True
            if info["classification_confidence"] is None:
                info["classification_confidence"] = 0.5
                info["needs_human_review"] = True

            local_facts = extract_issue_facts(subject, body, fallback_model=info.get("product_model"))
            if not info.get("issue_facts"):
                info["issue_facts"] = local_facts
            if not info.get("issue_fingerprint"):
                info["issue_fingerprint"] = local_facts.get("issue_fingerprint")
            if local_facts.get("issue_fingerprint") == "app_version_too_low_connection_failure":
                info["issue_fingerprint"] = "app_version_too_low_connection_failure"
                info["issue_category"] = "app_version_too_low_connection_failure"
                info["reply_template_category"] = "known_solution_reply"
                info["problem_category"] = "Technical Support"
                info["mail_category"] = "technical_support"
                info["classification_confidence"] = max(float(info.get("classification_confidence") or 0.0), 0.95)
                info["needs_human_review"] = False
            if local_facts.get("product_model") and info.get("product_model"):
                local_model = local_facts.get("product_model")
                ai_model = info.get("product_model")
                if local_model != ai_model and local_facts.get("negative_reasons"):
                    info["product_model"] = local_model
                    info["needs_human_review"] = True
                    info["classification_confidence"] = min(float(info.get("classification_confidence") or 0.5), 0.6)
            
            # Sanitize Unknown or wrong model - add fallback check against subject
            wrong_models = ["Unknown", None, "GL100", "GS1000", "GE300 Lite"]

            # Extra check: if AI returned wrong GE150 variant, correct it based on actual email content
            # This handles cases like: AI returns GE150 Plus but user asked about GE150 Pro
            body_lower = body.lower()
            subject_lower = subject.lower()

            # --- GE100 Series Anti-Confusion (CRITICAL: GE100/GE100 Pro/GE100 Pro Li are different products) ---
            # Priority: Pro Li > Pro > Base GE100
            if "ge100 pro li" in body_lower or "ge100proli" in body_lower:
                info["product_model"] = "GE100 Pro Li"
                self.logger.info("Corrected to GE100 Pro Li based on body content")
            elif "ge100 pro" in body_lower or "ge100pro" in body_lower:
                # Make sure it's not "ge100 pro li" which was already handled above
                if "ge100 pro li" not in body_lower and "ge100proli" not in body_lower:
                    info["product_model"] = "GE100 Pro"
                    self.logger.info("Corrected to GE100 Pro based on body content")
            # Check subject if body doesn't have clear info
            elif info["product_model"] in ["GE100"]:
                if "ge100 pro li" in subject_lower:
                    info["product_model"] = "GE100 Pro Li"
                    self.logger.info("Corrected to GE100 Pro Li based on subject content")
                elif "ge100 pro" in subject_lower:
                    info["product_model"] = "GE100 Pro"
                    self.logger.info("Corrected to GE100 Pro based on subject content")

            # --- GE150 Series Anti-Confusion ---
            # Priority: Pro > MAX > Plus > Base GE150
            # Check body first (most reliable), then subject
            ge150_pro_in_body = "ge150 pro" in body_lower or "ge150pro" in body_lower
            ge150_pro_in_subj = "ge150 pro" in subject_lower
            ge150_max_in_body = "ge150 max" in body_lower
            ge150_max_in_subj = "ge150 max" in subject_lower
            ge150_plus_in_body = "ge150 plus" in body_lower
            ge150_plus_in_subj = "ge150 plus" in subject_lower

            if ge150_pro_in_body:
                info["product_model"] = "GE150 Pro"
                self.logger.info("Corrected to GE150 Pro based on body content")
            elif ge150_max_in_body:
                info["product_model"] = "GE150 MAX"
                self.logger.info("Corrected to GE150 MAX based on body content")
            elif ge150_plus_in_body:
                info["product_model"] = "GE150 Plus"
                self.logger.info("Corrected to GE150 Plus based on body content")
            # Check subject when body doesn't have variant info OR model is wrong/missing
            elif (info["product_model"] in ["GE150", "GE150 Plus", None]
                  and not ge150_pro_in_body
                  and not ge150_max_in_body
                  and not ge150_plus_in_body):
                if ge150_pro_in_subj:
                    info["product_model"] = "GE150 Pro"
                    self.logger.info("Corrected to GE150 Pro based on subject content")
                elif ge150_max_in_subj:
                    info["product_model"] = "GE150 MAX"
                    self.logger.info("Corrected to GE150 MAX based on subject content")
                elif info["product_model"] == "GE150 Plus" and not ge150_plus_in_subj:
                    # Subject has "GE150 plus" but body doesn't → likely false positive
                    info["product_model"] = "GE150"
                    self.logger.info("Corrected GE150 Plus -> GE150 (false positive)")
            if info["product_model"] in wrong_models:
                # First try body, then try subject
                legacy_model = self._extract_product_model(body)
                if not legacy_model:
                    legacy_model = self._extract_product_model(subject)
                if legacy_model:
                    self.logger.info(f"AI identified wrong model, using legacy regex found: {legacy_model}")
                    info["product_model"] = legacy_model
                elif info["product_model"] in wrong_models:
                    # If AI still returned wrong known values, clear it
                    info["product_model"] = None
            else:
                # NEW: Cross-check AI result with actual email content
                # If AI returned a model that's NOT in the email, correct it
                ai_model = info["product_model"]
                if ai_model:
                    # Check if AI model appears in email (case-insensitive)
                    ai_model_normalized = ai_model.lower().replace(" ", "")
                    subject_check = subject_lower.replace(" ", "")
                    body_check = body_lower.replace(" ", "")

                    # If AI model is completely different from email content, use regex
                    if (ai_model_normalized not in subject_check and
                        ai_model_normalized not in body_check and
                        ai_model not in ["Unknown", None]):
                        # AI model not found in email - use regex instead
                        legacy_model = self._extract_product_model(body)
                        if not legacy_model:
                            legacy_model = self._extract_product_model(subject)
                        if legacy_model:
                            self.logger.warning(f"AI returned '{ai_model}' but it's not in email. Corrected to: {legacy_model}")
                            info["product_model"] = legacy_model

            return info
            
        else:
            # Fallback to simple extraction if AI is disabled (Simplified legacy logic)
            self.logger.warning("AI disabled, using basic fallback extraction")
            local_facts = extract_issue_facts(subject, body)
            issue_fingerprint = local_facts.get("issue_fingerprint")
            issue_category = (
                "app_version_too_low_connection_failure"
                if issue_fingerprint == "app_version_too_low_connection_failure"
                else "unknown_issue"
            )
            return {
                "product_model": local_facts.get("product_model"),
                "problem_category": "Technical Support",
                "sentiment": "neutral",
                "keywords": [],
                "subject": subject,
                "body": body,
                "mail_category": "technical_support",
                "issue_category": issue_category,
                "reply_template_category": "manual_human_reply",
                "classification_confidence": 0.0,
                "classification_reason": "AI disabled; basic fallback extraction only",
                "classification_evidence": [],
                "needs_human_review": True,
                "issue_facts": local_facts,
                "issue_fingerprint": issue_fingerprint,
            }

    def clean_email_content(self, email_body):
        """Clean email content by removing signatures, quotes, and other noise"""
        # Keep the regex-based cleaner as a pre-processor for the AI
        if not email_body:
            return ""
        
        # Remove quoted text (lines starting with >)
        lines = email_body.split('\n')
        clean_lines = []
        
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines
            if not stripped:
                continue
            
            # Skip quoted lines
            if stripped.startswith('>'):
                continue
            
            # Skip signature separators
            if any(sep in stripped for sep in ['--', '___', '***', '===']):
                if len(stripped) < 20:
                    break
            
            # Skip common signature patterns
            sig_candidates = [
                'best regards', 'sincerely', 'regards', 
                'best wishes', 'cheers', 'kind regards', 'yours truly',
                'sent from my iphone', 'sent from my android'
            ]
            
            is_sig = False
            line_lower = stripped.lower()
            for sig in sig_candidates:
                if line_lower.startswith(sig):
                    is_sig = True
                    break
            
            if is_sig:
                break
            
            clean_lines.append(line)
        
        clean_content = '\n'.join(clean_lines)
        clean_content = re.sub(r'\n\s*\n', '\n', clean_content)
        return clean_content.strip()

    def _extract_product_model(self, text):
        """Legacy regex-based product model extraction"""
        if not text:
            return None
            
        # Common Mooer product models
        models = [
            "GE150", "GE200", "GE250", "GE300", "GE1000", "GE100 Pro Li", "GE100 Pro", "GE100", "GE200 Pro", "GE150 Pro",
            "Prime P1", "Prime P2", "Prime S1", "GTRS S800", "GTRS", "GWF4",
            "F15i", "F15i Li", "F40i", "F40i Li", "F15",
            "SD10i", "SD30", "SD75", "SD90", "Hornet", "Groove Loop", "Drummer X2", "X2 Drum/Looper",
            "Preamp Live", "Radar", "Ocean Machine", "Red Truck", "Black Truck",
            "GL100", "GL200", "GS1000", "PCL6 MKII"
        ]
        
        text_upper = text.upper()
        
        for model in models:
            # Check for exact model name in upper case
            if model.upper() in text_upper:
                return model
                
        # Try generic regex for "GE" series if specific check failed
        # IMPORTANT: Don't just match GE\d+ — must check for Pro/Li suffixes
        ge_match = re.search(r'GE\s?(\d+)\s*(Pro\s*Li|Pro\s*Plus|Pro|Plus|MAX|Lite)?', text_upper, re.IGNORECASE)
        if ge_match:
            base = f"GE{ge_match.group(1)}"
            suffix = ge_match.group(2)
            if suffix:
                # Normalize suffix spacing
                suffix = suffix.strip()
                if suffix.upper() == "PRO LI":
                    return "GE100 Pro Li"
                return f"{base} {suffix}"
            return base
            
        return None

if __name__ == "__main__":
    # Test the ContentExtractor
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    extractor = ContentExtractor()
    
    # Test email content
    test_email = """
    Subject: F15i update failed
    
    Hi,
    I cannot update my F15i. The PC software doesn't see it.
    
    Best regards,
    John
    """
    
    # Extract information
    info = extractor.extract_info(test_email)
    
    print("\n=== Extracted Information ===")
    print(f"Product Model: {info['product_model']}")
    print(f"Problem Category: {info['problem_category']}")
    print(f"Sentiment: {info['sentiment']}")
    print(f"Keywords: {info['keywords']}")
