#!/usr/bin/env python3
"""
Test script for the Mooer Email Support Automation System
This script tests the complete workflow without actual IMAP connection
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

log_file = os.path.join(logs_dir, f"test_email_automation_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def test_complete_workflow():
    """Test the complete email processing workflow"""
    logger.info("Starting complete workflow test...")
    
    # Create test emails
    test_emails = [
        {
            "subject": "GE150 Firmware Update Issue",
            "sender": "customer@example.com",
            "date": "Tue, 23 Jan 2026 10:00:00 +0000",
            "body": "I'm having trouble updating the firmware on my GE150. My computer won't recognize it when I connect it via USB. I'm using Windows 11. Please help!",
            "id": "123"
        },
        {
            "subject": "GE1000 Loop Station Delay",
            "sender": "user@example.org",
            "date": "Tue, 23 Jan 2026 11:30:00 +0000",
            "body": "I'm experiencing delay issues with the loop station on my GE1000. When I record a loop, there's a noticeable delay that makes it hard to create tight grooves. I also have a GE200, and I can use the loop station reliably on that, so I think it must be an error.",
            "id": "456"
        },
        {
            "subject": "Replacement Power Adapter for Prime P1",
            "sender": "client@example.net",
            "date": "Tue, 23 Jan 2026 14:15:00 +0000",
            "body": "I need to purchase a replacement power adapter for my Prime P1. How much does it cost and how long will it take to ship to Germany?",
            "id": "789"
        }
    ]
    
    # Initialize components (excluding IMAP handler)
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
    
    # Process each test email
    for email in test_emails:
        logger.info(f"Testing email: {email['subject']}")
        
        try:
            # Test 1: Clean and extract content
            clean_body = content_extractor.clean_email_content(email['body'])
            email_content = f"Subject: {email['subject']}\n\n{clean_body}"
            logger.info(f"✓ Email cleaned successfully")
            
            # Test 2: Extract relevant information
            email_info = content_extractor.extract_info(email_content)
            email_info['subject'] = email['subject']
            email_info['body'] = clean_body
            logger.info(f"✓ Content extracted: Product={email_info['product_model']}, Category={email_info['problem_category']}, Sentiment={email_info['sentiment']}")
            
            # Test 3: Generate response
            response_body = response_generator.generate_response(email_info, email_content)
            logger.info(f"✓ Response generated successfully")
            
            # Test 4: Extract recipient email
            def extract_email_address(sender_string):
                import re
                match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sender_string)
                return match.group() if match else None
            
            recipient = extract_email_address(email['sender'])
            logger.info(f"✓ Recipient extracted: {recipient}")
            
            # Test 5: Print the complete response
            logger.info(f"\n=== Generated Response ===")
            logger.info(f"From: support@mooeraudio.com")
            logger.info(f"To: {recipient}")
            logger.info(f"Subject: RE: {email['subject']}")
            logger.info(f"Date: {datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')}")
            logger.info("")
            logger.info(response_body)
            logger.info("=== End of Response ===\n")
            
        except Exception as e:
            logger.error(f"✗ Error processing email {email['subject']}: {e}", exc_info=True)
            continue
    
    logger.info("Complete workflow test finished!")

def test_content_extraction():
    """Test only the content extraction module"""
    logger.info("Testing content extraction module...")
    
    extractor = ContentExtractor()
    
    test_texts = [
        "I need help with my GE150. It won't turn on.",
        "Hello, I'm having firmware update issues with my Prime P2.",
        "Can you tell me the price of a replacement cable for my GS1000?",
        "The Loopation pedal I bought from Amazon is defective. Please replace it."
    ]
    
    for text in test_texts:
        info = extractor.extract_info(text)
        logger.info(f"Text: '{text}'")
        logger.info(f"  Product Model: {info['product_model']}")
        logger.info(f"  Problem Category: {info['problem_category']}")
        logger.info(f"  Sentiment: {info['sentiment']}")
        logger.info(f"  Keywords: {info['keywords']}")
        logger.info("")

def test_response_generation():
    """Test only the response generation module"""
    logger.info("Testing response generation module...")
    
    # Set up response generator
    templates_path = os.path.join(os.getcwd(), "售后模板", "Customer Service Email.txt")
    pdf_reader_path = os.path.join(os.getcwd(), "pdf_reader.py")
    product_manuals_path = os.path.join(os.getcwd(), "MOOER产品说明书")
    
    generator = ResponseGenerator(
        templates_path,
        pdf_reader_path,
        product_manuals_path
    )
    
    test_cases = [
        {
            "email_info": {
                "product_model": "GE150",
                "problem_category": "Firmware Update",
                "sentiment": "neutral",
                "keywords": ["firmware", "update", "USB"]
            },
            "email_content": "Subject: GE150 Firmware Update\n\nI'm having trouble updating the firmware on my GE150. My computer won't recognize it when I connect it via USB."
        },
        {
            "email_info": {
                "product_model": "Prime P1",
                "problem_category": "Parts/Accessories Purchase",
                "sentiment": "neutral",
                "keywords": ["replacement", "power adapter", "Prime P1"]
            },
            "email_content": "Subject: Replacement Power Adapter\n\nI need to buy a replacement power adapter for my Prime P1."
        }
    ]
    
    for i, test_case in enumerate(test_cases):
        logger.info(f"Test case {i+1}:")
        response = generator.generate_response(test_case["email_info"], test_case["email_content"])
        logger.info(f"Response: {response[:100]}...")
        logger.info("")

if __name__ == "__main__":
    logger.info("=== Mooer Email Automation System Test ===")
    
    # Run all tests
    test_content_extraction()
    test_response_generation()
    test_complete_workflow()
    
    logger.info("=== Test Complete ===")
