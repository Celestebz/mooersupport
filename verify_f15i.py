import sys
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Add current directory to path
sys.path.append(r"e:\My Docment\Celeste\客服")

from response_generator import ResponseGenerator

templates_path = r"e:\My Docment\Celeste\客服\售后模板\Customer Service Email.txt"
pdf_reader_path = r"e:\My Docment\Celeste\客服\pdf_reader.py"
product_manuals_path = r"e:\My Docment\Celeste\客服\MOOER产品说明书"

generator = ResponseGenerator(templates_path, pdf_reader_path, product_manuals_path)

# Test Case: F15i Firmware Update
email_body = """i have a Mooer F15i li and when i try to update the firmware, i can't.
From PC, the software cannot detect my F15i when it is connected via USB.
Please assist."""

email_info = {
    "product_model": "F15i",
    "problem_category": "Firmware Update",
    "sentiment": "negative",
    "keywords": ["firmware", "update", "detect", "usb"],
    "subject": "F15i firmware update issue"
}

print("Generating response for F15i...")
response = generator.generate_response(email_info, email_body)
print("\n=== FINAL RESPONSE ===\n")
print(response)
