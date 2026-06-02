import re
import logging
import os
from ai_handler import AIHandler

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
                "email_type": analysis.get("email_type", "other")  # New: product_related, non_product, being_processed, other
            }
            
            # Sanitize Unknown or wrong model - add fallback check against subject
            wrong_models = ["Unknown", None, "GL100", "GS1000", "GE300 Lite"]

            # Extra check: if AI returned wrong GE150 variant, correct it based on actual email content
            # This handles cases like: AI returns GE150 Plus but user asked about GE150 Pro
            body_lower = body.lower()
            subject_lower = subject.lower()

            # Priority: Pro > MAX > Plus > Base GE150
            # Check body first (most reliable), then subject
            if "ge150 pro" in body_lower or "ge150pro" in body_lower:
                info["product_model"] = "GE150 Pro"
                self.logger.info("Corrected to GE150 Pro based on body content")
            elif "ge150 max" in body_lower:
                info["product_model"] = "GE150 MAX"
                self.logger.info("Corrected to GE150 MAX based on body content")
            elif "ge150 plus" in body_lower and ("ge150" in body_lower):
                info["product_model"] = "GE150 Plus"
                self.logger.info("Corrected to GE150 Plus based on body content")
            # Check subject only if body doesn't have clear info
            elif info["product_model"] in ["GE150", "GE150 Plus"]:
                if "ge150 pro" in subject_lower:
                    info["product_model"] = "GE150 Pro"
                    self.logger.info("Corrected to GE150 Pro based on subject content")
                elif "ge150 max" in subject_lower:
                    info["product_model"] = "GE150 MAX"
                    self.logger.info("Corrected to GE150 MAX based on subject content")
                elif "ge150 plus" not in body_lower:
                    # Only keep GE150 if body doesn't mention Plus/Pro/MAX
                    # If subject has "plus" but body doesn't, it's likely a false positive like "GE150 plus iPhone"
                    if info["product_model"] == "GE150 Plus":
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
            return {
                "product_model": None,
                "problem_category": "Technical Support",
                "sentiment": "neutral",
                "keywords": [],
                "subject": subject,
                "body": body,
                "email_type": "other"
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
            "GE150", "GE200", "GE250", "GE300", "GE1000", "GE100", "GE200 Pro", "GE150 Pro",
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
        ge_match = re.search(r'GE\s?(\d+)', text_upper)
        if ge_match:
            return f"GE{ge_match.group(1)}"
            
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
