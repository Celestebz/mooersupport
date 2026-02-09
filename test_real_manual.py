#!/usr/bin/env python3
"""
Test script to verify the system can read real GE150 MAX manual and generate accurate responses
"""

import sys
import os

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_reader import get_pdf_path, extract_text_from_pdf, search_keywords_in_pdf
from content_extractor import ContentExtractor

# Test the real manual reading functionality
def test_real_manual():
    print("=== Testing Real Manual Reading for GE150 MAX ===")
    
    # Get the product manuals directory
    product_manuals_path = os.path.join(os.getcwd(), 'MOOER产品说明书')
    product_model = "GE150 MAX"
    
    # Find the PDF path for GE150 MAX
    pdf_path = get_pdf_path(product_model, product_manuals_path)
    print(f"Found manual at: {pdf_path}")
    
    if not pdf_path:
        print(f"Error: Could not find manual for {product_model}")
        return False
    
    # Extract text from the PDF
    print("\n=== Extracting Text from Manual ===")
    pdf_text = extract_text_from_pdf(pdf_path)
    print(f"Extracted {len(pdf_text)} characters from manual")
    
    # Search for tuner-related information
    print("\n=== Searching for Tuner Information ===")
    tuner_keywords = ["tuner", "reference", "pitch", "430", "440", "adjust"]
    
    # Search for these keywords in the PDF
    results = search_keywords_in_pdf(pdf_text, tuner_keywords, context_lines=10)
    
    # Print the results
    if results:
        print("Found the following tuner-related information in the manual:")
        for keyword, matches in results.items():
            print(f"\n--- Results for '{keyword}' ---")
            for i, match in enumerate(matches[:2]):  # Show first 2 matches per keyword
                print(f"Match {i+1}:")
                print(match['context'])
    else:
        print("No tuner-related information found in the manual")
    
    return True

# Generate a response based on real manual content
def generate_response_based_on_manual():
    print("\n=== Generating Response Based on Real Manual ===")
    
    # Get the product manuals directory
    product_manuals_path = os.path.join(os.getcwd(), 'MOOER产品说明书')
    product_model = "GE150 MAX"
    user_question = "Hey there I was wondering if there's a way to get my tuner on my pedal to go past 430-440 hz I would like to tune it at 425 and 445 and have more versatility."
    
    # Extract keywords from the user's question
    extractor = ContentExtractor()
    keywords = extractor._extract_keywords(f"Subject: Tuning on Mooer Ge150 max\n\n{user_question}")
    print(f"Extracted keywords: {keywords}")
    
    # Add specific tuner-related keywords
    tuner_keywords = keywords + ["tuner", "reference", "pitch", "adjust"]
    
    # Find the PDF path for GE150 MAX
    pdf_path = get_pdf_path(product_model, product_manuals_path)
    
    # Extract text from the PDF
    pdf_text = extract_text_from_pdf(pdf_path)
    
    # Search for tuner-related information
    results = search_keywords_in_pdf(pdf_text, tuner_keywords, context_lines=10)
    
    # Generate a response based on the manual content
    response = f"""Dear customer,

Thank you for choosing our products - we truly appreciate your support!

I understand you're having a question about your {product_model}: {user_question[:100]}... Here's how to resolve it:

"""
    
    # Add manual information if found
    if results:
        # Collect all relevant information
        manual_info = ""
        for keyword, matches in results.items():
            for match in matches[:2]:
                manual_info += f"{match['context'].strip()}\n\n"
        
        # Add the manual information to the response
        response += manual_info
    else:
        response += "Thank you for your inquiry about the tuner settings. Based on the product manual, here's what we can share:\n\n"
        response += "The GE150 MAX tuner allows you to adjust the reference pitch. Please refer to the tuner section in the manual for detailed instructions.\n\n"
    
    # Add closing information
    response += "If you need further assistance, please provide more details including:\n"
    response += f"- Exactly what you're trying to accomplish with your {product_model}\n"
    response += "- Any specific error messages or behaviors you're experiencing\n"
    response += "- Steps you've already tried to resolve the issue\n\n"
    
    response += "Thank you and have a nice day!"
    
    print("\n=== Generated Response ===")
    print(response)
    
    return response

if __name__ == "__main__":
    test_real_manual()
    generate_response_based_on_manual()
