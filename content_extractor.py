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
    
    def extract_info(self, email_content):
        """Extract relevant information from email content using AI"""
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
            analysis = self.ai_handler.analyze_email_content(subject, body)
            
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
                "language": analysis.get("language")
            }
            
            # Sanitize Unknown model
            if info["product_model"] == "Unknown":
                info["product_model"] = None
                
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
                "body": body
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
