#!/usr/bin/env python3
"""
Test script to verify special character filtering in email generation
"""

import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from pdf_reader import extract_text_from_pdf
from response_generator import ResponseGenerator

def test_special_character_filtering():
    """Test that special characters are filtered out from email content"""
    print("Testing special character filtering...\n")
    
    # Test PDF extraction with S1 manual (since the example was about S1)
    pdf_path = r"e:\My Docment\Celeste\客服\MOOER产品说明书\S1_Manual_EN.pdf"
    
    print(f"1. Testing PDF extraction from: {pdf_path}")
    text = extract_text_from_pdf(pdf_path)
    if not text:
        print("   Failed to extract text")
        return False
    
    # Check for special characters in extracted text
    special_chars = []
    for i, char in enumerate(text):
        if not (char.isprintable() or char in '\n\t\r\f'):
            special_chars.append((i, char, ord(char)))
    
    if special_chars:
        print(f"   Found {len(special_chars)} special characters in extracted text")
        for pos, char, code in special_chars[:5]:
            print(f"   - Position {pos}: {char!r} (code: {code})")
    else:
        print("   ✓ No special characters found in extracted text")
    
    # Test response generation
    print("\n2. Testing response generation...")
    
    # Create response generator instance
    generator = ResponseGenerator(
        templates_path=r"e:\My Docment\Celeste\客服\售后模板\Customer Service Email.txt",
        pdf_reader_path=r"e:\My Docment\Celeste\客服\pdf_reader.py",
        product_manuals_path=r"e:\My Docment\Celeste\客服\MOOER产品说明书"
    )
    
    # Test email info with S1 product
    email_info = {
        "product_model": "S1",
        "problem_category": "Technical/Usage Question",
        "keywords": ["headphone", "output"],
        "subject": "S1 Headphone Output Question",
        "body": "I have a question about the headphone output on my S1 device"
    }
    
    email_content = f"Subject: {email_info['subject']}\n\n{email_info['body']}"
    
    # Generate response
    response = generator.generate_response(email_info, email_content)
    print(f"   ✓ Generated response (first 300 chars):")
    print(f"   {response[:300]}...")
    
    # Check for special characters in response
    special_chars_in_response = []
    for i, char in enumerate(response):
        if not (char.isprintable() or char in '\n\t\r\f'):
            special_chars_in_response.append((i, char, ord(char)))
    
    if special_chars_in_response:
        print(f"   Found {len(special_chars_in_response)} special characters in response")
        for pos, char, code in special_chars_in_response[:5]:
            print(f"   - Position {pos}: {char!r} (code: {code})")
    else:
        print("   ✓ No special characters found in response")
    
    # Test format_response
    print("\n3. Testing format_response...")
    formatted = generator.format_response(
        recipient="test@example.com",
        subject="Test Subject",
        response_body=response,
        original_email={
            "from": "sender@example.com",
            "date": "2026-01-23",
            "subject": "Test Email",
            "body": "Test email body with some \x01 special \x02 characters"
        }
    )
    
    print(f"   ✓ Formatted response (first 300 chars):")
    print(f"   {formatted[:300]}...")
    
    # Check for special characters in formatted response
    special_chars_in_formatted = []
    for i, char in enumerate(formatted):
        if not (char.isprintable() or char in '\n\t\r\f'):
            special_chars_in_formatted.append((i, char, ord(char)))
    
    if special_chars_in_formatted:
        print(f"   Found {len(special_chars_in_formatted)} special characters in formatted response")
        for pos, char, code in special_chars_in_formatted[:5]:
            print(f"   - Position {pos}: {char!r} (code: {code})")
    else:
        print("   ✓ No special characters found in formatted response")
    
    print("\n4. Testing example from user query...")
    # Create a test string with the problematic pattern
    test_string = "Regarding 'S1': \n●Individual\u0001headphone\u0001output \u0001\u0001\u0001\u0001 \n●Two\u0001main\u0001outputs\u0001allow\u0001users\u0001to\u0001set\u0001stereo\u0001connections \u0001\u0001\u0001\u0001"
    
    # Filter it using our method
    filtered = ''.join(char for char in test_string if char.isprintable() or char in '\n\t\r\f')
    
    print(f"   Original (with special chars): {test_string[:100]}...")
    print(f"   Filtered: {filtered[:100]}...")
    
    if '\u0001' in filtered:
        print("   ✗ Special characters still present!")
    else:
        print("   ✓ Special characters removed successfully")
    
    print("\n=== Test Results ===")
    if not (special_chars or special_chars_in_response or special_chars_in_formatted):
        print("✓ All tests passed! Special characters are being filtered correctly.")
        return True
    else:
        print("✗ Some tests failed. Special characters may still be present in some cases.")
        return False

if __name__ == "__main__":
    test_special_character_filtering()