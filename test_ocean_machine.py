#!/usr/bin/env python3
"""
Test script for Ocean Machine II email query
"""

import logging
import os
from datetime import datetime

# Import custom modules
from content_extractor import ContentExtractor
from response_generator import ResponseGenerator

# Set up logging
logs_dir = os.path.join(os.getcwd(), "logs")
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

log_file = os.path.join(logs_dir, f"test_ocean_machine_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def test_ocean_machine_email():
    """Test the Ocean Machine II email query"""
    logger.info("Testing Ocean Machine II email query...")
    
    # Create the test email
    test_email = {
        "subject": "Ocean Machine II Display Settings",
        "sender": "customer@example.com",
        "date": "Tue, 23 Jan 2026 10:00:00 +0000",
        "body": "Hello,\n\nIs it possible to change display settings to bpm or miliseconds from percents? I have no idea how to use percents to set up time for delays.\n\nBest regards,\nCustomer"
    }
    
    # Initialize components
    content_extractor = ContentExtractor()
    
    # Set up paths for response generator
    templates_path = os.path.join(os.getcwd(), "售后模板", "Customer Service Email.txt")
    pdf_reader_path = os.path.join(os.getcwd(), "pdf_reader.py")
    product_manuals_path = os.path.join(os.getcwd(), "MOOER产品说明书")
    
    response_generator = ResponseGenerator(
        templates_path,
        pdf_reader_path,
        product_manuals_path
    )
    
    try:
        # Clean and extract content
        clean_body = content_extractor.clean_email_content(test_email['body'])
        email_content = f"Subject: {test_email['subject']}\n\n{clean_body}"
        logger.info("✓ Email cleaned successfully")
        
        # Extract relevant information
        email_info = content_extractor.extract_info(email_content)
        email_info['subject'] = test_email['subject']
        email_info['body'] = clean_body
        logger.info(f"✓ Content extracted: Product={email_info['product_model']}, Category={email_info['problem_category']}, Sentiment={email_info['sentiment']}")
        
        # Generate response
        response_body = response_generator.generate_response(email_info, email_content)
        logger.info("✓ Response generated successfully")
        
        # Print the complete response
        logger.info(f"\n=== Generated Response ===")
        logger.info(f"From: support@mooeraudio.com")
        logger.info(f"To: customer@example.com")
        logger.info(f"Subject: RE: {test_email['subject']}")
        logger.info(f"Date: {datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')}")
        logger.info("")
        logger.info(response_body)
        logger.info("=== End of Response ===")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Error processing email: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    test_ocean_machine_email()
