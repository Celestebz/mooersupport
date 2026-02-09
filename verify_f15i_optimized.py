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
email_body = """i have a Mooer f15i li and when i try to update the firmware, i can't 
 
 From PC 
 the software cannot detect my F15 when it is connected via USB....i have connected directly to motherboard and not via any USB hub 
 
 From iAMP app on my android device 
 It just says upgrade to latest firmware but doesn't tell me how 
 
 I have tried multiple USB cables and multiple ports...however the Mooer Studio software cannot detect the F15i.  Am i using the wrong software to detect?  When the F15i is plugged in, audio from the PC can be heard through it...so the pc does detect it...just that the Mooer software does not.  Please help. 
 
 On the android device...it just persistently shoes update to latest firmware but nothing else...i cannot click on that message or anything."""

email_info = {
    "product_model": "F15i",
    "problem_category": "Firmware Update",
    "sentiment": "negative",
    "keywords": ["firmware", "update", "detect", "usb", "android"],
    "subject": "F15i Firmware Update Issue"
}

print("Generating response for F15i (Optimized Retrieval)...")
response = generator.generate_response(email_info, email_body)
print("\n=== FINAL RESPONSE ===\n")
print(response)
